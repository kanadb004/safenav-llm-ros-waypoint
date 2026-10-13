"""Phase 7 calibration trial runner (PLAN.md section 10, docs/archive/PLAN-v1.md section 10).

Replays a session file (``data/calibration/session{1,2}_sim.jsonl``) through the resolver core
directly, the same host-side, ``backend=http`` pattern ``run_phase5_benchmark.py`` established
in Phase 5 (D28) for fitting a full run into a morning. The gate (``confidence_threshold``) is
not applied here: this script only resolves and records, it never routes through
``SemanticNavigateToPose``, so there is nothing to disable. In loopback sim, navigation outcome
is deterministic given the resolved room (docs/archive/PLAN-v1.md section 10), so the label used
for calibration is simply ``resolved_room == intended_room``; see the phase report for the
deviation from driving this through the full ROS graph.

Usage:
    python ml/safenav_ml/run_trials.py --session 1 --backend-url http://127.0.0.1:8099 \
        --out data/runs/calibration/session1_trials.jsonl
    python ml/safenav_ml/run_trials.py --session 2 --backend-url http://127.0.0.1:8099 \
        --calibrator-path ros2_ws/src/semantic_waypoint_planner/config/calibrator.json \
        --out data/runs/calibration/session2_trials.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import ResolverCore  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH_DEFAULT = os.path.join(REPO_ROOT, "models", "phi3-mini-4k-instruct.Q4_K_M.gguf")
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
SESSION_PATHS = {
    1: os.path.join(REPO_ROOT, "data", "calibration", "session1_sim.jsonl"),
    2: os.path.join(REPO_ROOT, "data", "calibration", "session2_sim.jsonl"),
}

# Production configuration, config/planner_params.yaml (same as Phase 5/5A).
PRODUCTION = dict(fewshot_count=0, temperature=0.3, grammar_on=True)


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run(core: ResolverCore, rows: List[dict], session: int) -> List[dict]:
    records = []
    n = len(rows)
    for i, row in enumerate(rows):
        t0 = time.monotonic()
        result = core.resolve(row["command"], grammar_on=PRODUCTION["grammar_on"])
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        features = core.features(result, row["command"], len(core.graph.canonical_names))
        record = {
            "run_id": f"session{session}_{i}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "suite": f"calibration_session{session}",
            "sim_mode": "resolver_only",
            "command": row["command"],
            "intended_room": row["intended_room"],
            "category": row["category"],
            "persona": row.get("persona"),
            "resolved_room": result.room,
            "raw_confidence": result.raw_confidence,
            "calibrated_confidence": result.calibrated_confidence,
            "token_entropy": features[1],
            "n_candidates": features[2],
            "command_length": features[3],
            "edit_distance": features[4],
            "resolver_mode": result.mode,
            "grammar_on": PRODUCTION["grammar_on"],
            "anchor_room": result.anchor_room,
            "relation": result.relation,
            "n_relation_targets": result.n_relation_targets,
            "grammar_version": result.grammar_version,
            "out_of_graph": result.out_of_graph,
            "calibrator_loaded": result.calibrator_loaded,
            "resolver_ms": result.latency_ms,
            "e2e_ms": elapsed_ms,
            "reached_intended": result.room == row["intended_room"],
        }
        records.append(record)
        if (i + 1) % 25 == 0 or (i + 1) == n:
            print(f"  {i + 1}/{n} done", file=sys.stderr)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, choices=[1, 2], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--backend", choices=["inprocess", "http"], default="http")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8099")
    parser.add_argument("--model-path", default=MODEL_PATH_DEFAULT)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--calibrator-path", default=None)
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    core = ResolverCore(
        model_path=args.model_path,
        graph=graph,
        fewshot_count=PRODUCTION["fewshot_count"],
        temperature=PRODUCTION["temperature"],
        backend=args.backend,
        backend_url=args.backend_url,
        n_gpu_layers=args.n_gpu_layers,
        calibrator_path=args.calibrator_path,
    )

    rows = load_jsonl(SESSION_PATHS[args.session])
    records = run(core, rows, args.session)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    n_correct = sum(1 for r in records if r["reached_intended"])
    print(f"n={len(records)} resolved==intended={n_correct} ({n_correct / len(records):.3f})")


if __name__ == "__main__":
    main()
