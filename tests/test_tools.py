"""Tests for the deterministic tool layer.

Everything here runs without an API key. These are the checks that make the eval
trustworthy: if validation or the account enum is wrong, every metric downstream is
measuring the wrong thing.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from ledger_agent.chart_of_accounts import account_codes, is_valid_code
from ledger_agent.schemas import JournalEntry, JournalLine, to_cents
from ledger_agent.tools import (
    ALL_TOOLS,
    POST_JOURNAL_ENTRY,
    SEARCH_ACCOUNTS,
    VALIDATE_JOURNAL_ENTRY,
    extract_posted_entry,
    select_tools,
    validate_entry,
)

TODAY = dt.date(2026, 3, 1)


def entry(*lines: tuple[str, str, str], memo: str = "test") -> JournalEntry:
    """Build an entry from (account_code, debit, credit) triples."""
    return JournalEntry(
        entry_date=TODAY,
        memo=memo,
        lines=[
            JournalLine(
                account_code=code,
                description="line",
                debit=Decimal(debit),
                credit=Decimal(credit),
            )
            for code, debit, credit in lines
        ],
    )


# --- balancing ---------------------------------------------------------------------

def test_balanced_entry_is_valid() -> None:
    result = validate_entry(entry(("6010", "100.00", "0.00"), ("2010", "0.00", "100.00")))
    assert result.valid
    assert result.issues == []


def test_unbalanced_entry_reports_the_difference() -> None:
    result = validate_entry(entry(("6010", "100.00", "0.00"), ("2010", "0.00", "90.00")))
    assert not result.valid
    issue = next(i for i in result.issues if i.code == "UNBALANCED")
    assert "10.00" in issue.message


def test_multi_line_entry_balances_across_lines() -> None:
    result = validate_entry(
        entry(
            ("6010", "500.00", "0.00"),
            ("2200", "40.00", "0.00"),
            ("2010", "0.00", "540.00"),
        )
    )
    assert result.valid


def test_cent_level_drift_is_caught() -> None:
    """The case float arithmetic would silently pass."""
    result = validate_entry(entry(("6010", "0.10", "0.00"), ("2010", "0.00", "0.11")))
    assert not result.valid
    assert any(i.code == "UNBALANCED" for i in result.issues)


def test_repeated_decimal_amounts_sum_exactly() -> None:
    lines = [("6010", "0.10", "0.00")] * 3 + [("2010", "0.00", "0.30")]
    assert validate_entry(entry(*lines)).valid


# --- line-level rules --------------------------------------------------------------

def test_unknown_account_is_rejected() -> None:
    result = validate_entry(entry(("9999", "100.00", "0.00"), ("2010", "0.00", "100.00")))
    assert not result.valid
    assert any(i.code == "UNKNOWN_ACCOUNT" for i in result.issues)


def test_line_with_both_sides_is_rejected() -> None:
    result = validate_entry(entry(("6010", "100.00", "100.00"), ("2010", "0.00", "100.00")))
    assert not result.valid
    assert any(i.code == "BOTH_SIDES" for i in result.issues)


def test_empty_line_is_rejected() -> None:
    result = validate_entry(entry(("6010", "0.00", "0.00"), ("2010", "0.00", "100.00")))
    assert any(i.code == "EMPTY_LINE" for i in result.issues)


def test_negative_amount_is_rejected() -> None:
    result = validate_entry(entry(("6010", "-50.00", "0.00"), ("2010", "0.00", "-50.00")))
    assert any(i.code == "NEGATIVE_AMOUNT" for i in result.issues)


def test_entry_with_no_lines_is_rejected() -> None:
    result = validate_entry(JournalEntry(entry_date=TODAY, memo="empty", lines=[]))
    assert not result.valid
    assert result.issues[0].code == "NO_LINES"


# --- rendering for the model -------------------------------------------------------

def test_invalid_result_tells_the_model_to_retry() -> None:
    rendered = validate_entry(entry(("6010", "100.00", "0.00"), ("2010", "0.00", "90.00"))).render()
    assert rendered.startswith("INVALID")
    assert "call this tool again" in rendered.lower()


def test_valid_result_renders_as_valid() -> None:
    rendered = validate_entry(entry(("6010", "1.00", "0.00"), ("2010", "0.00", "1.00"))).render()
    assert rendered.startswith("VALID")


# --- schema ------------------------------------------------------------------------

def test_account_enum_matches_the_chart() -> None:
    """The schema's vocabulary and the chart cannot drift apart."""
    schema = VALIDATE_JOURNAL_ENTRY.input_schema
    enum = schema["properties"]["entry"]["properties"]["lines"]["items"]["properties"][
        "account_code"
    ]["enum"]
    assert enum == account_codes()
    assert all(is_valid_code(code) for code in enum)


