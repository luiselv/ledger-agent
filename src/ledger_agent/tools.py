"""Tool definitions: schema and handler, authored once.

Two consumers read this module — the agent loop in ``agent.py`` and the MCP server in
``mcp_server.py``. Neither declares its own schema, so the MCP surface and the surface
the model sees cannot drift apart.

Every handler here is deterministic. The judgment (reading an invoice, choosing an
account) belongs to the model; the tools supply the things a model is bad at and a
computer is exact at: lookup, arithmetic, and validation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import InvalidOperation
from typing import Any

from ledger_agent.chart_of_accounts import (
    CHART_OF_ACCOUNTS,
    account_codes,
    get_account,
    is_valid_code,
)
from ledger_agent.schemas import (
    JournalEntry,
    ValidationIssue,
    ValidationResult,
    to_cents,
)

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolDefinition:
    """A tool the model can call.

    ``input_schema`` is a JSON Schema object. It is handed verbatim to the Anthropic
    Messages API and to MCP, which is the point: one schema, two transports.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


# --- shared schema fragments -------------------------------------------------------

def _journal_entry_schema() -> dict[str, Any]:
    """Build the JSON Schema for a proposed journal entry.

    ``account_code`` carries an ``enum`` generated from the chart of accounts, so an
    invented code is rejected by the provider's schema validation rather than by our
    own checks. Constraining the vocabulary at the schema level removes a whole class
    of failure instead of detecting it after the fact.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["entry_date", "memo", "lines"],
        "properties": {
            "entry_date": {
                "type": "string",
                "description": "Posting date in ISO 8601 format (YYYY-MM-DD).",
            },
            "memo": {
                "type": "string",
                "description": "One-line description of the transaction.",
            },
            "lines": {
                "type": "array",
                "minItems": 2,
                "description": (
                    "The debit and credit lines. Every line sets exactly one of debit "
                    "or credit to a positive amount and leaves the other at 0."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["account_code", "description", "debit", "credit"],
                    "properties": {
                        "account_code": {
                            "type": "string",
                            "enum": account_codes(),
                            "description": "The general-ledger account this line posts to.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Why this line exists, in plain language.",
                        },
                        "debit": {
                            "type": "number",
                            "description": "Debit amount, or 0 when this is a credit line.",
                        },
                        "credit": {
                            "type": "number",
                            "description": "Credit amount, or 0 when this is a debit line.",
                        },
                    },
                },
            },
        },
    }


def _parse_entry(payload: dict[str, Any]) -> JournalEntry | str:
    """Parse an entry from tool arguments, returning an error string on failure.

    A malformed payload comes back as text for the model to read, not as an exception.
    The model wrote these arguments; it is the only party that can fix them.
    """
    raw = payload.get("entry")
    if not isinstance(raw, dict):
        return "ERROR: expected an object under the key 'entry'. Call the tool again with it."
    try:
        return JournalEntry.model_validate(raw)
    except (ValueError, InvalidOperation) as exc:
        return f"ERROR: the entry did not parse: {exc}\nCorrect the shape and call again."


# --- search_accounts ---------------------------------------------------------------

def _handle_search_accounts(payload: dict[str, Any]) -> str:
    query = str(payload.get("query", "")).strip().lower()

    if not query:
        matches = list(CHART_OF_ACCOUNTS)
    else:
        terms = query.split()
        matches = [
            account
            for account in CHART_OF_ACCOUNTS
            if any(
                term in f"{account.code} {account.name} {account.description}".lower()
                for term in terms
            )
        ]

    if not matches:
        return (
            f"No accounts matched '{query}'. Call this tool with an empty query to see "
            "the whole chart, then pick the closest account."
        )

    lines = [f"{len(matches)} account(s) matched:"]
    lines.extend(
        f"  {a.code}  {a.name} ({a.type.value}, normal balance {a.type.normal_balance})\n"
        f"        {a.description}"
        for a in matches
    )
    return "\n".join(lines)


SEARCH_ACCOUNTS = ToolDefinition(
    name="search_accounts",
    description=(
        "Search the chart of accounts by keyword and return matching accounts with "
        "their type, normal balance and a description of what belongs in each. Call "
        "this before choosing an account code when the right account is not obvious. "
        "Pass an empty query to list the entire chart."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Keywords describing the expense or item, e.g. 'cloud hosting "
                    "subscription' or 'sales tax'. Empty string returns everything."
                ),
            }
        },
    },
    handler=_handle_search_accounts,
)


# --- validate_journal_entry --------------------------------------------------------

def validate_entry(entry: JournalEntry) -> ValidationResult:
    """Check a proposed entry for the errors a ledger would reject it for.

    Exposed separately from the tool handler so the harness and the tests can call it
    without going through tool-argument parsing.
    """
    issues: list[ValidationIssue] = []

    if not entry.lines:
        issues.append(
            ValidationIssue(code="NO_LINES", message="The entry has no lines. Add at least two.")
        )
        return ValidationResult(valid=False, issues=issues)

    for index, line in enumerate(entry.lines, start=1):
        if not is_valid_code(line.account_code):
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_ACCOUNT",
                    message=(
                        f"Line {index} posts to account '{line.account_code}', which is not "
                        "in the chart of accounts. Use search_accounts to find a valid code."
                    ),
                )
            )
        if line.debit < 0 or line.credit < 0:
            issues.append(
                ValidationIssue(
                    code="NEGATIVE_AMOUNT",
                    message=(
                        f"Line {index} has a negative amount. Express a reduction by posting "
                        "to the opposite side, not by negating the amount."
                    ),
                )
            )
        if line.debit > 0 and line.credit > 0:
            issues.append(
                ValidationIssue(
                    code="BOTH_SIDES",
                    message=(
                        f"Line {index} sets both debit ({line.debit}) and credit "
                        f"({line.credit}). Split it into two lines."
                    ),
                )
            )
        if line.debit == 0 and line.credit == 0:
            issues.append(
                ValidationIssue(
                    code="EMPTY_LINE",
                    message=f"Line {index} has neither a debit nor a credit amount.",
                )
            )

    debits, credits = entry.total_debits(), entry.total_credits()
    if debits != credits:
        difference = to_cents(abs(debits - credits))
        heavier = "debits" if debits > credits else "credits"
        issues.append(
            ValidationIssue(
                code="UNBALANCED",
                message=(
                    f"The entry does not balance: debits total {debits}, credits total "
                    f"{credits}, so {heavier} exceed the other side by {difference}. A "
                    "common cause is posting the net amount while the invoice total "
                    "includes tax, or omitting the tax line entirely."
                ),
            )
        )

    return ValidationResult(valid=not issues, issues=issues)


def _handle_validate_journal_entry(payload: dict[str, Any]) -> str:
    parsed = _parse_entry(payload)
    if isinstance(parsed, str):
        return parsed
    return validate_entry(parsed).render()


VALIDATE_JOURNAL_ENTRY = ToolDefinition(
    name="validate_journal_entry",
    description=(
        "Check a proposed journal entry before posting it: that debits equal credits, "
        "that every account code exists, and that each line uses exactly one side. "
        "Returns either VALID or a list of specific problems to fix. Call this and "
        "resolve any issues before calling post_journal_entry."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["entry"],
        "properties": {"entry": _journal_entry_schema()},
    },
    handler=_handle_validate_journal_entry,
)


# --- post_journal_entry ------------------------------------------------------------

def _handle_post_journal_entry(payload: dict[str, Any]) -> str:
    parsed = _parse_entry(payload)
    if isinstance(parsed, str):
        return parsed

    result = validate_entry(parsed)
    if not result.valid:
        # Refusing here is what keeps an invalid entry out of the ledger even when the
        # model skips validation. The tool is the enforcement point, not the prompt.
        return "REJECTED — the entry was not posted.\n" + result.render()

    total = parsed.total_debits()
    accounts = ", ".join(
        f"{line.account_code} ({get_account(line.account_code).name})"  # type: ignore[union-attr]
        for line in parsed.lines
    )
    return (
        f"POSTED: entry dated {parsed.entry_date} for {total} across {len(parsed.lines)} "
        f"lines — {accounts}. Nothing further is required."
    )


POST_JOURNAL_ENTRY = ToolDefinition(
    name="post_journal_entry",
    description=(
        "Post the finished journal entry to the ledger. This is the last step: call it "
        "once, with the complete entry, after validation passes. The entry is rejected "
        "if it does not balance or references an unknown account."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["entry"],
        "properties": {"entry": _journal_entry_schema()},
    },
    handler=_handle_post_journal_entry,
)


# --- registry ----------------------------------------------------------------------

ALL_TOOLS: tuple[ToolDefinition, ...] = (
    SEARCH_ACCOUNTS,
    VALIDATE_JOURNAL_ENTRY,
    POST_JOURNAL_ENTRY,
)

_BY_NAME: dict[str, ToolDefinition] = {tool.name: tool for tool in ALL_TOOLS}


def get_tool(name: str) -> ToolDefinition | None:
    """Return the tool named ``name``, or None if it is not registered."""
    return _BY_NAME.get(name)


def select_tools(names: list[str] | None = None) -> list[ToolDefinition]:
    """Return the named tools, or all of them when ``names`` is None.

    The experiment harness uses this to run the same dataset with a tool withheld.
    """
    if names is None:
        return list(ALL_TOOLS)
    return [tool for tool in ALL_TOOLS if tool.name in set(names)]


def anthropic_tool_params(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Render tools into the shape the Anthropic Messages API expects."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def extract_posted_entry(tool_name: str, payload: dict[str, Any]) -> JournalEntry | None:
    """Return the entry from a successful ``post_journal_entry`` call, if it is one.

    The harness needs the structured entry the agent settled on, and the terminal tool
    call is where it lives — the assistant's prose is not the artifact.
    """
    if tool_name != POST_JOURNAL_ENTRY.name:
        return None
    parsed = _parse_entry(payload)
    if isinstance(parsed, str):
        return None
    return parsed if validate_entry(parsed).valid else None


__all__ = [
    "ALL_TOOLS",
    "POST_JOURNAL_ENTRY",
    "SEARCH_ACCOUNTS",
    "VALIDATE_JOURNAL_ENTRY",
    "ToolDefinition",
    "anthropic_tool_params",
    "extract_posted_entry",
    "get_tool",
    "select_tools",
    "validate_entry",
]
