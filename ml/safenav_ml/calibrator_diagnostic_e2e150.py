#!/usr/bin/env python3
"""PLAN.md 11A.6: tabulate the section 12.8 features for e2e150 production wrong passes
against correct passes, to state plainly whether the wrong spatial passes are separable on
any feature. No retraining, no re-thresholding, no new features; this only reads already
collected rows and reports summary statistics.

Usage:
    python3 ml/safenav_ml/calibrator_diagnostic_e2e150.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCTION_RESCORED = os.path.join(REPO_ROOT, "data", "runs", "e2e150_loopback_rescored.jsonl")

FEATURES = ["raw_confidence", "edit_distance", "command_length", "token_entropy"]


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _attempted(row: dict) -> str:
    a = row.get("attempted_room") or row.get("resolved_room") or "none"
    return a if a else "none"


def stats(values: List[float]) -> str:
    if not values:
        return "n/a"
    mean = sum(values) / len(values)
    return f"mean={mean:.4f} range=[{min(values):.4f}, {max(values):.4f}] n={len(values)}"


def main() -> int:
    rows = load_jsonl(PRODUCTION_RESCORED)
    gate_passed = [r for r in rows if r.get("gate_passed")]
    wrong = [r for r in gate_passed if _attempted(r) != r.get("intended_room")]
    correct = [r for r in gate_passed if _attempted(r) == r.get("intended_room")]

    print(f"e2e150 production (rescored): {len(gate_passed)} gate-passed of {len(rows)}, "
          f"{len(wrong)} wrong, {len(correct)} correct")
    print(f"n_candidates is constant at 30 on every row (D53); not tabulated here.\n")

    print(f"{'feature':<16} {'wrong passes':<45} {'correct passes'}")
    for feat in FEATURES:
        wrong_vals = [r[feat] for r in wrong if r.get(feat) is not None]
        correct_vals = [r[feat] for r in correct if r.get(feat) is not None]
        print(f"{feat:<16} {stats(wrong_vals):<45} {stats(correct_vals)}")

    wrong_spatial = [r for r in wrong if r.get("category") == "spatial"]
    print(f"\nwrong passes that are spatial: {len(wrong_spatial)}/{len(wrong)}")

    print("\nBy category, wrong passes:")
    for cat in sorted({r["category"] for r in gate_passed}):
        cat_wrong = [r for r in wrong if r["category"] == cat]
        cat_passed = [r for r in gate_passed if r["category"] == cat]
        print(f"  {cat:<14} {len(cat_wrong)}/{len(cat_passed)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
