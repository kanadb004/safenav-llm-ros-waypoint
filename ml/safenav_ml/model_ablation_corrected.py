#!/usr/bin/env python3
"""PLAN.md 11A.7: adds a corrected-label (synthetic_500_v2.jsonl) top-1 column to the Phase 8
model ablation, computed from the already cached data/runs/model_ablation/*.jsonl (no
inference re-run), and states the top-3 denominator (resolvable rows, adversarial excluded).

Usage:
    python3 ml/safenav_ml/model_ablation_corrected.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from safenav_ml import metrics  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_DIR = os.path.join(REPO_ROOT, "data", "runs", "model_ablation")
BENCHMARK_V2 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")

MODELS = ["phi3-mini-4k-instruct.Q4_K_M", "tinyllama-1.1b-chat-v1.0.Q4_K_M", "phi3.5-mini-instruct.Q4_K_M"]


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> int:
    corrected_labels = {r["id"]: r["expected"] for r in load_jsonl(BENCHMARK_V2)}

    print(f"{'model':<30} {'top-1 (original)':<20} {'top-1 (corrected)':<20} "
          f"{'top-3':<10} {'top-3 n':<10}")
    for model in MODELS:
        path = os.path.join(RUN_DIR, f"{model}.jsonl")
        rows = load_jsonl(path)

        original_rows = [{"expected": r["expected"], "predicted": r["predicted"]} for r in rows]
        corrected_rows = [
            {"expected": corrected_labels.get(r["id"], r["expected"]), "predicted": r["predicted"]}
            for r in rows
        ]
        top1_original = metrics.top1(original_rows)
        top1_corrected = metrics.top1(corrected_rows)
        top3_rows = [{"expected": r["expected"], "top_k_rooms": r.get("top_k_rooms")} for r in rows]
        top3 = metrics.top3(top3_rows)
        top3_n = sum(1 for r in top3_rows if r["expected"] != "none")

        print(f"{model:<30} {top1_original:<20.3f} {top1_corrected:<20.3f} {top3:<10.3f} {top3_n:<10}")

    print("\ntop-3 denominator: 455 (resolvable rows under the original synthetic_500.jsonl "
          "labels the ablation's own top_k_rooms column was computed against; 45 adversarial "
          "rows excluded, stated per PLAN.md 11A.7/D57 finding 8, which was previously unstated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