def test_every_tool_declares_an_object_schema() -> None:
    for tool in ALL_TOOLS:
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False
        assert tool.input_schema["required"]
        assert tool.description.strip()


def test_validate_and_post_share_the_entry_schema() -> None:
    assert (
        VALIDATE_JOURNAL_ENTRY.input_schema["properties"]["entry"]
        == POST_JOURNAL_ENTRY.input_schema["properties"]["entry"]
    )


# --- handlers ----------------------------------------------------------------------

def test_search_accounts_finds_by_description() -> None:
    output = SEARCH_ACCOUNTS.handler({"query": "cloud hosting"})
    assert "6010" in output


def test_search_accounts_empty_query_returns_whole_chart() -> None:
    output = SEARCH_ACCOUNTS.handler({"query": ""})
    assert all(code in output for code in account_codes())


def test_search_accounts_miss_suggests_a_next_step() -> None:
    output = SEARCH_ACCOUNTS.handler({"query": "zzzznotathing"})
    assert "empty query" in output


def test_malformed_arguments_come_back_as_text() -> None:
    """A bad payload is the model's mistake to fix, so it is told, not raised at."""
    assert VALIDATE_JOURNAL_ENTRY.handler({}).startswith("ERROR")
    assert VALIDATE_JOURNAL_ENTRY.handler({"entry": "not-an-object"}).startswith("ERROR")


def test_post_rejects_an_unbalanced_entry() -> None:
    payload: dict[str, Any] = {
        "entry": {
            "entry_date": "2026-03-01",
            "memo": "unbalanced",
            "lines": [
                {"account_code": "6010", "description": "x", "debit": 100, "credit": 0},
                {"account_code": "2010", "description": "y", "debit": 0, "credit": 90},
            ],
        }
    }
    output = POST_JOURNAL_ENTRY.handler(payload)
    assert output.startswith("REJECTED")


def test_post_accepts_a_balanced_entry() -> None:
    payload: dict[str, Any] = {
        "entry": {
            "entry_date": "2026-03-01",
            "memo": "software",
            "lines": [
                {"account_code": "6010", "description": "x", "debit": 100, "credit": 0},
                {"account_code": "2010", "description": "y", "debit": 0, "credit": 100},
            ],
        }
    }
    assert POST_JOURNAL_ENTRY.handler(payload).startswith("POSTED")


def test_extract_posted_entry_only_returns_valid_terminal_calls() -> None:
    good: dict[str, Any] = {
        "entry": {
            "entry_date": "2026-03-01",
            "memo": "ok",
            "lines": [
                {"account_code": "6010", "description": "x", "debit": 10, "credit": 0},
                {"account_code": "2010", "description": "y", "debit": 0, "credit": 10},
            ],
        }
    }
    assert extract_posted_entry("post_journal_entry", good) is not None
    assert extract_posted_entry("validate_journal_entry", good) is None

    bad = {"entry": {**good["entry"], "lines": good["entry"]["lines"][:1]}}
    assert extract_posted_entry("post_journal_entry", bad) is None


# --- config surface ----------------------------------------------------------------

def test_select_tools_can_withhold_one() -> None:
    """The experiment's independent variable."""
    names = [t.name for t in select_tools(["search_accounts", "post_journal_entry"])]
    assert "validate_journal_entry" not in names
    assert len(select_tools(None)) == len(ALL_TOOLS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.125", "0.13"), ("0.135", "0.14"), ("1.005", "1.01"), ("2.344", "2.34")],
)
def test_rounding_is_half_up_not_bankers(raw: str, expected: str) -> None:
    assert to_cents(Decimal(raw)) == Decimal(expected)
