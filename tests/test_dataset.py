"""Integrity checks on the labeled dataset.

The labels are the ground truth. If an invoice's arithmetic does not close, or a label
contradicts the invoice it points at, every metric downstream is measuring the dataset's
bugs rather than the agent's. These run offline and gate CI for exactly that reason.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from eval.harness import Case, load_cases

from ledger_agent.chart_of_accounts import is_valid_code

CASES = load_cases()

SUBTOTAL = re.compile(r"Subtotal\s+([\d,\.]+)")
TAX = re.compile(r"Sales tax \([\d\.]+%\)\s+([\d,\.]+)")
TOTAL = re.compile(r"TOTAL DUE\s+([\d,\.]+)")


def money(match: re.Match[str] | None) -> Decimal:
    return Decimal(match.group(1).replace(",", "")) if match else Decimal("0.00")


def test_dataset_is_not_empty() -> None:
    assert len(CASES) >= 20


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_invoice_arithmetic_closes(case: Case) -> None:
    """Subtotal plus tax must equal the stated total, or the entry cannot balance."""
    subtotal = money(SUBTOTAL.search(case.text))
    tax = money(TAX.search(case.text))
    total = money(TOTAL.search(case.text))
    assert subtotal > 0, "no subtotal found"
    assert subtotal + tax == total


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_labels_reference_real_accounts(case: Case) -> None:
    assert case.expected_accounts
    for code in case.expected_accounts:
        assert is_valid_code(code), f"{code} is not in the chart of accounts"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_every_case_credits_accounts_payable(case: Case) -> None:
    """Each invoice is unpaid on receipt, so every entry has a payable side."""
    assert "2010" in case.expected_accounts


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_tax_label_matches_the_invoice(case: Case) -> None:
    """Sales Tax Payable is labeled if and only if the invoice charges tax."""
    charges_tax = money(TAX.search(case.text)) > 0
    assert ("2200" in case.expected_accounts) == charges_tax


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_fixtures_are_marked_synthetic(case: Case) -> None:
    """Nothing here should ever read as a real invoice if it escapes the repo."""
    assert "SYNTHETIC TEST FIXTURE" in case.text


def test_case_ids_are_unique() -> None:
    ids = [c.case_id for c in CASES]
    assert len(ids) == len(set(ids))


def test_dataset_exercises_a_range_of_accounts() -> None:
    """A dataset that only ever hits two accounts would not test classification."""
    covered = {code for case in CASES for code in case.expected_accounts}
    assert len(covered) >= 10


def test_multi_account_cases_exist() -> None:
    """Some cases must require splitting one invoice across several accounts."""
    assert sum(1 for c in CASES if len(c.expected_accounts) >= 4) >= 2
