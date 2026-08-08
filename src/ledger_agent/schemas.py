"""Domain models for invoices and journal entries.

Money is ``Decimal`` throughout, never ``float``. Binary floating point cannot
represent 0.10 exactly, so a journal entry that should balance to the cent will
drift — and in double-entry bookkeeping "off by 0.01" is not a rounding nuisance,
it is an entry the ledger will refuse.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

CENTS = Decimal("0.01")

# Serialized as a string so the JSON schema stays lossless: a Decimal rendered as a
# JSON number would be parsed back as a float by most consumers, reintroducing the
# drift this module exists to avoid.
Money = Annotated[Decimal, Field(description="A monetary amount with two decimal places.")]


def to_cents(value: Decimal | int | str) -> Decimal:
    """Quantize ``value`` to two decimal places, rounding half away from zero.

    ROUND_HALF_UP is the convention accountants expect; Python's default
    ROUND_HALF_EVEN ("banker's rounding") would round 0.125 to 0.12.
    """
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class LineItem(BaseModel):
    """One billed line on an invoice, before any accounting judgment is applied."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="The line description exactly as printed on the invoice.")
    quantity: Decimal = Field(default=Decimal(1), description="Units billed. Defaults to 1.")
    unit_price: Money = Field(description="Price per unit, excluding tax.")
    amount: Money = Field(description="Line total excluding tax (quantity * unit_price).")

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Any:
        # The model returns JSON numbers; converting via str avoids inheriting float
        # imprecision at the boundary.
        if isinstance(value, float):
            return Decimal(str(value))
        return value


class Invoice(BaseModel):
    """A vendor invoice, extracted from unstructured text.

    This is the output schema of the ``extract_invoice`` tool.
    """

    model_config = ConfigDict(extra="forbid")

    vendor_name: str = Field(description="The name of the vendor issuing the invoice.")
    invoice_number: str = Field(description="The vendor's invoice identifier.")
    invoice_date: dt.date = Field(description="Invoice issue date, ISO 8601 (YYYY-MM-DD).")
    currency: str = Field(default="USD", description="ISO 4217 currency code.")
    line_items: list[LineItem] = Field(description="Every billed line, excluding tax and totals.")
    tax_amount: Money = Field(
        default=Decimal("0.00"),
        description="Total sales tax / VAT charged. Zero when the invoice shows no tax.",
    )
    total: Money = Field(description="Invoice grand total, including tax.")

    @field_validator("tax_amount", "total", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Any:
        if isinstance(value, float):
            return Decimal(str(value))
        return value

    def subtotal(self) -> Decimal:
        """Return the sum of line amounts, excluding tax."""
        return to_cents(sum((item.amount for item in self.line_items), Decimal(0)))


class JournalLine(BaseModel):
    """One side of a journal entry: an account and an amount, debit or credit.

    A line carries exactly one of ``debit`` or ``credit`` as a non-zero amount. Modelling
    them as two fields rather than one signed amount matches how ledgers and accountants
    actually read an entry.
    """

    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(description="A code from the chart of accounts.")
    description: str = Field(description="Why this line exists, in plain language.")
    debit: Money = Field(default=Decimal("0.00"), description="Debit amount, or 0.00.")
    credit: Money = Field(default=Decimal("0.00"), description="Credit amount, or 0.00.")

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> Any:
        if value is None:
            return Decimal("0.00")
        if isinstance(value, float):
            return Decimal(str(value))
        return value


class JournalEntry(BaseModel):
    """A proposed double-entry journal entry.

    Validity is not enforced here — an unbalanced entry must be *representable* so that
    ``validate_journal_entry`` can inspect it and tell the model what is wrong. Rejecting
    it at parse time would collapse a correctable mistake into a hard failure.
    """

    model_config = ConfigDict(extra="forbid")

    entry_date: dt.date = Field(description="Posting date, ISO 8601 (YYYY-MM-DD).")
    memo: str = Field(description="One-line description of the transaction.")
    lines: list[JournalLine] = Field(description="The entry's debit and credit lines.")

    def total_debits(self) -> Decimal:
        return to_cents(sum((line.debit for line in self.lines), Decimal(0)))

    def total_credits(self) -> Decimal:
        return to_cents(sum((line.credit for line in self.lines), Decimal(0)))

    def is_balanced(self) -> bool:
        return self.total_debits() == self.total_credits()

    def account_codes(self) -> list[str]:
        """Return the account codes used, in line order (duplicates preserved)."""
        return [line.account_code for line in self.lines]


class ValidationIssue(BaseModel):
    """A single problem found in a proposed entry, phrased for the model to act on."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Machine-readable issue identifier.")
    message: str = Field(description="What is wrong and how to fix it.")


class ValidationResult(BaseModel):
    """The outcome of validating a proposed entry."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    def render(self) -> str:
        """Render for the model.

        Tool output is read by an LLM, not by a parser, so it is phrased as instructions.
        """
        if self.valid:
            return "VALID: the entry balances and every account code exists."
        lines = ["INVALID: fix the issues below and call this tool again.", ""]
        lines.extend(f"- [{issue.code}] {issue.message}" for issue in self.issues)
        return "\n".join(lines)
