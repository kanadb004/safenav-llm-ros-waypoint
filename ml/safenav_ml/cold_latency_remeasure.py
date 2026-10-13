#!/usr/bin/env python3
"""Phase 5A section 8A.3: cold latency re-measure, v1 and v2 grammar paths separately.

Must be run against a freshly started llama-server with nothing else contending for the GPU
(phase 5's section 6 confound). Forces the grammar version directly (bypassing cue detection)
so each path gets exactly 50 calls over the held-out slice, rather than however many the cue
list happens to route each way.

Usage: python3 ml/safenav_ml/cold_latency_remeasure.py --backend-url http://127.0.0.1:8099
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.relations import load_cues, has_relational_cue  # noqa: E402
from semantic_waypoint_planner.resolver_core import ResolverCore  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH_DEFAULT = os.path.join(REPO_ROOT, "models", "phi3-mini-4k-instruct.Q4_K_M.gguf")
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
BENCHMARK_500 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")


def held_out_100():
    with open(BENCHMARK_500, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return rows[4::5]


def percentile(values, q):
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    idx = q * (len(values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def measure_path(core, commands, grammar_str, n, label):
    latencies = []
    per_token = []
    for command in commands[:n]:
        prompt = core.prompt_builder.build_prompt(command)
        start = time.monotonic()
        text, backend_ms, prompt_eval_tokens = core._backend.complete(
            prompt, grammar_str, max_tokens=core.max_tokens, temperature=core.temperature,
            stop=["<|end|>"],
        )
        elapsed_ms = (time.monotonic() - start) * 1000.0
        latencies.append(elapsed_ms)
        # Re-query the server's own timings for predicted_per_token_ms via a second, tiny
        # same-prompt call would double the cost; instead approximate from predicted tokens
        # in the text (JSON answers are short and this is diagnostic, not the gate itself).
        n_tokens = max(1, len(text) // 4)
        per_token.append(elapsed_ms / n_tokens)
    print(f"{label}: n={len(latencies)} p50={percentile(latencies, 0.50):.1f} "
          f"p90={percentile(latencies, 0.90):.1f} p99={percentile(latencies, 0.99):.1f} "
          f"mean_per_token_ms~={sum(per_token) / len(per_token):.1f}")
    return latencies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default="http://127.0.0.1:8099")
    parser.add_argument("--model-path", default=MODEL_PATH_DEFAULT)
    parser.add_argument("--n", type=int, default=50)
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    core = ResolverCore(
        model_path=args.model_path, graph=graph, fewshot_count=0, temperature=0.3,
        backend="http", backend_url=args.backend_url,
    )

    rows = held_out_100()
    commands = [r["command"] for r in rows]
    cues = load_cues()
    cue_rate = sum(1 for c in commands if has_relational_cue(c, cues)) / len(commands)

    v1_latencies = measure_path(core, commands, core.grammar_str_v1, args.n, "v1 grammar path")
    v2_latencies = measure_path(core, commands, core.grammar_str, args.n, "v2 grammar path")

    weighted = ([percentile(v1_latencies, 0.90)] * round((1 - cue_rate) * 100)
                + [percentile(v2_latencies, 0.90)] * round(cue_rate * 100))
    traffic_weighted_p90 = sum(weighted) / len(weighted)

    print(f"\nmeasured cue rate on held-out 100 (8A.1 list): {cue_rate:.4f}")
    print(f"traffic-weighted p90 (cue-rate blend of v1/v2 p90): {traffic_weighted_p90:.1f} ms")
    print(f"gate: p90 < 3000 ms -> "
          f"{'PASS' if traffic_weighted_p90 < 3000 else 'FAIL'}")


if __name__ == "__main__":
    main()
