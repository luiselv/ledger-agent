"""Run the agent against a single invoice and show its work.

    uv run python -m ledger_agent.cli eval/dataset/case_013_mixed_equipment_and_supplies.txt

Prints every tool call and the resulting entry. The transcript is the point: it shows
where the model corrected itself, which is invisible in an aggregate score.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ledger_agent.agent import DEFAULT_MODEL, AgentConfig, run_agent
from ledger_agent.chart_of_accounts import get_account
from ledger_agent.env import load_dotenv


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Post one invoice as a journal entry.")
    parser.add_argument("invoice", type=Path, help="Path to a file containing invoice text.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--no-validate-tool",
        action="store_true",
        help="Withhold validate_journal_entry, to see what changes without it.",
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    if not args.invoice.exists():
        print(f"No such file: {args.invoice}", file=sys.stderr)
        return 2

    from anthropic import Anthropic

    config = AgentConfig(
        name="cli",
        model=args.model,
        tool_names=["search_accounts", "post_journal_entry"] if args.no_validate_tool else None,
    )
    result = run_agent(args.invoice.read_text(encoding="utf-8"), config, Anthropic())

    print(f"model: {config.model}    tools: {[t.name for t in config.tools()]}\n")
    for index, call in enumerate(result.tool_calls, start=1):
        first_line = call.result.splitlines()[0] if call.result else ""
        print(f"{index}. {call.name}")
        if call.name == "search_accounts":
            print(f"     query: {call.arguments.get('query', '')!r}")
        print(f"     -> {first_line}")
        # Validation failures are where the loop earns its keep, so they print in full.
        if first_line.startswith(("INVALID", "REJECTED")):
            for detail in call.result.splitlines()[1:]:
                if detail.strip():
                    print(f"        {detail}")
    print()

    if result.error:
        print(f"error: {result.error}", file=sys.stderr)
        return 1

    if result.entry is None:
        print(f"No entry was posted (stop reason: {result.stop_reason}).")
        return 1

    entry = result.entry
    print(f"{entry.entry_date}  {entry.memo}")
    print(f"{'ACCOUNT':<38}{'DEBIT':>12}{'CREDIT':>12}")
    print("-" * 62)
    for line in entry.lines:
        account = get_account(line.account_code)
        label = f"{line.account_code} {account.name if account else '?'}"
        debit = f"{line.debit:,.2f}" if line.debit else ""
        credit = f"{line.credit:,.2f}" if line.credit else ""
        print(f"{label:<38}{debit:>12}{credit:>12}")
    print("-" * 62)
    print(f"{'':38}{entry.total_debits():>12,.2f}{entry.total_credits():>12,.2f}")
    print(
        f"\n{result.iterations} iteration(s), "
        f"{result.input_tokens + result.output_tokens:,} tokens"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
