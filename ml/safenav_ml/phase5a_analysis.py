#!/usr/bin/env python3
"""Phase 5A accuracy analysis: joins a run_phase5_benchmark.py full-500 output against
synthetic_500_v2.jsonl by id, scores both label sets, the per-category table, and the
section 5.1 regression check (the 68 rows phase 5 found had a correct anchor overwritten by
a spurious hop).

Usage: python3 ml/safenav_ml/phase5a_analysis.py data/runs/phase5a_full500.jsonl
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from safenav_ml import metrics  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V2_PATH = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")
SPURIOUS_COMMANDS_PATH = "/tmp/phase5_spurious_commands.json"

CATEGORIES = ["direct", "alias", "spatial", "functional", "negation", "abbreviation", "multi_hop", "adversarial"]


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def build_rows(run_path):
    run_rows = {r["id"]: r for r in load_jsonl(run_path)}
    v2_rows = {r["id"]: r for r in load_jsonl(V2_PATH)}

    original_rows = []
    corrected_rows = []
    for rid, run_row in run_rows.items():
        v2_row = v2_rows[rid]
        base = dict(run_row)
        original_rows.append({**base, "expected": v2_row["expected_original"]})
        corrected_rows.append({**base, "expected": v2_row["expected"]})
    return original_rows, corrected_rows


def table(rows, label):
    print(f"\n=== {label} ===")
    print(f"n={len(rows)} top1={metrics.top1(rows):.4f} top3={metrics.top3(rows)} "
          f"oog_rate={metrics.oog_rate(rows)}")
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for cat in CATEGORIES:
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            continue
        print(f"  {cat:<13} n={len(cat_rows):<4} top1={metrics.top1(cat_rows):.4f}")


def regression_check(run_path):
    if not os.path.exists(SPURIOUS_COMMANDS_PATH):
        print("\n(no spurious-command list found, skipping regression check)")
        return
    with open(SPURIOUS_COMMANDS_PATH, "r", encoding="utf-8") as f:
        spurious_commands = set(json.load(f))

    run_rows = load_jsonl(run_path)
    v2_rows = {r["id"]: r for r in load_jsonl(V2_PATH)}

    matched = [r for r in run_rows if r["command"] in spurious_commands]
    now_correct = 0
    for r in matched:
        original_expected = v2_rows[r["id"]]["expected_original"]
        if r["predicted"] == original_expected:
            now_correct += 1

    print(f"\n=== Section 5.1 regression check ===")
    print(f"{len(matched)}/{len(spurious_commands)} spurious-hop rows matched by command text")
    print(f"{now_correct}/{len(matched)} now answered correctly (against original labels)")
    cue_gated_away = sum(1 for r in matched if r["grammar_version"] == "v1")
    print(f"{cue_gated_away}/{len(matched)} took the v1 grammar this time (hop structurally suppressed)")


def main():
    run_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "data", "runs", "phase5a_full500.jsonl")
    original_rows, corrected_rows = build_rows(run_path)
    table(original_rows, "Original labels (synthetic_500.jsonl)")
    table(corrected_rows, "Corrected labels (synthetic_500_v2.jsonl)")
    regression_check(run_path)


if __name__ == "__main__":
    main()
