"""The agent loop.

The model reads an invoice and works toward a posted journal entry. It is given tools
rather than instructions-and-hope: the ledger's rules live in ``validate_journal_entry``
and ``post_journal_entry``, which the model must satisfy, instead of living only in a
prompt it may or may not follow.

The loop terminates on a successful post, on a turn with no tool calls, or at the
iteration cap — whichever comes first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ledger_agent.chart_of_accounts import CHART_OF_ACCOUNTS
from ledger_agent.schemas import JournalEntry
from ledger_agent.tools import (
    ToolDefinition,
    anthropic_tool_params,
    extract_posted_entry,
    get_tool,
    select_tools,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance for typing only
    from anthropic import Anthropic

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# The chart appears here as codes and names only. Full descriptions are reachable
# through search_accounts, so the tool has a real job and the model still is not
# guessing which codes exist.
_ACCOUNT_INDEX = "\n".join(
    f"  {a.code}  {a.name} ({a.type.value})" for a in CHART_OF_ACCOUNTS
)

SYSTEM_PROMPT = f"""\
You are an accounting agent. Given the text of a vendor invoice, you produce and post a \
single balanced double-entry journal entry recording it as a payable.

The chart of accounts:
{_ACCOUNT_INDEX}

Use search_accounts to read what belongs in an account before choosing it.

How to record a vendor invoice:
- Debit the expense or asset account that reflects what was purchased, one line per \
distinct kind of cost.
- Debit recoverable sales tax or VAT to Sales Tax Payable; never fold tax into the \
expense account of the item taxed.
- Credit Accounts Payable for the invoice grand total, because the invoice is not yet paid.
- Total debits must equal total credits, to the cent.
- Use the invoice date as the entry date.

Work in this order: read the invoice, look up any account you are unsure of, then call \
post_journal_entry once with the complete entry. Keep commentary short — the entry is \
the deliverable.
"""


@dataclass(frozen=True)
class AgentConfig:
    """One experimental condition.

    Varying ``tool_names`` is how the harness measures what a tool is worth: withhold
    ``validate_journal_entry`` and the same model must get the arithmetic right unaided.
    """

    name: str
    model: str = DEFAULT_MODEL
    tool_names: list[str] | None = None
    max_iterations: int = 6
    temperature: float = 0.0
    max_tokens: int = 2048

    def tools(self) -> list[ToolDefinition]:
        return select_tools(self.tool_names)


@dataclass
class ToolCallRecord:
    """One tool invocation, kept for the transcript and for debugging a bad run."""

    name: str
    arguments: dict[str, Any]
    result: str


@dataclass
class AgentResult:
    """Everything one run produced, successful or not."""

    entry: JournalEntry | None = None
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    stop_reason: str = "unknown"
    error: str | None = None

    @property
    def posted(self) -> bool:
        """Whether the run ended with an entry accepted by the ledger."""
        return self.entry is not None

    @property
    def validation_calls(self) -> int:
        return sum(1 for c in self.tool_calls if c.name == "validate_journal_entry")

    @property
    def post_attempts(self) -> int:
        return sum(1 for c in self.tool_calls if c.name == "post_journal_entry")


def run_agent(
    invoice_text: str,
    config: AgentConfig,
    client: Anthropic,
) -> AgentResult:
    """Run the agent over one invoice and return what happened.

    Transport and provider errors are captured on the result rather than raised: a
    harness scoring twenty cases should record a failed case and keep going.
    """
    tools = anthropic_tool_params(config.tools())
    prompt = f"Record this invoice as a journal entry.\n\n<invoice>\n{invoice_text}\n</invoice>"
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    result = AgentResult()

    for iteration in range(1, config.max_iterations + 1):
        result.iterations = iteration
        try:
            response = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=SYSTEM_PROMPT,
                tools=tools,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
            )
        except Exception as exc:  # recorded on the result, not raised past the harness
            result.error = f"{type(exc).__name__}: {exc}"
            result.stop_reason = "api_error"
            return result

        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens
        result.stop_reason = response.stop_reason or "unknown"

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:
            # The model stopped calling tools. If it never posted, that is a failed run,
            # and the caller sees it as one.
            result.stop_reason = "end_turn"
            return result

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            arguments = dict(block.input) if isinstance(block.input, dict) else {}
            tool = get_tool(block.name)
            if tool is None:
                # Only reachable if the provider echoes a tool we did not send.
                output = f"ERROR: unknown tool '{block.name}'."
            else:
                output = tool.handler(arguments)

            result.tool_calls.append(
                ToolCallRecord(name=block.name, arguments=arguments, result=output)
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output}
            )

            entry = extract_posted_entry(block.name, arguments)
            if entry is not None and output.startswith("POSTED"):
                result.entry = entry

        if result.posted:
            result.stop_reason = "posted"
            return result

        messages.append({"role": "user", "content": tool_results})

    result.stop_reason = "max_iterations"
    return result
