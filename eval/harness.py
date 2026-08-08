"""Run one configuration over the labeled dataset and score it.

    uv run python -m eval.harness                      # default config, all tools
    uv run python -m eval.harness --no-validate-tool   # withhold the validator
    uv run python -m eval.harness --limit 3            # smoke test on three cases
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import CaseOutcome, RunReport, score_case
from ledger_agent.agent import DEFAULT_MODEL, AgentConfig, run_agent
from ledger_agent.env import load_dotenv

DATASET_DIR = Path(__file__).parent / "dataset"
MANIFEST = DATASET_DIR / "labels.json"


@dataclass(frozen=True)
class Case:
    """One labeled invoice."""

    case_id: str
    text: str
    expected_accounts: set[str]
    notes: str


def load_cases(limit: int | None = None) -> list[Case]:
    """Read the manifest and its invoice files.

    A manifest entry pointing at a missing file is a broken dataset, not a case to
    skip quietly — a harness that silently scores fewer cases than it claims is worse
    than one that fails.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = []
    for raw in manifest["cases"]:
        path = DATASET_DIR / raw["file"]
        if not path.exists():
            raise FileNotFoundError(f"{raw['case_id']}: missing invoice file {path}")
        cases.append(
            Case(
                case_id=raw["case_id"],
                text=path.read_text(encoding="utf-8"),
                expected_accounts=set(raw["expected_accounts"]),
                notes=raw.get("notes", ""),
            )
        )
    return cases[:limit] if limit else cases


def run_config(
    config: AgentConfig,
    cases: list[Case],
    *,
    concurrency: int = 4,
    verbose: bool = True,
) -> RunReport:
    """Run every case under one config and return the scored report."""
    from anthropic import Anthropic

    client = Anthropic()

    def one(case: Case) -> CaseOutcome:
        result = run_agent(case.text, config, client)
        outcome = score_case(case.case_id, case.expected_accounts, result)
        if verbose:
            mark = "ok  " if outcome.exact_match else "MISS"
            detail = outcome.error or (
                f"missing={sorted(outcome.missing) or '-'} "
                f"spurious={sorted(outcome.spurious) or '-'}"
            )
            print(
                f"  [{mark}] {case.case_id:<42} iters={outcome.iterations} "
                f"{'' if outcome.exact_match else detail}",
                file=sys.stderr,
            )
        return outcome

    # Cases are independent, so they run concurrently; the API is the bottleneck.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        outcomes = list(pool.map(one, cases))

    return RunReport(config_name=config.name, model=config.model, outcomes=outcomes)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--name", default=None, help="Label for this run in the report.")
    parser.add_argument(
        "--no-validate-tool",
        action="store_true",
        help="Withhold validate_journal_entry so the model must balance unaided.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    tool_names = (
        ["search_accounts", "post_journal_entry"] if args.no_validate_tool else None
    )
    config = AgentConfig(
        name=args.name or ("no validator" if args.no_validate_tool else "all tools"),
        model=args.model,
        tool_names=tool_names,
        max_iterations=args.max_iterations,
    )

    cases = load_cases(args.limit)
    print(f"running {len(cases)} case(s) — {config.name} / {config.model}", file=sys.stderr)
    report = run_config(config, cases, concurrency=args.concurrency)
    print()
    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
