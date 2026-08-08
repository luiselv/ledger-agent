"""The chart of accounts.

This module is the vocabulary the model is allowed to speak. Every account code the
agent can emit is declared here, and the tool schemas derive their ``enum`` from
``account_codes()`` — so an invented account like "6999-MISC" is rejected by the API
before it ever reaches our code, rather than being caught by a downstream validation
we have to write and maintain.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AccountType(StrEnum):
    """The five classical account types, which fix each account's normal balance."""

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"

    @property
    def normal_balance(self) -> str:
        """Return the side ('debit' or 'credit') on which this type increases."""
        if self in (AccountType.ASSET, AccountType.EXPENSE):
            return "debit"
        return "credit"


class Account(BaseModel):
    """A single general-ledger account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str
    type: AccountType
    description: str


# A deliberately small chart: broad enough that classification is a real decision,
# small enough that a reader can hold it in their head. Codes follow the conventional
# ranges (1000s assets, 2000s liabilities, 4000s revenue, 5000-6000s expenses).
CHART_OF_ACCOUNTS: tuple[Account, ...] = (
    Account(
        code="1010",
        name="Cash",
        type=AccountType.ASSET,
        description="Operating bank accounts and cash on hand.",
    ),
    Account(
        code="1200",
        name="Accounts Receivable",
        type=AccountType.ASSET,
        description="Amounts owed to the company by customers.",
    ),
    Account(
        code="1400",
        name="Prepaid Expenses",
        type=AccountType.ASSET,
        description=(
            "Costs paid in advance for a service period that extends beyond the "
            "invoice date, such as an annual insurance premium or a prepaid "
            "twelve-month software subscription."
        ),
    ),
    Account(
        code="1500",
        name="Computer Equipment",
        type=AccountType.ASSET,
        description=(
            "Capitalized hardware with a useful life beyond one year: laptops, "
            "servers, monitors. Individually significant purchases, not consumables."
        ),
    ),
    Account(
        code="2010",
        name="Accounts Payable",
        type=AccountType.LIABILITY,
        description="Amounts the company owes to vendors for invoices received.",
    ),
    Account(
        code="2200",
        name="Sales Tax Payable",
        type=AccountType.LIABILITY,
        description=(
            "Sales tax, VAT or GST charged on a purchase and recoverable from or "
            "owed to the tax authority. Tax lines post here, never to the expense "
            "account of the item being taxed."
        ),
    ),
    Account(
        code="4010",
        name="Product Revenue",
        type=AccountType.REVENUE,
        description="Revenue earned from sales of the company's products.",
    ),
    Account(
        code="5010",
        name="Cost of Goods Sold",
        type=AccountType.EXPENSE,
        description=(
            "Direct costs of goods resold to customers: inventory purchases, "
            "manufacturing materials, fulfilment of a specific sale."
        ),
    ),
    Account(
        code="6010",
        name="Software Subscriptions",
        type=AccountType.EXPENSE,
        description=(
            "Recurring SaaS and software licence fees consumed within the period: "
            "cloud hosting, developer tooling, seat-based subscriptions."
        ),
    ),
    Account(
        code="6020",
        name="Professional Fees",
        type=AccountType.EXPENSE,
        description=(
            "Fees paid to outside firms and contractors for services: legal, "
            "accounting, audit, consulting, design and engineering contractors."
        ),
    ),
    Account(
        code="6030",
        name="Marketing and Advertising",
        type=AccountType.EXPENSE,
        description=(
            "Paid advertising, sponsorships, conference booths, content production "
            "and other demand-generation spend."
        ),
    ),
    Account(
        code="6040",
        name="Office Supplies",
        type=AccountType.EXPENSE,
        description=(
            "Low-value consumables used in the course of business: stationery, "
            "kitchen supplies, small peripherals below the capitalization threshold."
        ),
    ),
    Account(
        code="6050",
        name="Travel and Entertainment",
        type=AccountType.EXPENSE,
        description=(
            "Airfare, lodging, ground transport, per-diems and client meals incurred "
            "on company business."
        ),
    ),
    Account(
        code="6060",
        name="Rent and Utilities",
        type=AccountType.EXPENSE,
        description=(
            "Office rent, co-working memberships, electricity, water, internet and "
            "similar facility costs."
        ),
    ),
    Account(
        code="6070",
        name="Bank and Payment Fees",
        type=AccountType.EXPENSE,
        description=(
            "Payment processor fees, wire charges, FX spreads and bank account "
            "maintenance charges."
        ),
    ),
)

_BY_CODE: dict[str, Account] = {account.code: account for account in CHART_OF_ACCOUNTS}


def account_codes() -> list[str]:
    """Return every valid account code, in chart order.

    This is the single source of the ``enum`` used in the tool schemas.
    """
    return [account.code for account in CHART_OF_ACCOUNTS]


def get_account(code: str) -> Account | None:
    """Return the account with ``code``, or None if no such account exists."""
    return _BY_CODE.get(code)


def is_valid_code(code: str) -> bool:
    """Report whether ``code`` names an account in the chart."""
    return code in _BY_CODE


def render_for_prompt() -> str:
    """Render the chart as a compact table for inclusion in a system prompt.

    The model needs the descriptions to classify well; the enum alone only tells it
    which codes exist, not what they mean.
    """
    lines = [f"{'CODE':<6} {'TYPE':<10} {'NAME':<28} DESCRIPTION"]
    for account in CHART_OF_ACCOUNTS:
        lines.append(
            f"{account.code:<6} {account.type.value:<10} {account.name:<28} {account.description}"
        )
    return "\n".join(lines)
