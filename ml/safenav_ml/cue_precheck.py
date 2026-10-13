#!/usr/bin/env python3
"""Phase 5A section 8A.1 go/no-go pre-check, run before any cue-gating code was written.

Measures recall of the frozen cue list (config/relational_cues.json) on spatial+multi_hop,
and its false positive rate on direct/alias/negation/abbreviation. Re-running this script
reproduces the numbers recorded in relational_cues.json's "pre_check" block and in the phase
5a report; it is not meant to be used to retune the list afterwards.
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCHMARK_500 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")
CUES_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "relational_cues.json"
)


def load_rows():
    with open(BENCHMARK_500, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def has_cue(command: str, cues) -> bool:
    lowered = command.lower()
    return any(cue in lowered for cue in cues)


def main():
    with open(CUES_PATH, "r", encoding="utf-8") as f:
        cues = json.load(f)["cues"]

    rows = load_rows()
    hard = [r for r in rows if r["category"] in ("spatial", "multi_hop")]
    easy = [r for r in rows if r["category"] in ("direct", "alias", "negation", "abbreviation")]

    hard_hits = [r for r in hard if has_cue(r["command"], cues)]
    easy_hits = [r for r in easy if has_cue(r["command"], cues)]

    recall = len(hard_hits) / len(hard)
    fp_rate = len(easy_hits) / len(easy)

    print(f"recall (spatial+multi_hop): {len(hard_hits)}/{len(hard)} = {recall:.4f}")
    print(f"false positive rate (direct/alias/negation/abbreviation): "
          f"{len(easy_hits)}/{len(easy)} = {fp_rate:.4f}")
    print(f"verdict: {'PASS' if recall >= 0.85 else 'FAIL'} (gate 0.85)")

    print("\nmisses (hard rows with no cue):")
    for r in hard:
        if r not in hard_hits:
            print(f"  {r['category']} | {r['command']}")

    print("\nfalse positives (easy rows with a cue):")
    for r in easy_hits:
        print(f"  {r['category']} | {r['command']}")


if __name__ == "__main__":
    main()
