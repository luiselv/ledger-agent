"""Tests for the scoring layer.

The metrics decide what the experiment concludes, so they get tested as carefully as
the code they measure. A silently wrong recall would turn a null result into a
headline.
"""

from __future__ import annotations

from decimal import Decimal

from eval.metrics import BinStats, CaseOutcome, RunReport, score_case

from ledger_agent.agent import AgentResult
from ledger_agent.schemas import JournalEntry, JournalLine
from tests.test_tools import TODAY


def outcome(
    case_id: str,
    expected: set[str],
    actual: set[str],
    *,
    posted: bool = True,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        expected_accounts=expected,
        actual_accounts=actual,
        posted=posted,
        balanced=posted,
    )


def report(*outcomes: CaseOutcome) -> RunReport:
    return RunReport(config_name="t", model="m", outcomes=list(outcomes))


# --- BinStats ----------------------------------------------------------------------

def test_binstats_rates() -> None:
    stats = BinStats(tp=8, fp=2, fn=4, tn=6)
    assert stats.precision == 0.8
    assert stats.recall == 0.6666666666666666
    assert round(stats.f1, 4) == 0.7273
    assert stats.accuracy == 0.7
    assert stats.support == 12


def test_binstats_are_zero_not_undefined_when_empty() -> None:
    """A class with no predictions must not divide by zero."""
    empty = BinStats()
    assert (empty.precision, empty.recall, empty.f1, empty.accuracy) == (0.0, 0.0, 0.0, 0.0)


def test_perfect_and_null_classifiers() -> None:
    assert BinStats(tp=5, tn=5).f1 == 1.0
    assert BinStats(fp=5, fn=5).f1 == 0.0


# --- per-account confusion matrix --------------------------------------------------

def test_confusion_matrix_counts_set_membership() -> None:
    run = report(
        outcome("a", {"6010", "2010"}, {"6010", "2010"}),  # both TP
        outcome("b", {"6020", "2010"}, {"6010", "2010"}),  # 6020 FN, 6010 FP
    )
    stats = run.per_account_stats()

    assert stats["2010"].tp == 2
    assert stats["6010"].tp == 1 and stats["6010"].fp == 1
    assert stats["6020"].fn == 1 and stats["6020"].tp == 0
    # 6020 was neither expected nor predicted in case "a".
    assert stats["6020"].tn == 1


def test_unposted_case_counts_as_false_negatives() -> None:
    """Failing to produce an entry is not the same as classifying nothing."""
    run = report(outcome("a", {"6010", "2010"}, set(), posted=False))
    stats = run.per_account_stats()
    assert stats["6010"].fn == 1
    assert stats["6010"].tp == 0


def test_macro_f1_ignores_accounts_with_no_support() -> None:
    """A spurious account should not be averaged in as a zero-support class."""
    run = report(
        outcome("a", {"6010"}, {"6010"}),
        outcome("b", {"6010"}, {"6010", "9999"}),
    )
    stats = run.per_account_stats()
    assert stats["9999"].support == 0
    # Only 6010 has support, and it was predicted correctly both times.
    assert run.macro_f1() == 1.0


def test_macro_f1_weights_a_rare_account_equally() -> None:
    """The reason for macro over micro: a missed rare class must show up."""
    common = [outcome(f"c{i}", {"6010"}, {"6010"}) for i in range(9)]
    rare_missed = outcome("rare", {"6020"}, {"6010"})
    run = report(*common, rare_missed)

    assert run.exact_match_rate == 0.9
    # 6020 scores 0, 6010 is dragged down by one false positive, so macro F1 lands
    # well below the 90% headline rate.
    assert run.macro_f1() < 0.6


# --- aggregates --------------------------------------------------------------------

def test_exact_match_requires_the_exact_account_set() -> None:
    assert outcome("a", {"6010", "2010"}, {"6010", "2010"}).exact_match
    assert not outcome("b", {"6010", "2010"}, {"6010", "2010", "2200"}).exact_match
    assert not outcome("c", {"6010", "2010"}, {"6010"}).exact_match
    assert not outcome("d", {"6010"}, {"6010"}, posted=False).exact_match


def test_missing_and_spurious_are_reported_separately() -> None:
    o = outcome("a", {"6010", "2200", "2010"}, {"6010", "2010", "6040"})
    assert o.missing == {"2200"}
    assert o.spurious == {"6040"}


def test_needed_correction_tracks_rejected_post_attempts() -> None:
    clean = outcome("a", {"6010"}, {"6010"})
    clean.post_attempts = 1
    retried = outcome("b", {"6010"}, {"6010"})
    retried.post_attempts = 3

    assert not clean.needed_correction
    assert retried.needed_correction
    assert report(clean, retried).first_attempt_rate == 0.5


def test_first_attempt_rate_excludes_runs_that_never_posted() -> None:
    """Never posting is not the same as posting cleanly on the first try."""
    never = outcome("a", {"6010"}, set(), posted=False)
    never.post_attempts = 0
    assert report(never).first_attempt_rate == 0.0


def test_balanced_rate_cannot_exceed_posted_rate() -> None:
    """The property that makes `balanced` uninformative, asserted rather than assumed."""
    run = report(
        outcome("a", {"6010"}, {"6010"}),
        outcome("b", {"6010"}, set(), posted=False),
    )
    assert run.balanced_rate <= run.posted_rate


def test_rates_on_an_empty_report_do_not_divide_by_zero() -> None:
    empty = report()
    assert empty.posted_rate == 0.0
    assert empty.macro_f1() == 0.0
    assert empty.mean_iterations == 0.0


def test_render_lists_the_misses() -> None:
    rendered = report(
        outcome("good", {"6010"}, {"6010"}),
        outcome("bad", {"6020"}, {"6010"}),
    ).render()
    assert "bad" in rendered
    assert "good" not in rendered.split("did not match exactly")[-1]


# --- scoring an agent run ----------------------------------------------------------

def test_score_case_reads_the_posted_entry() -> None:
    entry = JournalEntry(
        entry_date=TODAY,
        memo="hosting",
        lines=[
            JournalLine(
                account_code="6010",
                description="hosting",
                debit=Decimal("1200.00"),
                credit=Decimal("0"),
            ),
            JournalLine(
                account_code="2010",
                description="payable",
                debit=Decimal("0"),
                credit=Decimal("1200.00"),
            ),
        ],
    )
    result = AgentResult(entry=entry, iterations=2, input_tokens=100, output_tokens=50)
    scored = score_case("c1", {"6010", "2010"}, result)

    assert scored.posted and scored.balanced and scored.exact_match
    assert scored.iterations == 2


def test_score_case_records_an_api_error() -> None:
    result = AgentResult(error="APIError: boom", stop_reason="api_error")
    scored = score_case("c1", {"6010"}, result)
    assert not scored.posted
    assert scored.error == "APIError: boom"
    assert scored.missing == {"6010"}
