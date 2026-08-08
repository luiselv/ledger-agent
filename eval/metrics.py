"""Scoring.

Two metric families, because an agent is not a classifier.

*Classification* asks whether the right account was chosen, per account, via the usual
confusion-matrix counts. Accuracy alone would hide the failure that matters: an account
that appears in two of twenty cases can be missed every time while accuracy stays at 90%.

*End-to-end* asks whether the run produced something a ledger would accept at all —
posted, balanced, and reaching the right set of accounts. A model can classify every
line correctly and still fail to emit a valid entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledger_agent.agent import AgentResult


@dataclass
class BinStats:
    """Confusion-matrix counts for one class, and the rates derived from them."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def support(self) -> int:
        """How many cases actually belong to this class."""
        return self.tp + self.fn

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.fn + self.tn
        return (self.tp + self.tn) / total if total else 0.0


@dataclass
class CaseOutcome:
    """The scored result of one invoice."""

    case_id: str
    expected_accounts: set[str]
    actual_accounts: set[str] = field(default_factory=set)
    posted: bool = False
    balanced: bool = False
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    validation_calls: int = 0
    post_attempts: int = 0
    error: str | None = None

    @property
    def exact_match(self) -> bool:
        """Whether the entry reached exactly the expected set of accounts."""
        return self.posted and self.actual_accounts == self.expected_accounts

    @property
    def needed_correction(self) -> bool:
        """Whether a post attempt was rejected before one succeeded.

        This is the honest version of "did the entry balance". Because
        ``post_journal_entry`` refuses an unbalanced entry, every *posted* entry
        balances by construction — that number can only ever be 100% and measures
        nothing. What varies is whether the model got it right the first time.
        """
        return self.post_attempts > 1

    @property
    def missing(self) -> set[str]:
        return self.expected_accounts - self.actual_accounts

    @property
    def spurious(self) -> set[str]:
        return self.actual_accounts - self.expected_accounts


def score_case(case_id: str, expected_accounts: set[str], result: AgentResult) -> CaseOutcome:
    """Turn one agent run into a scored outcome."""
    actual = set(result.entry.account_codes()) if result.entry else set()
    return CaseOutcome(
        case_id=case_id,
        expected_accounts=expected_accounts,
        actual_accounts=actual,
        posted=result.posted,
        balanced=result.entry.is_balanced() if result.entry else False,
        iterations=result.iterations,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        validation_calls=result.validation_calls,
        post_attempts=result.post_attempts,
        error=result.error,
    )


