"""Unit tests for ml/safenav_ml/metrics.py: a 12-row toy set covering adversarial rows,
``none`` predictions, unparseable output, and top-3 ties. No API, no model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safenav_ml import metrics  # noqa: E402


def _row(expected, predicted, category="direct", top_k=None, out_of_graph=False,
         malformed=False, mode="llm_grammar", latency_ms=1000.0, cold=False):
    return {
        "expected": expected,
        "predicted": predicted,
        "category": category,
        "top_k_rooms": top_k or ([predicted] if predicted else []),
        "out_of_graph": out_of_graph,
        "malformed": malformed,
        "mode": mode,
        "latency_ms": latency_ms,
        "cold": cold,
    }


TOY_ROWS = [
    # resolvable, correct, exact top-1 and top-3 hit
    _row("kitchen", "kitchen", category="direct", top_k=["kitchen", "office", "lab"]),
    # resolvable, wrong top-1, but expected in top-3 (tie-break order preserved)
    _row("office", "kitchen", category="alias", top_k=["kitchen", "office", "lab"]),
    # resolvable, wrong, not even in top-3
    _row("server_room", "kitchen", category="spatial", top_k=["kitchen", "office", "lab"]),
    # resolvable, falsely abstained (predicted none)
    _row("lab", "none", category="functional", top_k=["none"]),
    # resolvable, unparseable output (predicted None)
    _row("workshop", None, category="negation", top_k=[]),
    # adversarial, correctly abstained
    _row("none", "none", category="adversarial", top_k=["none"]),
    _row("none", "none", category="adversarial", top_k=["none"]),
    # adversarial, falsely accepted (answered with a room -> also out_of_graph in free mode)
    _row("none", "kitchen", category="adversarial", top_k=["kitchen"], out_of_graph=True),
    # resolvable, correct, free mode, malformed flag present but false
    _row("kitchen", "kitchen", category="direct", top_k=["kitchen"], mode="llm_free", malformed=False),
    # resolvable, free mode, malformed output (unparseable, counts as out_of_graph too)
    _row("office", None, category="alias", top_k=[], mode="llm_free", malformed=True, out_of_graph=True),
    # cold call, excluded from latency percentiles by default
    _row("kitchen", "kitchen", category="direct", top_k=["kitchen"], latency_ms=50000.0, cold=True),
    # fast path hit
    _row("kitchen", "kitchen", category="direct", top_k=["kitchen"], mode="fast_path", latency_ms=2.0),
]


def test_top1_counts_adversarial_abstention_as_correct():
    rows = [TOY_ROWS[0], TOY_ROWS[5]]
    assert metrics.top1(rows) == 1.0


def test_top1_mixed():
    # row0 correct, row1 wrong -> 0.5
    assert metrics.top1([TOY_ROWS[0], TOY_ROWS[1]]) == 0.5


def test_top1_empty_is_none():
    assert metrics.top1([]) is None


def test_top3_only_resolvable_rows():
    # row0: hit, row1: hit (office in top3), row2: miss -> 2/3
    resolvable = [TOY_ROWS[0], TOY_ROWS[1], TOY_ROWS[2]]
    assert metrics.top3(resolvable) == 2 / 3


def test_top3_excludes_adversarial():
    rows = [TOY_ROWS[0], TOY_ROWS[5]]
    assert metrics.top3(rows) == 1.0


def test_oog_rate():
    rows = [TOY_ROWS[7], TOY_ROWS[9], TOY_ROWS[0]]
    assert metrics.oog_rate(rows) == 2 / 3


def test_malformed_rate_free_mode_only():
    rows = [TOY_ROWS[8], TOY_ROWS[9]]
    assert metrics.malformed_rate(rows) == 0.5


def test_malformed_rate_none_when_no_free_rows():
    assert metrics.malformed_rate([TOY_ROWS[0]]) is None


def test_abstain_precision_and_recall():
    # abstained rows: row3 (resolvable, false abstain), row5, row6 (adversarial, correct)
    rows = [TOY_ROWS[3], TOY_ROWS[5], TOY_ROWS[6]]
    assert metrics.abstain_precision(rows) == 2 / 3
    # adversarial rows: row5, row6 both abstained -> recall 1.0
    assert metrics.abstain_recall(rows) == 1.0


def test_false_accept_and_false_abstain_rate():
    adversarial = [TOY_ROWS[5], TOY_ROWS[6], TOY_ROWS[7]]
    assert metrics.false_accept_rate(adversarial) == 1 / 3
    resolvable = [TOY_ROWS[0], TOY_ROWS[3]]
    assert metrics.false_abstain_rate(resolvable) == 0.5


def test_latency_percentiles_excludes_cold():
    rows = [TOY_ROWS[0], TOY_ROWS[10]]
    result = metrics.latency_percentiles(rows)
    assert result["p50_ms"] == 1000.0
    assert result["p90_ms"] == 1000.0


def test_latency_percentiles_includes_cold_when_asked():
    rows = [TOY_ROWS[0], TOY_ROWS[10]]
    result = metrics.latency_percentiles(rows, exclude_cold=False)
    assert result["p90_ms"] == 45100.0


def test_fast_path_hit_rate():
    rows = [TOY_ROWS[0], TOY_ROWS[11]]
    assert metrics.fast_path_hit_rate(rows) == 0.5


def test_per_category_top1():
    result = metrics.per_category_top1(TOY_ROWS)
    assert result["direct"] == 1.0
    assert result["adversarial"] == 2 / 3


def test_summarize_has_all_keys():
    out = metrics.summarize(TOY_ROWS)
    for key in (
        "n", "top1", "top3", "oog_rate", "malformed_rate", "abstain_precision",
        "abstain_recall", "false_accept_rate", "false_abstain_rate", "p50_ms", "p90_ms",
        "fast_path_hit_rate", "per_category_top1",
    ):
        assert key in out
    assert out["n"] == 12


# Phase 7 calibration metrics (PLAN.md section 10).

def test_ece_perfect_calibration_is_zero():
    probs = [0.0, 0.0, 1.0, 1.0]
    labels = [0, 0, 1, 1]
    assert metrics.ece(probs, labels, n_bins=10) == 0.0


def test_ece_penalizes_overconfidence():
    # All predicted at 0.95 but only half correct: one bin, |0.95 - 0.5| = 0.45.
    probs = [0.95, 0.95, 0.95, 0.95]
    labels = [1, 0, 1, 0]
    assert abs(metrics.ece(probs, labels, n_bins=10) - 0.45) < 1e-9


def test_brier_score_known_value():
    probs = [1.0, 0.0]
    labels = [1, 1]
    # (1-1)^2 + (0-1)^2 = 1, divided by 2
    assert metrics.brier_score(probs, labels) == 0.5


def test_false_pass_rate_only_counts_passed_predictions():
    probs = [0.9, 0.9, 0.4]
    labels = [1, 0, 1]  # third row is below threshold, excluded
    assert metrics.false_pass_rate(probs, labels, threshold=0.5) == 0.5


def test_false_rejection_rate_only_counts_correct_predictions():
    probs = [0.9, 0.4, 0.4]
    labels = [1, 1, 0]  # third row is incorrect, excluded
    assert metrics.false_rejection_rate(probs, labels, threshold=0.5) == 0.5


def test_reliability_bins_counts_and_empty_bins():
    probs = [0.05, 0.95]
    labels = [0, 1]
    bins = metrics.reliability_bins(probs, labels, n_bins=10)
    assert len(bins) == 10
    assert bins[0]["n"] == 1 and bins[0]["accuracy"] == 0.0
    assert bins[9]["n"] == 1 and bins[9]["accuracy"] == 1.0
    assert bins[5]["n"] == 0 and bins[5]["accuracy"] is None
