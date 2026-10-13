"""Phase 7 calibrator trainer (PLAN.md section 10, docs/archive/PLAN-v1.md section 10).

Trains the five-feature Platt scaled logistic regression (section 12.8) on
``data/runs/calibration/session1_trials.jsonl`` (produced by ``run_trials.py``), evaluates it on
session 2, and writes ``config/calibrator.json``. Also computes the gated end-to-end accuracy on
the 500 benchmark by reusing a cached full-500 resolver run (features are reconstructed
deterministically, so the LLM is never re-run for this) joined against the corrected labels in
``synthetic_500_v2.jsonl``.

Usage:
    python ml/safenav_ml/train_calibrator.py \
        --session1 data/runs/calibration/session1_trials.jsonl \
        --session2 data/runs/calibration/session2_trials.jsonl \
        --benchmark-500-run data/runs/phase5a_full500.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

import numpy as np  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from safenav_ml import metrics  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import Calibrator, features as compute_features  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
CALIBRATOR_OUT = os.path.join(ROS2_PY_PATH, "config", "calibrator.json")
BENCHMARK_V2 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")
FIXTURES_OUT = os.path.join(ROS2_PY_PATH, "test", "fixtures", "calibrator_parity_vectors.json")
RESULTS_DIR = os.path.join(REPO_ROOT, "docs", "results")

FEATURE_NAMES = [
    "raw_confidence", "token_entropy", "n_candidates", "command_length", "edit_distance",
]
N_BINS = 10
FALSE_PASS_TARGET = 0.05


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def row_features(row: dict) -> List[float]:
    return [
        float(row["raw_confidence"]),
        float(row["token_entropy"]),
        float(row["n_candidates"]),
        float(row["command_length"]),
        float(row["edit_distance"]),
    ]


def row_label(row: dict) -> int:
    return int(row["resolved_room"] == row["intended_room"])


def fit_scaled_logreg(X: np.ndarray, y: np.ndarray) -> Tuple[StandardScaler, LogisticRegression]:
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    # Both classes are needed for LogisticRegression; session 1 is sized so this holds in
    # practice, but guard the degenerate fold case explicitly rather than let sklearn raise.
    if len(set(y.tolist())) < 2:
        raise RuntimeError("fold has a single class, cannot fit logistic regression")
    clf = LogisticRegression(max_iter=1000)
    clf.fit(Xs, y)
    return scaler, clf


def predict_proba(scaler: StandardScaler, clf: LogisticRegression, X: np.ndarray) -> np.ndarray:
    return clf.predict_proba(scaler.transform(X))[:, 1]


def leave_one_persona_out_cv(rows: List[dict]) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (out_of_fold_probs, labels) aligned to ``rows``."""
    personas = sorted({r["persona"] for r in rows})
    X = np.array([row_features(r) for r in rows])
    y = np.array([row_label(r) for r in rows])
    oof = np.zeros(len(rows))
    for held_out in personas:
        train_idx = [i for i, r in enumerate(rows) if r["persona"] != held_out]
        test_idx = [i for i, r in enumerate(rows) if r["persona"] == held_out]
        scaler, clf = fit_scaled_logreg(X[train_idx], y[train_idx])
        oof[test_idx] = predict_proba(scaler, clf, X[test_idx])
    return oof, y


def pick_threshold(probs: np.ndarray, labels: np.ndarray, target_false_pass: float) -> float:
    for t in [round(0.01 * i, 2) for i in range(0, 100)]:
        if metrics.false_pass_rate(probs.tolist(), labels.tolist(), t) <= target_false_pass:
            return t
    return 0.99


def write_fixtures(scaler: StandardScaler, clf: LogisticRegression, X: np.ndarray) -> None:
    n = min(20, len(X))
    idx = np.linspace(0, len(X) - 1, n).astype(int)
    probs = predict_proba(scaler, clf, X[idx])
    vectors = [
        {"features": X[i].tolist(), "expected_probability": float(p)}
        for i, p in zip(idx, probs)
    ]
    os.makedirs(os.path.dirname(FIXTURES_OUT), exist_ok=True)
    with open(FIXTURES_OUT, "w", encoding="utf-8") as f:
        json.dump(vectors, f, indent=2)


