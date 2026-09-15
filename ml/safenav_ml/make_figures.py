"""Renders figures F1-F7 (docs/phase-4-brief.md section 8) into docs/results/phase4/ as PNG,
150 dpi, matplotlib only (no seaborn). Reads Stage A/B JSONL, baselines, and the fast-path
hit-rate pass; skips a figure and prints a warning if its inputs are missing rather than
failing the whole run.

    python ml/safenav_ml/make_figures.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from safenav_ml import metrics  # noqa: E402
from safenav_ml.prompt_study import FEWSHOT_COUNTS, TEMPERATURES, condition_name  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STUDY_DIR = os.path.join(REPO_ROOT, "data", "runs", "prompt_study")
BASELINES_DIR = os.path.join(REPO_ROOT, "data", "runs", "baselines")
OUT_DIR = os.path.join(REPO_ROOT, "docs", "results", "phase4")

CAPTION_HW = "Apple M2, Metal"


def _load_jsonl(path: str) -> Optional[List[dict]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _savefig(fig, name: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def figure_f1() -> None:
    """Two heatmaps (gbnf, free): top-1 on the 64-pair subsample, rows fewshot, columns temp."""
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, fmt in zip(axes, ["gbnf", "free"]):
        grid = []
        for fs in FEWSHOT_COUNTS:
            row = []
            for t in TEMPERATURES:
                rows = _load_jsonl(os.path.join(STUDY_DIR, f"{condition_name(fs, t, fmt)}.jsonl"))
                row.append(metrics.top1(rows) if rows else float("nan"))
            grid.append(row)
        im = ax.imshow(grid, vmin=0, vmax=1, cmap="viridis")
        ax.set_xticks(range(len(TEMPERATURES)), [str(t) for t in TEMPERATURES])
        ax.set_yticks(range(len(FEWSHOT_COUNTS)), [str(fs) for fs in FEWSHOT_COUNTS])
        ax.set_xlabel("temperature")
        ax.set_ylabel("few shot count")
        ax.set_title(fmt)
        for i in range(len(FEWSHOT_COUNTS)):
            for j in range(len(TEMPERATURES)):
                v = grid[i][j]
                if v == v:  # not nan
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center", color="white", fontsize=8)
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle(f"F1: top-1 by fewshot x temperature (N=64 subsample, {CAPTION_HW})")
    _savefig(fig, "f1_heatmap_top1.png")


def figure_f2(winner_rows: List[dict]) -> None:
    """Grouped bars: top-1 per category, winner (full 500) vs B0, B1, B2, B3, B4."""
    series = {"ours": winner_rows}
    for tag in ["b0", "b1", "b2", "b3", "b4"]:
        rows = _load_jsonl(os.path.join(BASELINES_DIR, f"{tag}.jsonl"))
        if rows:
            series[tag] = rows
    if len(series) < 2:
        print("F2: skipped, not enough baseline rows")
        return

    categories = sorted({r["category"] for r in winner_rows})
    fig, ax = plt.subplots(figsize=(11, 5))
    width = 0.8 / len(series)
    x = range(len(categories))
    for i, (name, rows) in enumerate(series.items()):
        per_cat = metrics.per_category_top1(rows)
        values = [per_cat.get(c) or 0.0 for c in categories]
        ax.bar([xi + i * width for xi in x], values, width=width, label=name)
    ax.set_xticks([xi + width * (len(series) - 1) / 2 for xi in x], categories, rotation=30, ha="right")
    ax.set_ylabel("top-1 accuracy")
    ax.set_title(f"F2: top-1 per category, ours vs baselines (N=500, {CAPTION_HW})")
    ax.legend()
    _savefig(fig, "f2_category_bars.png")


def figure_f3(winner_rows: List[dict], free_twin_rows: Optional[List[dict]]) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    labels, oog, malformed = [], [], []
    labels.append("grammar on"); oog.append(metrics.oog_rate(winner_rows) or 0.0); malformed.append(0.0)
    if free_twin_rows:
        labels.append("grammar off")
        oog.append(metrics.oog_rate(free_twin_rows) or 0.0)
        malformed.append(metrics.malformed_rate(free_twin_rows) or 0.0)
    b4_rows = _load_jsonl(os.path.join(BASELINES_DIR, "b4.jsonl"))
    if b4_rows:
        labels.append("B4 cloud")
        oog.append(metrics.oog_rate(b4_rows) or 0.0)
        malformed.append(metrics.malformed_rate(b4_rows) or 0.0)

    x = range(len(labels))
    ax.bar([xi - 0.2 for xi in x], oog, width=0.4, label="out-of-graph rate")
    ax.bar([xi + 0.2 for xi in x], malformed, width=0.4, label="malformed rate")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("rate")
    ax.set_title(f"F3: OOG / malformed, grammar on vs off (N=500, {CAPTION_HW})\n"
                 "grammar-on is 0 by construction")
    ax.legend()
    _savefig(fig, "f3_oog_malformed.png")


def figure_f4() -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    data, labels = [], []
    for fs in FEWSHOT_COUNTS:
        for t in TEMPERATURES:
            for fmt in ["gbnf", "free"]:
                rows = _load_jsonl(os.path.join(STUDY_DIR, f"{condition_name(fs, t, fmt)}.jsonl"))
                if not rows:
                    continue
                warm = [r["latency_ms"] for r in rows if not r.get("cold")]
                if warm:
                    data.append(warm)
                    labels.append(condition_name(fs, t, fmt))
    if not data:
        print("F4: skipped, no Stage A data yet")
        return
    ax.boxplot(data, tick_labels=labels, showfliers=False)
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_ylabel("latency (ms)")
    ax.axhline(5900, color="orange", linestyle="--", label="container CPU warm 5.9s (Phase 3)")
    ax.axhline(970, color="green", linestyle=":", label="Das et al. cloud min 0.97s")
    ax.axhline(12100, color="red", linestyle=":", label="Das et al. cloud max 12.1s")
    ax.axhline(700, color="purple", linestyle="-.", label="Jetson projection 0.7s (not measured)")
    ax.set_title(f"F4: latency per Stage A condition, warm calls (N=64 subsample, {CAPTION_HW})")
    ax.legend(fontsize=7)
    _savefig(fig, "f4_latency_boxplot.png")


def figure_f5(winner_rows: List[dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    correct = [r for r in winner_rows if r["predicted"] == r["expected"]]
    incorrect = [r for r in winner_rows if r["predicted"] != r["expected"]]
    axes[0].hist([r["raw_confidence"] for r in correct], bins=20, alpha=0.6, label="correct")
    axes[0].hist([r["raw_confidence"] for r in incorrect], bins=20, alpha=0.6, label="incorrect")
    axes[0].set_xlabel("raw_confidence"); axes[0].legend()
    axes[1].hist([r["token_entropy"] for r in correct], bins=20, alpha=0.6, label="correct")
    axes[1].hist([r["token_entropy"] for r in incorrect], bins=20, alpha=0.6, label="incorrect")
    axes[1].set_xlabel("token_entropy (heuristic, D12)"); axes[1].legend()
    fig.suptitle(f"F5: confidence/entropy, correct vs incorrect, winner (N=500, {CAPTION_HW})\n"
                 "these are the Phase 7 calibration inputs")
    _savefig(fig, "f5_confidence_entropy_hist.png")


def figure_f6() -> None:
    path = os.path.join(STUDY_DIR, "fast_path_hit_rate.jsonl")
    rows = _load_jsonl(path)
    if not rows:
        print("F6: skipped, run --fast-path-hit-rate first")
        return
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r["hit"])
    cats = sorted(by_cat)
    rates = [sum(by_cat[c]) / len(by_cat[c]) for c in cats]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(cats, rates)
    ax.set_xticklabels(cats, rotation=30, ha="right")
    ax.set_ylabel("fast path hit rate")
    ax.set_title(f"F6: fast path hit rate per category (N=500, {CAPTION_HW})")
    _savefig(fig, "f6_fast_path_hit_rate.png")


def figure_f7(winner_rows: List[dict]) -> None:
    adversarial_ids_by_tag = {"ours": winner_rows}
    for tag in ["b1", "b2", "b3", "b4"]:
        rows = _load_jsonl(os.path.join(BASELINES_DIR, f"{tag}.jsonl"))
        if rows:
            adversarial_ids_by_tag[tag] = rows
    fig, ax = plt.subplots(figsize=(8, 5))
    labels, far, fabst = [], [], []
    for name, rows in adversarial_ids_by_tag.items():
        adversarial = [r for r in rows if r["expected"] == "none"]
        resolvable = [r for r in rows if r["expected"] != "none"]
        if not adversarial:
            continue
        labels.append(name)
        far.append(metrics.false_accept_rate(adversarial) or 0.0)
        fabst.append(metrics.false_abstain_rate(resolvable) or 0.0)
    x = range(len(labels))
    ax.bar([xi - 0.2 for xi in x], far, width=0.4, label="false accept (adversarial)")
    ax.bar([xi + 0.2 for xi in x], fabst, width=0.4, label="false abstain (resolvable)")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("rate")
    ax.set_title(f"F7: abstention trade-off, ours vs baselines (N=500, {CAPTION_HW})")
    ax.legend()
    _savefig(fig, "f7_abstention_tradeoff.png")


def main() -> None:
    summary_path = os.path.join(STUDY_DIR, "summary.csv")
    winner_rows: Optional[List[dict]] = None
    free_twin_rows: Optional[List[dict]] = None
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = list(csv.DictReader(f))
        gbnf = [r for r in summary if r["condition"].endswith("_gbnf") and r.get("n") == "500"]
        if gbnf:
            best = max(gbnf, key=lambda r: float(r["top1"]))
            winner_rows = _load_jsonl(os.path.join(STUDY_DIR, f"{best['condition']}.jsonl"))
            free_cond = best["condition"].replace("_gbnf", "_free")
            free_twin_rows = _load_jsonl(os.path.join(STUDY_DIR, f"{free_cond}.jsonl"))

    figure_f1()
    figure_f4()
    figure_f6()
    if winner_rows:
        figure_f2(winner_rows)
        figure_f3(winner_rows, free_twin_rows)
        figure_f5(winner_rows)
        figure_f7(winner_rows)
    else:
        print("F2/F3/F5/F7: skipped, no full-500 gbnf winner found in summary.csv yet")


if __name__ == "__main__":
    main()
