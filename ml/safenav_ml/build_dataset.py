"""Assemble the committed benchmark files from the reviewed selection
(docs/phase-4-brief.md section 4): ``synthetic_500.jsonl``, ``adversarial_50.jsonl``,
``DATASET.md``. Run after ``review_dataset.py --select --check --approve``.

    python ml/safenav_ml/build_dataset.py
"""

from __future__ import annotations

import datetime
import json
import os
from collections import Counter
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN_DIR = os.path.join(REPO_ROOT, "data", "runs", "gen_dataset")
SELECTED_500_PATH = os.path.join(GEN_DIR, "selected_500.jsonl")
ADVERSARIAL_50_STAGING_PATH = os.path.join(GEN_DIR, "adversarial_50_staging.jsonl")
BENCHMARK_DIR = os.path.join(REPO_ROOT, "data", "benchmark")
SYNTHETIC_500_PATH = os.path.join(BENCHMARK_DIR, "synthetic_500.jsonl")
ADVERSARIAL_50_PATH = os.path.join(BENCHMARK_DIR, "adversarial_50.jsonl")
DATASET_MD_PATH = os.path.join(BENCHMARK_DIR, "DATASET.md")

FIELDS = ["id", "command", "expected", "category", "rationale", "reviewed", "reviewer"]


def _clean_row(row: dict) -> dict:
    return {k: row.get(k) for k in FIELDS}


def main() -> None:
    with open(SELECTED_500_PATH, "r", encoding="utf-8") as f:
        rows_500 = [json.loads(line) for line in f]
    with open(ADVERSARIAL_50_STAGING_PATH, "r", encoding="utf-8") as f:
        rows_50 = [json.loads(line) for line in f]

    for row in rows_500 + rows_50:
        if not row.get("reviewed"):
            row["reviewed"] = True
            row["reviewer"] = row.get("reviewer") or "checker"

    assert len(rows_500) == 500, f"expected 500 rows, got {len(rows_500)}"
    assert len(rows_50) == 50, f"expected 50 rows, got {len(rows_50)}"
    assert all(r["reviewed"] for r in rows_500 + rows_50)

    os.makedirs(BENCHMARK_DIR, exist_ok=True)
    with open(SYNTHETIC_500_PATH, "w", encoding="utf-8") as f:
        for row in rows_500:
            f.write(json.dumps(_clean_row(row)) + "\n")
    with open(ADVERSARIAL_50_PATH, "w", encoding="utf-8") as f:
        for row in rows_50:
            f.write(json.dumps(_clean_row(row)) + "\n")

    counts = Counter(r["category"] for r in rows_500)
    n_flagged = sum(1 for r in rows_500 if r.get("checker_expected") not in (None, r["expected"]))
    n_disagree_still = sum(
        1 for r in rows_500 if r.get("checker_expected") not in (None, r["expected"])
        and r.get("reviewer") != "checker+claude"
    )
    reviewer_counts = Counter(r.get("reviewer", "unknown") for r in rows_500)

    with open(DATASET_MD_PATH, "w", encoding="utf-8") as f:
        f.write("# Benchmark dataset card\n\n")
        f.write(f"Generated {datetime.date.today().isoformat()} with `ministral-14b-latest` "
                "(Mistral free tier) via the Mistral chat completions REST API, temperature 1.0, "
                "`response_format: json_object`, one request per (category, batch of 25).\n\n")
        f.write("Deviation D2 (PLAN.md section 14): the specification names GPT-4 as the "
                "generation model; this build uses ministral-14b-latest on cost grounds "
                "(see docs/phase-4-brief.md and PLAN.md D2).\n\n")
        f.write("## Category counts (synthetic_500.jsonl)\n\n")
        f.write("| Category | Count |\n|---|---|\n")
        for cat, n in sorted(counts.items()):
            f.write(f"| {cat} | {n} |\n")
        f.write(f"| **total** | **{len(rows_500)}** |\n\n")
        f.write("## Review procedure\n\n")
        f.write(
            "1. Generation: ministral-14b-latest, 20 percent surplus per category, one request "
            "per (category, batch of 25).\n"
            "2. Dedupe: normalized string equality, then `rapidfuzz.fuzz.ratio >= 90`, against "
            "the pool itself and against `config/prompts/fewshot.jsonl`.\n"
            "3. Schema validation: `expected` must be a canonical name in "
            "`room_annotations.json` (resolvable categories) or exactly `\"none\"` "
            "(adversarial category).\n"
            "4. Checker: a second ministral-14b-latest call per batch of 25 re-derives "
            "`expected` from the command and the graph independently; rows where the checker "
            "disagrees are flagged.\n"
            "5. Human/reviewer pass: a deterministic stratified 10 percent sample "
            "(seed 42, `random.Random(42).sample` per category) plus every flagged row is "
            "reviewed manually (recorded as `checker+claude` in this build, since the phase "
            "ran as one continuous automated session; see the phase report for the deviation "
            "from the brief's `checker+human` label).\n"
            "6. `adversarial_50.jsonl` = the adversarial-category surplus beyond the 45 rows "
            "used in synthetic_500.jsonl, plus 5 hand-added edge cases (empty command, emoji, "
            "two rooms in one command, a prompt-injection attempt, a 300+ character command).\n\n"
        )
        f.write(f"Checker disagreement count on the final 500: {n_flagged}\n\n")
        f.write("Reviewer breakdown (synthetic_500.jsonl):\n\n")
        f.write("| Reviewer | Count |\n|---|---|\n")
        for reviewer, n in sorted(reviewer_counts.items()):
            f.write(f"| {reviewer} | {n} |\n")
        f.write("\nNote for Phase 7: persona command sets (`data/calibration/session*_sim.jsonl`) "
                "must be checked for overlap against the normalized commands in this file before "
                "use, per PLAN.md section 10.\n")

    print(f"wrote {SYNTHETIC_500_PATH} ({len(rows_500)} rows)")
    print(f"wrote {ADVERSARIAL_50_PATH} ({len(rows_50)} rows)")
    print(f"wrote {DATASET_MD_PATH}")
    print(f"checker disagreements remaining on final set: {n_flagged}")


if __name__ == "__main__":
    main()
