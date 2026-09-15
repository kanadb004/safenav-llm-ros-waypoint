#!/usr/bin/env python3
"""Host Metal latency proxy for the resolver (PLAN.md section 13 and Phase 3 DoD).

Runs N consecutive resolutions of a fixed command through ``ResolverCore`` with a real GGUF
model and reports p50/p90 latency. Also reports the token-prefix overlap between the first and
second call's full prompts as evidence that only the command (plus the fixed
"<|end|>\\n<|assistant|>\\n" suffix) needs to be evaluated fresh on repeat calls; llama-cpp-python
reuses the KV cache for the matching prefix internally (see ``Llama.generate``'s longest-common-
prefix check), so this token-count overlap is what drives the wall-clock speed-up printed below.

Usage: python ml/safenav_ml/latency_probe.py [models/phi3-mini-4k-instruct.Q4_K_M.gguf]
"""

import argparse
import os
import statistics
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner"))

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import ResolverCore  # noqa: E402

DEFAULT_MODEL = os.path.join(REPO_ROOT, "models", "phi3-mini-4k-instruct.Q4_K_M.gguf")
ANNOTATIONS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "maps", "room_annotations.json"
)
FIXED_COMMAND = "somewhere I can charge the robot"


def common_prefix_len(a, b) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model_path", nargs="?", default=DEFAULT_MODEL)
    parser.add_argument("--n-calls", type=int, default=20)
    parser.add_argument("--n-threads", type=int, default=8)
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    core = ResolverCore(model_path=args.model_path, graph=graph, n_threads=args.n_threads, temperature=0.0)

    prompt_1 = core.prompt_builder.build_prompt(FIXED_COMMAND)
    prompt_2 = core.prompt_builder.build_prompt(FIXED_COMMAND + " please")
    tokens_1 = core._llm.tokenize(prompt_1.encode("utf-8"), add_bos=True)
    tokens_2 = core._llm.tokenize(prompt_2.encode("utf-8"), add_bos=True)
    prefix_len = common_prefix_len(tokens_1, tokens_2)
    print(
        f"prompt token count: {len(tokens_1)}, shared prefix with a second command: "
        f"{prefix_len} tokens ({len(tokens_1) - prefix_len} tokens differ, i.e. the command "
        f"and everything after it)"
    )

    latencies = []
    for i in range(args.n_calls):
        result = core.resolve(FIXED_COMMAND, grammar_on=True)
        latencies.append(result.latency_ms)
        print(f"call {i + 1:2d}: {result.latency_ms:8.1f} ms  mode={result.mode} room={result.room}")

    p50 = statistics.median(latencies)
    p90 = statistics.quantiles(latencies, n=10)[8]
    print(f"\np50 = {p50:.1f} ms, p90 = {p90:.1f} ms over {args.n_calls} calls")


if __name__ == "__main__":
    main()
