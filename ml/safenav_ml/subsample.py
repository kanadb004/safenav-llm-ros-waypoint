"""Deterministic stratified subsample of the 500-pair benchmark for Stage A screening
(docs/phase-4-brief.md section 4, deviation D19).

    python ml/safenav_ml/subsample.py --n-per-category 8 --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_INPUT = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "data", "benchmark", "subsample_64.jsonl")


def build_subsample(rows: List[dict], n_per_category: int, seed: int) -> List[dict]:
    rng = random.Random(seed)
    by_category = defaultdict(list)
    for r in rows:
        by_category[r["category"]].append(r)
    out: List[dict] = []
    for cat in sorted(by_category):
        pool = sorted(by_category[cat], key=lambda r: r["id"])
        out.extend(rng.sample(pool, min(n_per_category, len(pool))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--out", default=DEFAULT_OUTPUT)
    ap.add_argument("--n-per-category", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    subsample = build_subsample(rows, args.n_per_category, args.seed)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in subsample:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(subsample)} rows to {args.out}")


if __name__ == "__main__":
    main()
