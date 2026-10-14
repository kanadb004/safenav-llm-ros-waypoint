#!/usr/bin/env python3
"""PLAN.md 11A.5: offline Condition B (gate on, threshold 0.85) versus Condition C (gate off,
threshold 0.0), on the two cached run sets where the gate was designed to act: the corrected
500 benchmark (``data/runs/phase5a_full500.jsonl``, joined against
``data/benchmark/synthetic_500_v2.jsonl``, with features reconstructed the way
train_calibrator.py's gated_benchmark_500 does, since that run predates the calibrator) and
session 2 calibration trials (``data/runs/calibration/session2_trials.jsonl``, which already
carries calibrated_confidence from the deployed calibrator). No inference is run; this only
re-gates stored confidences at two thresholds.

Usage:
    python3 ml/safenav_ml/offline_gate_comparison.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import Calibrator, features as compute_features  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
CALIBRATOR_PATH = os.path.join(ROS2_PY_PATH, "config", "calibrator.json")
BENCHMARK_V2 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")
PHASE5A_RUN = os.path.join(REPO_ROOT, "data", "runs", "phase5a_full500.jsonl")
SESSION2_RUN = os.path.join(REPO_ROOT, "data", "runs", "calibration", "session2_trials.jsonl")

THRESHOLDS = {"gate on (0.85)": 0.85, "gate off (0.0)": 0.0}


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class _FakeResult:
    def __init__(self, room, raw_confidence, token_entropy):
        self.room = room
        self.raw_confidence = raw_confidence
        self.token_entropy = token_entropy


def build_500_rows(graph: AnnotationGraph, calibrator: Calibrator) -> List[dict]:
    """Reconstructs calibrated_confidence for the cached full-500 run, reusing
    train_calibrator.py's gated_benchmark_500 pattern (features are deterministic from the
    stored resolver output, so nothing is re-run)."""
    run_rows = {r["id"]: r for r in load_jsonl(PHASE5A_RUN)}
    labeled_rows = load_jsonl(BENCHMARK_V2)

    out = []
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
        out.append({
            "category": labeled["category"],
            "intended_room": labeled["expected"],
            "attempted_room": run_row["resolved_room"] or "none",
            "calibrated_confidence": calibrated,
        })
    return out


def build_session2_rows(calibrator: Calibrator) -> List[dict]:
    """session2_trials.jsonl was collected with calibrator_loaded=False (its
    calibrated_confidence column is raw_confidence passed through the identity fallback), so
    this reconstructs it the same way as the full-500 run: from the feature values it already
    recorded directly (raw_confidence, token_entropy, n_candidates, command_length,
    edit_distance), through the deployed Calibrator. No inference is re-run."""
    rows = load_jsonl(SESSION2_RUN)
    out = []
    for r in rows:
        feat = [r["token_entropy"], r["n_candidates"], r["command_length"], r["edit_distance"]]
        calibrated = calibrator.calibrate(r["raw_confidence"], [r["raw_confidence"], *feat])
        out.append({
            "category": r["category"],
            "intended_room": r["intended_room"],
            "attempted_room": r.get("resolved_room") or "none",
            "calibrated_confidence": calibrated,
        })
    return out


def gate_summary(rows: List[dict], threshold: float) -> Dict:
    n = len(rows)
    acted = [r for r in rows if r["calibrated_confidence"] >= threshold]
    wrong = [r for r in acted if r["attempted_room"] != r["intended_room"]]
    return {
        "n": n,
        "acted_rate": len(acted) / n if n else None,
        "acted_num_den": (len(acted), n),
        "wrong_room_action_rate": len(wrong) / n if n else None,
        "wrong_room_action_num_den": (len(wrong), n),
        "wrong_room_action_rate_of_acted": (len(wrong) / len(acted)) if acted else None,
    }


def per_category(rows: List[dict], threshold: float) -> Dict[str, Dict]:
    categories = sorted({r["category"] for r in rows})
    return {cat: gate_summary([r for r in rows if r["category"] == cat], threshold) for cat in categories}


def render(name: str, rows: List[dict]) -> str:
    lines = [f"### {name}", ""]
    lines.append("| threshold | n | acted rate | wrong-room action rate (of n / of acted) |")
    lines.append("|---|---|---|---|")
    for label, t in THRESHOLDS.items():
        s = gate_summary(rows, t)
        of_acted = "n/a" if s["wrong_room_action_rate_of_acted"] is None else f"{s['wrong_room_action_rate_of_acted']:.3f}"
        lines.append(
            f"| {label} | {s['n']} | {s['acted_rate']:.3f} ({s['acted_num_den'][0]}/{s['acted_num_den'][1]}) | "
            f"{s['wrong_room_action_rate']:.3f} ({s['wrong_room_action_num_den'][0]}/{s['wrong_room_action_num_den'][1]}) / {of_acted} |"
        )
    lines.append("")
    lines.append("Per category (gate on 0.85 vs gate off 0.0), wrong-room action rate:")
    lines.append("")
    categories = sorted({r["category"] for r in rows})
    lines.append("| category | gate on (0.85) | gate off (0.0) |")
    lines.append("|---|---|---|")
    on = per_category(rows, 0.85)
    off = per_category(rows, 0.0)
    for cat in categories:
        on_s, off_s = on[cat], off[cat]
        lines.append(
            f"| {cat} | {on_s['wrong_room_action_rate']:.3f} "
            f"({on_s['wrong_room_action_num_den'][0]}/{on_s['wrong_room_action_num_den'][1]}) | "
            f"{off_s['wrong_room_action_rate']:.3f} "
            f"({off_s['wrong_room_action_num_den'][0]}/{off_s['wrong_room_action_num_den'][1]}) |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    calibrator = Calibrator(CALIBRATOR_PATH)

    rows_500 = build_500_rows(graph, calibrator)
    rows_session2 = build_session2_rows(calibrator)

    out = ["# PLAN.md 11A.5: offline Condition B versus C\n"]
    out.append(render("Corrected 500 benchmark (phase5a_full500.jsonl x synthetic_500_v2.jsonl)", rows_500))
    out.append(render("Session 2 calibration trials (calibration/session2_trials.jsonl)", rows_session2))
    text = "\n".join(out)
    print(text)

    out_path = os.path.join(REPO_ROOT, "docs", "results", "offline_gate_comparison.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