@dataclass
class RunReport:
    """Aggregate scores for one config over the whole dataset."""

    config_name: str
    model: str
    outcomes: list[CaseOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def posted_rate(self) -> float:
        return self._rate(o.posted for o in self.outcomes)

    @property
    def balanced_rate(self) -> float:
        """Share of runs whose entry balances.

        Kept for completeness, but note it is bounded below by ``posted_rate`` and
        equal to it in practice: the terminal tool rejects anything unbalanced. See
        ``first_attempt_rate`` for the number that actually varies.
        """
        return self._rate(o.balanced for o in self.outcomes)

    @property
    def first_attempt_rate(self) -> float:
        """Share of runs that posted successfully without a rejected attempt first."""
        return self._rate(o.posted and not o.needed_correction for o in self.outcomes)

    @property
    def mean_validation_calls(self) -> float:
        return self._mean(o.validation_calls for o in self.outcomes)

    @property
    def exact_match_rate(self) -> float:
        return self._rate(o.exact_match for o in self.outcomes)

    @property
    def mean_iterations(self) -> float:
        return self._mean(o.iterations for o in self.outcomes)

    @property
    def mean_output_tokens(self) -> float:
        return self._mean(o.output_tokens for o in self.outcomes)

    @property
    def total_tokens(self) -> int:
        return sum(o.input_tokens + o.output_tokens for o in self.outcomes)

    @property
    def errored(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    def _rate(self, values: object) -> float:
        flags = list(values)  # type: ignore[call-overload]
        return sum(1 for v in flags if v) / len(flags) if flags else 0.0

    def _mean(self, values: object) -> float:
        nums = list(values)  # type: ignore[call-overload]
        return sum(nums) / len(nums) if nums else 0.0

    def per_account_stats(self) -> dict[str, BinStats]:
        """Confusion-matrix counts per account, treating each case as a set-membership test.

        For account A and case C: predicting A when C expects it is a true positive;
        predicting it when C does not is a false positive; and so on. A case that never
        posted contributes false negatives for everything it should have hit, which is
        the honest reading — the accounts were not classified.
        """
        classes = sorted(
            {code for o in self.outcomes for code in o.expected_accounts | o.actual_accounts}
        )
        stats = {code: BinStats() for code in classes}
        for outcome in self.outcomes:
            for code in classes:
                expected = code in outcome.expected_accounts
                predicted = code in outcome.actual_accounts
                bucket = stats[code]
                if expected and predicted:
                    bucket.tp += 1
                elif predicted:
                    bucket.fp += 1
                elif expected:
                    bucket.fn += 1
                else:
                    bucket.tn += 1
        return stats

    def macro_f1(self) -> float:
        """Unweighted mean F1 across accounts that appear in the labels.

        Macro rather than micro: rare accounts should count as much as common ones,
        since those are the ones a classifier quietly gives up on.
        """
        stats = [s for s in self.per_account_stats().values() if s.support]
        return sum(s.f1 for s in stats) / len(stats) if stats else 0.0

    def render(self) -> str:
        """Render a full report for one config."""
        lines = [
            f"### {self.config_name}  (`{self.model}`)",
            "",
            f"- cases: {self.total}  (errored: {self.errored})",
            f"- posted a valid entry: {self.posted_rate:.0%}",
            f"- posted on the first attempt: {self.first_attempt_rate:.0%}",
            f"- exact account match: {self.exact_match_rate:.0%}",
            f"- macro F1 over accounts: {self.macro_f1():.3f}",
            f"- mean iterations: {self.mean_iterations:.2f}",
            f"- mean validation calls: {self.mean_validation_calls:.2f}",
            f"- total tokens: {self.total_tokens:,}",
            "",
            "| account | precision | recall | F1 | support |",
            "|---|---|---|---|---|",
        ]
        for code, stat in sorted(self.per_account_stats().items()):
            if not stat.support and not stat.fp:
                continue
            lines.append(
                f"| {code} | {stat.precision:.2f} | {stat.recall:.2f} | "
                f"{stat.f1:.2f} | {stat.support} |"
            )

        misses = [o for o in self.outcomes if not o.exact_match]
        if misses:
            lines.extend(["", "<details><summary>Cases that did not match exactly</summary>", ""])
            for outcome in misses:
                detail = outcome.error or (
                    f"missing {sorted(outcome.missing) or '-'}, "
                    f"spurious {sorted(outcome.spurious) or '-'}"
                    if outcome.posted
                    else "never posted a valid entry"
                )
                lines.append(f"- `{outcome.case_id}`: {detail}")
            lines.extend(["", "</details>"])

        return "\n".join(lines)


def render_comparison(reports: list[RunReport]) -> str:
    """Render the cross-config table.

    This is the table that answers the question the experiment was run to answer, so it
    goes first and the per-config detail follows.
    """
    lines = [
        "| config | posted | 1st-try post | exact match | macro F1 | mean iters | tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        lines.append(
            f"| {report.config_name} | {report.posted_rate:.0%} | "
            f"{report.first_attempt_rate:.0%} | {report.exact_match_rate:.0%} | "
            f"{report.macro_f1():.3f} | {report.mean_iterations:.2f} | "
            f"{report.total_tokens:,} |"
        )
    return "\n".join(lines)
