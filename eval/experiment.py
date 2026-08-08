"""Run several configurations over the same dataset and compare them.

The question this exists to answer: does the *design* of the agent — specifically,
giving it a validator it must satisfy — matter more or less than the size of the
model behind it? Both levers are varied against identical inputs so the comparison
means something.

    uv run python -m eval.experiment                 # full matrix
    uv run python -m eval.experiment --limit 5       # cheap smoke run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from eval.harness import load_cases, run_config
from eval.metrics import RunReport, render_comparison
from ledger_agent.agent import AgentConfig
from ledger_agent.env import load_dotenv

RESULTS = Path(__file__).parent.parent / "results"

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-5-20250929"

# Only one variable moves between the first two rows (the validator) and only one
# between the second and third (the model). A matrix that changed both at once could
# not attribute a difference to either.
MATRIX: tuple[AgentConfig, ...] = (
    AgentConfig(
        name="haiku, no validator",
        model=HAIKU,
        tool_names=["search_accounts", "post_journal_entry"],
    ),
    AgentConfig(name="haiku, with validator", model=HAIKU, tool_names=None),
    AgentConfig(name="sonnet, no validator",
                model=SONNET,
                tool_names=["search_accounts", "post_journal_entry"]),
    AgentConfig(name="sonnet, with validator", model=SONNET, tool_names=None),
)


def render_report(reports: list[RunReport], case_count: int) -> str:
    """Assemble the committed markdown report."""
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        "# Evaluation results",
        "",
        f"_{case_count} labeled synthetic invoices · generated {stamp} · temperature 0_",
        "",
        "## Comparison",
        "",
        render_comparison(reports),
        "",
        "**Reading this table.** `posted` is the share of invoices that produced an entry "
        "the ledger accepted. `1st-try post` is the share that got there without a "
        "rejected attempt first — the number that actually varies, since a posted entry "
        "balances by construction. `exact match` is the share whose entry used exactly "
        "the expected set of accounts, the strict measure: one spurious line fails the "
        "case. `macro F1` averages per-account F1 across accounts that appear in the "
        "labels, so a rare account counts as much as a common one.",
        "",
        "## Per-configuration detail",
        "",
    ]
    for report in reports:
        parts.extend([report.render(), ""])
    return "\n".join(parts)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N cases.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS / "latest.md",
        help="Where to write the markdown report.",
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    cases = load_cases(args.limit)
    reports = []
    for config in MATRIX:
        print(f"\n=== {config.name} ({config.model}) ===", file=sys.stderr)
        reports.append(run_config(config, cases, concurrency=args.concurrency))

    report = render_report(reports, len(cases))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")

    # The raw per-case outcomes go next to the markdown so the numbers can be
    # re-analysed — or disputed — without paying for another run.
    raw = args.out.with_suffix(".json")
    raw.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now(dt.UTC).isoformat(),
                "runs": [
                    {
                        "config": r.config_name,
                        "model": r.model,
                        "outcomes": [
                            {
                                "case_id": o.case_id,
                                "expected_accounts": sorted(o.expected_accounts),
                                "actual_accounts": sorted(o.actual_accounts),
                                "posted": o.posted,
                                "exact_match": o.exact_match,
                                "iterations": o.iterations,
                                "validation_calls": o.validation_calls,
                                "post_attempts": o.post_attempts,
                                "input_tokens": o.input_tokens,
                                "output_tokens": o.output_tokens,
                                "error": o.error,
                            }
                            for o in r.outcomes
                        ],
                    }
                    for r in reports
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(render_comparison(reports))
    print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
