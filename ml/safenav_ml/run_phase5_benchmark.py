#!/usr/bin/env python3
"""Phase 5 benchmark runner (PLAN.md section 8, DoD). Host only, against a running
llama-server (``backend=http``) by default, since that is what fits the full 500 in under an
hour (D28). Writes one JSONL run record per row (section 12.9 plus the phase 5 D29 fields) and
prints the metrics table.

    python3 ml/safenav_ml/run_phase5_benchmark.py --rows full --backend-url http://127.0.0.1:8099 \
        --out data/runs/phase5_full500.jsonl
    python3 ml/safenav_ml/run_phase5_benchmark.py --rows hard --out data/runs/phase5_hard_subset.jsonl
    python3 ml/safenav_ml/run_phase5_benchmark.py --rows adversarial --out data/runs/phase5_adversarial50.jsonl
    python3 ml/safenav_ml/run_phase5_benchmark.py --rows heldout100 --out data/runs/phase5_heldout100.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from safenav_ml import metrics  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import ResolverCore  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH_DEFAULT = os.path.join(REPO_ROOT, "models", "phi3-mini-4k-instruct.Q4_K_M.gguf")
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
BENCHMARK_500 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")
ADVERSARIAL_50 = os.path.join(REPO_ROOT, "data", "benchmark", "adversarial_50.jsonl")

# Production configuration, config/planner_params.yaml.
PRODUCTION = dict(fewshot_count=0, temperature=0.3, grammar_on=True)


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def select_rows(which: str) -> List[dict]:
    all_500 = load_jsonl(BENCHMARK_500)
    if which == "full":
        return all_500
    if which == "hard":
        return [r for r in all_500 if r["category"] in ("spatial", "multi_hop")]
    if which == "adversarial":
        return load_jsonl(ADVERSARIAL_50)
    if which == "heldout100":
        # Deterministic: every 5th row by position in the file (500 / 5 = 100), untouched by
        # any tuning decision in this phase (section 8.4). Not excluded from "full": the full
        # 500 headline and this slice are both reported, per the DoD.
        return all_500[4::5]
    raise ValueError(f"unknown --rows value: {which!r}")


def run(core: ResolverCore, rows: List[dict], backend_name: str, grammar_on: bool) -> List[dict]:
    records = []
    n = len(rows)
    for i, row in enumerate(rows):
        t0 = time.monotonic()
        result = core.resolve(row["command"], grammar_on=grammar_on)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        record = {
            "run_id": f"phase5_{backend_name}_{row['id']}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": row["command"],
            "intended_room": row["expected"],
            "category": row["category"],
            "resolved_room": result.room,
            "predicted": result.room,
            "expected": row["expected"],
            "raw_confidence": result.raw_confidence,
            "calibrated_confidence": result.calibrated_confidence,
            "token_entropy": result.token_entropy,
            "resolver_mode": result.mode,
            "mode": result.mode,
            "grammar_on": grammar_on,
            "out_of_graph": result.out_of_graph,
            "malformed": result.room is None,
            "top_k_rooms": [name for name, _ in result.room_ranking],
            "resolver_ms": result.latency_ms,
            "latency_ms": elapsed_ms,
            "cold": i == 0,
            "anchor_room": result.anchor_room,
            "relation": result.relation,
            "n_relation_targets": result.n_relation_targets,
            "backend": backend_name,
        }
        records.append(record)
        if (i + 1) % 25 == 0 or (i + 1) == n:
            print(f"  {i + 1}/{n} done", file=sys.stderr)
    return records


def print_report(rows: List[dict]) -> None:
    print(f"n={len(rows)}")
    print(f"top1={metrics.top1(rows)}")
    print(f"top3={metrics.top3(rows)}")
    print(f"oog_rate={metrics.oog_rate(rows)}")
    by_category: Dict[str, List[dict]] = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)
    for cat, cat_rows in sorted(by_category.items()):
        print(f"  {cat}: n={len(cat_rows)} top1={metrics.top1(cat_rows)}")
    lat = metrics.latency_percentiles(rows, exclude_cold=True)
    print(f"latency p50={lat['p50_ms']} p90={lat['p90_ms']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", choices=["full", "hard", "adversarial", "heldout100"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--backend", choices=["inprocess", "http"], default="http")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8099")
    parser.add_argument("--model-path", default=MODEL_PATH_DEFAULT)
    parser.add_argument("--n-gpu-layers", type=int, default=-1)
    parser.add_argument("--grammar-off", action="store_true")
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
    )

    rows = select_rows(args.rows)
    grammar_on = not args.grammar_off
    records = run(core, rows, args.backend, grammar_on)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    print_report(records)


if __name__ == "__main__":
    main()