def plot_reliability(probs: np.ndarray, labels: np.ndarray, out_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bins = metrics.reliability_bins(probs.tolist(), labels.tolist(), N_BINS)
    xs = [b["mean_confidence"] for b in bins if b["n"] > 0]
    ys = [b["accuracy"] for b in bins if b["n"] > 0]
    ns = [b["n"] for b in bins if b["n"] > 0]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", label="perfect calibration")
    ax.scatter(xs, ys, s=[20 + 4 * n for n in ns], alpha=0.8, label="session 1 (out-of-fold)")
    ax.set_xlabel("mean predicted confidence")
    ax.set_ylabel("empirical accuracy")
    ax.set_title("Phase 7 reliability diagram (calibrated, session 1 CV)")
    ax.legend()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def gated_benchmark_500(calibrator: Calibrator, graph: AnnotationGraph, run_path: str) -> Dict[str, object]:
    if not os.path.exists(run_path):
        return {"skipped": True, "reason": f"{run_path} not found"}
    run_rows = {r["id"]: r for r in load_jsonl(run_path)}
    labeled_rows = load_jsonl(BENCHMARK_V2)

    out_rows = []
    for labeled in labeled_rows:
        rid = labeled["id"]
        if rid not in run_rows:
            continue
        run_row = run_rows[rid]
        room = None if run_row["resolved_room"] in (None, "none") else run_row["resolved_room"]
        aliases = graph.get_room(room).aliases if room and graph.get_room(room) else []
        command_norm = " ".join(run_row["command"].strip().lower().split())
        feat = compute_features(
            _FakeResult(room=run_row["resolved_room"], raw_confidence=run_row["raw_confidence"],
                        token_entropy=run_row["token_entropy"]),
            command_norm, len(graph.canonical_names), aliases,
        )
        calibrated = calibrator.calibrate(run_row["raw_confidence"], feat)
        gated_predicted = run_row["resolved_room"] if calibrated >= calibrator.threshold else "none"
        out_rows.append({
            "expected": labeled["expected"],
            "predicted": gated_predicted,
            "category": labeled["category"],
        })

    return {
        "skipped": False,
        "n": len(out_rows),
        "gated_top1": metrics.top1(out_rows),
        "per_category": metrics.per_category_top1(out_rows),
    }


class _FakeResult:
    """Just enough of ``ResolveResult`` for ``resolver_core.features()``."""

    def __init__(self, room, raw_confidence, token_entropy):
        self.room = room or "none"
        self.raw_confidence = raw_confidence
        self.token_entropy = token_entropy


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session1", default=os.path.join(REPO_ROOT, "data", "runs", "calibration", "session1_trials.jsonl"))
    ap.add_argument("--session2", default=os.path.join(REPO_ROOT, "data", "runs", "calibration", "session2_trials.jsonl"))
    ap.add_argument("--benchmark-500-run", default=os.path.join(REPO_ROOT, "data", "runs", "phase5a_full500.jsonl"))
    ap.add_argument("--out", default=CALIBRATOR_OUT)
    args = ap.parse_args()

    session1 = load_jsonl(args.session1)
    X1 = np.array([row_features(r) for r in session1])
    y1 = np.array([row_label(r) for r in session1])

    oof_probs, oof_labels = leave_one_persona_out_cv(session1)
    cv_ece = metrics.ece(oof_probs.tolist(), oof_labels.tolist(), N_BINS)
    cv_brier = metrics.brier_score(oof_probs.tolist(), oof_labels.tolist())
    raw_ece_s1 = metrics.ece(X1[:, 0].tolist(), y1.tolist(), N_BINS)

    threshold = pick_threshold(oof_probs, oof_labels, FALSE_PASS_TARGET)
    false_pass_s1 = metrics.false_pass_rate(oof_probs.tolist(), oof_labels.tolist(), threshold)

    # Isotonic variant, comparison only (not deployed): report its CV ECE alongside.
    iso_oof = np.zeros(len(session1))
    personas = sorted({r["persona"] for r in session1})
    for held_out in personas:
        train_idx = [i for i, r in enumerate(session1) if r["persona"] != held_out]
        test_idx = [i for i, r in enumerate(session1) if r["persona"] == held_out]
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(X1[train_idx, 0], y1[train_idx])
        iso_oof[test_idx] = iso.predict(X1[test_idx, 0])
    iso_ece = metrics.ece(iso_oof.tolist(), y1.tolist(), N_BINS)

    # Final model: fit on all of session 1 for deployment.
    final_scaler, final_clf = fit_scaled_logreg(X1, y1)

    config = {
        "version": 1,
        "type": "platt_logistic",
        "trained_on": "session1_sim",
        "date": time.strftime("%Y-%m-%d"),
        "feature_names": FEATURE_NAMES,
        "scaler_mean": final_scaler.mean_.tolist(),
        "scaler_scale": final_scaler.scale_.tolist(),
        "weights": final_clf.coef_[0].tolist(),
        "bias": float(final_clf.intercept_[0]),
        "threshold": threshold,
        "metrics": {
            "cv_ece": cv_ece,
            "brier": cv_brier,
            "false_pass_at_threshold": false_pass_s1,
        },
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"wrote {args.out}")
    print(f"session1 CV: ece={cv_ece:.4f} brier={cv_brier:.4f} raw_ece={raw_ece_s1:.4f} "
          f"isotonic_ece={iso_ece:.4f} threshold={threshold} false_pass@threshold={false_pass_s1:.4f}")

    write_fixtures(final_scaler, final_clf, X1)
    plot_reliability(oof_probs, oof_labels, os.path.join(RESULTS_DIR, "calibration_session1.png"))

    # Evaluate on session 2 with the just-trained calibrator (identity for raw since we
    # recompute calibrated probabilities directly here rather than re-running run_trials.py).
    if os.path.exists(args.session2):
        session2 = load_jsonl(args.session2)
        X2 = np.array([row_features(r) for r in session2])
        y2 = np.array([row_label(r) for r in session2])
        calibrator = Calibrator(args.out)
        calibrated2 = np.array([calibrator.calibrate(r["raw_confidence"], row_features(r)) for r in session2])

        raw_ece_s2 = metrics.ece(X2[:, 0].tolist(), y2.tolist(), N_BINS)
        calibrated_ece_s2 = metrics.ece(calibrated2.tolist(), y2.tolist(), N_BINS)
        false_pass_s2 = metrics.false_pass_rate(calibrated2.tolist(), y2.tolist(), threshold)
        false_rejection_s2 = metrics.false_rejection_rate(calibrated2.tolist(), y2.tolist(), threshold)

        print(f"session2: n={len(session2)} raw_ece={raw_ece_s2:.4f} "
              f"calibrated_ece={calibrated_ece_s2:.4f} false_pass={false_pass_s2:.4f} "
              f"false_rejection={false_rejection_s2:.4f}")

        metrics_table = {
            "session1_cv": {"ece": cv_ece, "brier": cv_brier, "raw_ece": raw_ece_s1, "isotonic_ece": iso_ece},
            "session2_eval": {
                "n": len(session2), "raw_ece": raw_ece_s2, "calibrated_ece": calibrated_ece_s2,
                "false_pass_rate": false_pass_s2, "false_rejection_rate": false_rejection_s2,
            },
            "threshold": threshold,
        }
    else:
        metrics_table = {
            "session1_cv": {"ece": cv_ece, "brier": cv_brier, "raw_ece": raw_ece_s1, "isotonic_ece": iso_ece},
            "session2_eval": None,
            "threshold": threshold,
        }

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    calibrator = Calibrator(args.out)
    gated = gated_benchmark_500(calibrator, graph, args.benchmark_500_run)
    metrics_table["gated_benchmark_500"] = gated
    if gated.get("skipped"):
        print(f"gated 500 benchmark skipped: {gated['reason']}")
    else:
        print(f"gated 500 benchmark: n={gated['n']} top1={gated['gated_top1']:.4f}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "calibration_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics_table, f, indent=2)


if __name__ == "__main__":
    main()
