"""Grid prompt sensitivity study: few shot {0,5,10,20} x temperature {0.0,0.1,0.3} x format
{gbnf, free} (PLAN.md Phase 4, docs/phase-4-brief.md sections 3, 7.3). Host only, Metal.

    python ml/safenav_ml/prompt_study.py --stage a --pairs data/benchmark/subsample_64.jsonl \
        --out data/runs/prompt_study --n-threads 8
    python ml/safenav_ml/prompt_study.py --stage b --conditions fs5_t0.0_gbnf fs10_t0.0_gbnf \
        --pairs data/benchmark/synthetic_500.jsonl --out data/runs/prompt_study
    python ml/safenav_ml/prompt_study.py --summary --out data/runs/prompt_study
    python ml/safenav_ml/prompt_study.py --fast-path-hit-rate --pairs data/benchmark/synthetic_500.jsonl \
        --out data/runs/prompt_study
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from safenav_ml import metrics  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import ResolverCore, fast_path_match, normalize_command  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(REPO_ROOT, "models", "phi3-mini-4k-instruct.Q4_K_M.gguf")
ANNOTATIONS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "maps", "room_annotations.json"
)

FEWSHOT_COUNTS = [0, 5, 10, 20]
TEMPERATURES = [0.0, 0.1, 0.3]
FORMATS = ["gbnf", "free"]
STUDY_MAX_TOKENS = 64

# The specification's grid counts as 18 conditions (docs/phase-4-brief.md section 7.3). We run
# all 24 and report these 18 in the main table (full gbnf grid, the free-format diagnostic at
# the two endpoint few-shot counts), the remaining 6 (free format at fs5/fs20) in an appendix.
SPEC_18 = [
    f"fs{fs}_t{t}_{fmt}"
    for fs in FEWSHOT_COUNTS for t in TEMPERATURES for fmt in FORMATS
    if fmt == "gbnf" or fs in (0, 10)
]


def condition_name(fs: int, t: float, fmt: str) -> str:
    return f"fs{fs}_t{t}_{fmt}"


def all_conditions() -> List[str]:
    return [
        condition_name(fs, t, fmt)
        for fs in FEWSHOT_COUNTS for t in TEMPERATURES for fmt in FORMATS
    ]


def parse_condition(name: str) -> Dict[str, object]:
    fs_part, t_part, fmt = name.split("_")
    return {"fewshot_count": int(fs_part[2:]), "temperature": float(t_part[1:]), "format": fmt}


def _preflight() -> None:
    import llama_cpp

    supports_gpu = llama_cpp.llama_supports_gpu_offload()
    print(f"llama_supports_gpu_offload(): {supports_gpu}")
    if not supports_gpu:
        print("WARNING: Metal GPU offload not available; the study will be far slower than budgeted")
    docker_running = subprocess.run(
        ["docker", "ps", "-q"], capture_output=True, text=True
    ).stdout.strip()
    if docker_running:
        print("WARNING: docker containers are running; stop them to free RAM for Metal "
              "(docker compose -f docker/docker-compose.yml stop)")


def _acquire_lock(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    lock_path = os.path.join(out_dir, ".prompt_study.lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"another prompt_study.py instance holds the lock at {lock_path}")
    return lock_file


def _load_pairs(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_done_ids(out_path: str) -> Dict[str, dict]:
    if not os.path.exists(out_path):
        return {}
    done = {}
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            done[row["id"]] = row
    return done


def run_condition(core: ResolverCore, pairs: List[dict], out_path: str, cold_flag: List[bool]) -> None:
    done = _load_done_ids(out_path)
    if len(done) >= len(pairs):
        print(f"  {os.path.basename(out_path)}: already complete ({len(done)} rows)")
        return
    with open(out_path, "a", encoding="utf-8") as f:
        for pair in pairs:
            if pair["id"] in done:
                continue
            result = core.resolve(
                pair["command"], grammar_on=core._study_grammar_on, fast_path=False,
                max_tokens=STUDY_MAX_TOKENS,
            )
            malformed = (not core._study_grammar_on) and result.room == "none" and not result.raw_text.strip()
            row = {
                "id": pair["id"],
                "command": pair["command"],
                "expected": pair["expected"],
                "category": pair["category"],
                "predicted": result.room,
                "raw_confidence": result.raw_confidence,
                "token_entropy": result.token_entropy,
                "top_k_rooms": [name for name, _ in result.room_ranking],
                "top_k_scores": [score for _, score in result.room_ranking],
                "mode": result.mode,
                "out_of_graph": result.out_of_graph,
                "malformed": malformed,
                "latency_ms": result.latency_ms,
                "cold": cold_flag[0],
                "raw_text": result.raw_text,
            }
            cold_flag[0] = False
            f.write(json.dumps(row) + "\n")
            f.flush()


def run_stage(conditions: List[str], pairs_path: str, out_dir: str) -> None:
    _preflight()
    lock = _acquire_lock(out_dir)
    try:
        graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
        pairs = _load_pairs(pairs_path)
        for i, p in enumerate(pairs):
            p.setdefault("id", f"p{i:04d}")

        core = ResolverCore(
            model_path=MODEL_PATH, graph=graph, n_ctx=2048, n_threads=8, temperature=0.0,
            max_tokens=STUDY_MAX_TOKENS, fewshot_count=0, allow_none=True,
        )
        core._study_grammar_on = True  # noqa: SLF001

        last_fs = None
        for cond_name in conditions:
            cond = parse_condition(cond_name)
            out_path = os.path.join(out_dir, f"{cond_name}.jsonl")
            cold_flag = [False]
            if cond["fewshot_count"] != last_fs:
                core.fewshot_count = cond["fewshot_count"]
                core.set_graph(core.graph)
                last_fs = cond["fewshot_count"]
                cold_flag = [True]
            core.temperature = cond["temperature"]
            core._study_grammar_on = cond["format"] == "gbnf"  # noqa: SLF001

            t0 = time.monotonic()
            run_condition(core, pairs, out_path, cold_flag)
            print(f"  {cond_name}: done in {time.monotonic() - t0:.1f}s")
    finally:
        lock.close()


def run_fast_path_hit_rate(pairs_path: str, out_dir: str) -> None:
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    pairs = _load_pairs(pairs_path)
    rows = []
    for p in pairs:
        hit = fast_path_match(graph, p["command"]) is not None
        rows.append({"id": p.get("id"), "category": p["category"], "hit": hit})
    out_path = os.path.join(out_dir, "fast_path_hit_rate.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    from collections import defaultdict
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r["hit"])
    print(f"overall fast path hit rate: {sum(r['hit'] for r in rows) / len(rows):.3f}")
    for cat, hits in sorted(by_cat.items()):
        print(f"  {cat}: {sum(hits) / len(hits):.3f} ({sum(hits)}/{len(hits)})")


def _condition_rows(out_dir: str, cond_name: str) -> List[dict]:
    path = os.path.join(out_dir, f"{cond_name}.jsonl")
    if not os.path.exists(path):
        return []
    return _load_pairs(path)


def write_summary(out_dir: str) -> None:
    conditions = all_conditions()
    summary_rows = []
    for cond_name in conditions:
        rows = _condition_rows(out_dir, cond_name)
        if not rows:
            continue
        summ = metrics.summarize(rows)
        correct_conf = [r["raw_confidence"] for r in rows if r["predicted"] == r["expected"]]
        incorrect_conf = [r["raw_confidence"] for r in rows if r["predicted"] != r["expected"]]
        correct_ent = [r["token_entropy"] for r in rows if r["predicted"] == r["expected"]]
        incorrect_ent = [r["token_entropy"] for r in rows if r["predicted"] != r["expected"]]
        summ["condition"] = cond_name
        summ["mean_conf_correct"] = sum(correct_conf) / len(correct_conf) if correct_conf else None
        summ["mean_conf_incorrect"] = sum(incorrect_conf) / len(incorrect_conf) if incorrect_conf else None
        summ["mean_entropy_correct"] = sum(correct_ent) / len(correct_ent) if correct_ent else None
        summ["mean_entropy_incorrect"] = sum(incorrect_ent) / len(incorrect_ent) if incorrect_ent else None
        summary_rows.append(summ)

    csv_path = os.path.join(out_dir, "summary.csv")
    cols = [
        "condition", "n", "top1", "top3", "oog_rate", "malformed_rate", "abstain_precision",
        "abstain_recall", "false_accept_rate", "false_abstain_rate", "p50_ms", "p90_ms",
        "mean_conf_correct", "mean_conf_incorrect", "mean_entropy_correct", "mean_entropy_incorrect",
    ]
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for s in summary_rows:
            f.write(",".join(str(s.get(c, "")) for c in cols) + "\n")

    def md_table(rows: List[dict]) -> str:
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for s in rows:
            lines.append("| " + " | ".join(
                f"{s.get(c):.3f}" if isinstance(s.get(c), float) else str(s.get(c, "")) for c in cols
            ) + " |")
        return "\n".join(lines)

    spec_rows = [s for s in summary_rows if s["condition"] in SPEC_18]
    appendix_rows = [s for s in summary_rows if s["condition"] not in SPEC_18]
    md_path = os.path.join(out_dir, "summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Prompt study summary\n\n## Specification's 18 conditions\n\n")
        f.write(md_table(spec_rows) + "\n\n## Appendix: remaining 6 conditions\n\n")
        f.write(md_table(appendix_rows) + "\n")

    print(f"wrote {csv_path} and {md_path} ({len(summary_rows)} conditions)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["a", "b"])
    ap.add_argument("--conditions", nargs="*")
    ap.add_argument("--pairs", default=os.path.join(REPO_ROOT, "data", "benchmark", "subsample_64.jsonl"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "data", "runs", "prompt_study"))
    ap.add_argument("--n-threads", type=int, default=8)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--fast-path-hit-rate", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.fast_path_hit_rate:
        run_fast_path_hit_rate(args.pairs, args.out)
        return
    if args.summary:
        write_summary(args.out)
        return

    if args.stage == "a":
        run_stage(all_conditions(), args.pairs, args.out)
    elif args.stage == "b":
        if not args.conditions:
            raise SystemExit("--stage b requires --conditions")
        run_stage(args.conditions, args.pairs, args.out)
    else:
        raise SystemExit("pass --stage a|b, --summary, or --fast-path-hit-rate")


if __name__ == "__main__":
    main()
