#!/usr/bin/env python3
"""Backend parity check (PLAN.md section 8, DoD): the same model, grammar, and prompt should
give (almost) the same answer whether reached in-process or over HTTP to llama-server.
Temperature 0 so any residual disagreement is implementation drift, not sampling noise.

    python3 ml/safenav_ml/backend_parity.py --n 100 --backend-url http://127.0.0.1:8099
"""

from __future__ import annotations

import argparse
import json
import os
import sys

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
BENCHMARK_500 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")


def load_rows(n: int):
    rows = []
    with open(BENCHMARK_500, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    # Deterministic, spread across categories rather than the first n rows of one category.
    return rows[::max(1, len(rows) // n)][:n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8099")
    parser.add_argument("--model-path", default=MODEL_PATH_DEFAULT)
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "data", "runs", "phase5_backend_parity.jsonl"))
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    rows = load_rows(args.n)

    inprocess = ResolverCore(
        model_path=args.model_path, graph=graph, fewshot_count=0, temperature=0.0,
        backend="inprocess", n_gpu_layers=-1,
    )
    http = ResolverCore(
        model_path=args.model_path, graph=graph, fewshot_count=0, temperature=0.0,
        backend="http", backend_url=args.backend_url,
    )

    records = []
    disagreements = []
    for i, row in enumerate(rows):
        r_in = inprocess.resolve(row["command"], grammar_on=True)
        r_http = http.resolve(row["command"], grammar_on=True)
        agree = r_in.room == r_http.room and r_in.relation == r_http.relation
        records.append({
            "id": row["id"], "command": row["command"],
            "inprocess_room": r_in.room, "inprocess_relation": r_in.relation,
            "http_room": r_http.room, "http_relation": r_http.relation,
            "agree": agree,
        })
        if not agree:
            disagreements.append(records[-1])
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(rows)}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    agreement = sum(r["agree"] for r in records) / len(records)
    print(f"n={len(records)} agreement={agreement:.4f}")
    for d in disagreements:
        print(f"  DISAGREE {d['id']}: {d['command']!r} inprocess={d['inprocess_room']}/{d['inprocess_relation']} "
              f"http={d['http_room']}/{d['http_relation']}")


if __name__ == "__main__":
    main()
