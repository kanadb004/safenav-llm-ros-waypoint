"""Phase 8B e2e150 report (PLAN.md section 11A.2): each metric below is its own numerator and
denominator, rather than the Phase 8 "false start" conflation of navigation failure with a
wrong resolution (D57). Computed from run_trials.py's JSONL output (rescored for the
production suite per 11A.1) for one or more e2e150 suites (production, grammar off, gate off).
Writes a markdown table per suite plus a per-category breakdown into docs/results/.

Usage:
    python3 ml/safenav_ml/e2e_report.py \
        --production data/runs/e2e150_loopback_rescored.jsonl \
        --grammar-off data/runs/e2e150_grammar_off_8b.jsonl \
        --gate-off data/runs/e2e150_gate_off_8b.jsonl \
        --out docs/results/e2e150_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from safenav_ml.metrics import _percentile  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CATEGORIES = ("direct", "alias", "negation", "abbreviation", "spatial")


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _percentiles(values: List[float]) -> Dict[str, Optional[float]]:
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"p50": None, "p90": None, "p99": None, "n": 0}
    return {
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "p99": _percentile(values, 0.99),
        "n": len(values),
    }


def _attempted(row: dict) -> str:
    a = row.get("attempted_room") or row.get("resolved_room") or "none"
    return a if a else "none"


def _frac(num: int, den: int) -> Optional[float]:
    return (num / den) if den else None


def summarize(rows: List[dict], label: str) -> Dict:
    n = len(rows)
    gate_passed_rows = [r for r in rows if r.get("gate_passed")]
    n_gate_passed = len(gate_passed_rows)

    # acted rate: gate_passed / n
    acted_rate = _frac(n_gate_passed, n)

    # wrong-room action rate (the specification's "false start"): gate_passed and
    # attempted_room != intended, / n and / acted. Navigation outcome is not part of this.
    wrong_room_rows = [r for r in gate_passed_rows if _attempted(r) != r.get("intended_room")]
    n_wrong_room = len(wrong_room_rows)
    wrong_room_rate_of_n = _frac(n_wrong_room, n)
    wrong_room_rate_of_acted = _frac(n_wrong_room, n_gate_passed)

    # correct abstention: intended "none" and not acted, / rows with intended "none"
    none_rows = [r for r in rows if r.get("intended_room") == "none"]
    n_correct_abstention = sum(1 for r in none_rows if not r.get("gate_passed"))
    correct_abstention_rate = _frac(n_correct_abstention, len(none_rows))

    # resolver correct: attempted_room == intended (with "none" meaning abstention), / n
    n_resolver_correct = sum(1 for r in rows if _attempted(r) == r.get("intended_room"))
    resolver_correct_rate = _frac(n_resolver_correct, n)

    # navigation-invalid rows: final pose outside map bounds, or null
    invalid_rows = [r for r in rows if r.get("nav_invalid")]
    n_invalid = len(invalid_rows)

    # navigation reach, given a correct acted resolution: reached_intended / correct acted
    # rows, excluding navigation-invalid rows. A simulator health figure, not a task metric.
    correct_acted_rows = [
        r for r in gate_passed_rows
        if _attempted(r) == r.get("intended_room") and not r.get("nav_invalid")
    ]
    n_reached = sum(1 for r in correct_acted_rows if r.get("reached_intended"))
    reach_rate = _frac(n_reached, len(correct_acted_rows))

    nav_success = sum(1 for r in rows if r.get("nav_result") == "succeeded")
    out_of_graph = sum(1 for r in rows if r.get("out_of_graph"))

    e2e_ms = [r.get("e2e_ms") for r in rows if r.get("e2e_ms") is not None]
    resolver_ms = [r.get("resolver_ms") for r in rows if r.get("resolver_ms") is not None]
    t_nav_start = []
    n_t_nav_start_null = 0
    for r in rows:
        if r.get("t_nav_start") is not None and r.get("t_command") is not None:
            t_nav_start.append((r["t_nav_start"] - r["t_command"]) * 1000.0)
        else:
            n_t_nav_start_null += 1

    by_category = {}
    for cat in CATEGORIES:
        cat_rows = [r for r in rows if r.get("category") == cat]
        cat_gate_passed = [r for r in cat_rows if r.get("gate_passed")]
        cat_wrong = [r for r in cat_gate_passed if _attempted(r) != r.get("intended_room")]
        by_category[cat] = {
            "n": len(cat_rows),
            "acted_rate": _frac(len(cat_gate_passed), len(cat_rows)),
            "wrong_room_action_rate": _frac(len(cat_wrong), len(cat_rows)),
            "wrong_room_of_acted": _frac(len(cat_wrong), len(cat_gate_passed)),
        }

    return {
        "label": label,
        "n": n,
        "acted_rate": acted_rate,
        "acted_num_den": (n_gate_passed, n),
        "wrong_room_action_rate": wrong_room_rate_of_n,
        "wrong_room_action_num_den": (n_wrong_room, n),
        "wrong_room_action_rate_of_acted": wrong_room_rate_of_acted,
        "correct_abstention_rate": correct_abstention_rate,
        "correct_abstention_num_den": (n_correct_abstention, len(none_rows)),
        "resolver_correct_rate": resolver_correct_rate,
        "resolver_correct_num_den": (n_resolver_correct, n),
        "reach_given_correct_rate": reach_rate,
        "reach_given_correct_num_den": (n_reached, len(correct_acted_rows)),
        "nav_invalid_count": n_invalid,
        "nav_invalid_rate": _frac(n_invalid, n),
        "nav_result_succeeded_rate": _frac(nav_success, n),
        "out_of_graph_count": out_of_graph,
        "out_of_graph_rate": _frac(out_of_graph, n),
        "e2e_ms": _percentiles(e2e_ms),
        "resolver_ms": _percentiles(resolver_ms),
        "time_to_nav_start_ms": _percentiles(t_nav_start),
        "time_to_nav_start_null_count": n_t_nav_start_null,
        "by_category": by_category,
    }


def _fmt_rate(num_den) -> str:
    num, den = num_den
    if den == 0:
        return "n/a (0/0)"
    return f"{num / den:.3f} ({num}/{den})"


def _fmt_lat(p: Dict[str, Optional[float]]) -> str:
    if p["p50"] is None:
        return "n/a"
    return f"{p['p50']:.0f}/{p['p90']:.0f}/{p['p99']:.0f} (n={p['n']})"


def render_markdown(summaries: List[Dict]) -> str:
    lines = ["# Phase 8B: e2e150 suite results (PLAN.md 11A.2 metrics)", ""]
    lines.append(
        "| suite | n | acted rate | wrong-room action rate (of n / of acted) | "
        "correct abstention | resolver correct | reach given correct (valid rows) | "
        "nav_invalid | out of graph | e2e p50/p90/p99 (n) | resolver p50/p90/p99 (n) | "
        "nav start p50/p90 (n, nulls) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        wrong_of_acted = (
            "n/a" if s["wrong_room_action_rate_of_acted"] is None
            else f"{s['wrong_room_action_rate_of_acted']:.3f}"
        )
        nav_start = s["time_to_nav_start_ms"]
        nav_start_str = (
            "n/a" if nav_start["p50"] is None
            else f"{nav_start['p50']:.0f}/{nav_start['p90']:.0f} "
                 f"(n={nav_start['n']}, null={s['time_to_nav_start_null_count']})"
        )
        lines.append(
            f"| {s['label']} | {s['n']} | {_fmt_rate(s['acted_num_den'])} | "
            f"{_fmt_rate(s['wrong_room_action_num_den'])} / {wrong_of_acted} | "
            f"{_fmt_rate(s['correct_abstention_num_den'])} | "
            f"{_fmt_rate(s['resolver_correct_num_den'])} | "
            f"{_fmt_rate(s['reach_given_correct_num_den'])} | "
            f"{s['nav_invalid_count']} ({_fmt_rate((s['nav_invalid_count'], s['n']))}) | "
            f"{s['out_of_graph_count']} ({_fmt_rate((s['out_of_graph_count'], s['n']))}) | "
            f"{_fmt_lat(s['e2e_ms'])} | {_fmt_lat(s['resolver_ms'])} | {nav_start_str} |"
        )

    lines.append("")
    lines.append("## Per-category wrong-room action rate")
    lines.append("")
    lines.append("| suite | " + " | ".join(CATEGORIES) + " |")
    lines.append("|---|" + "---|" * len(CATEGORIES))
    for s in summaries:
        cells = []
        for cat in CATEGORIES:
            c = s["by_category"][cat]
            cells.append(_fmt_rate((
                round(c["wrong_room_action_rate"] * c["n"]) if c["wrong_room_action_rate"] is not None else 0,
                c["n"],
            )))
        lines.append(f"| {s['label']} | " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", required=True)
    parser.add_argument("--grammar-off")
    parser.add_argument("--gate-off")
    parser.add_argument("--out", required=True)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    summaries = [summarize(load_jsonl(args.production), "production (grammar on, gate on)")]
    if args.grammar_off:
        summaries.append(summarize(load_jsonl(args.grammar_off), "grammar off (gate on)"))
    if args.gate_off:
        summaries.append(summarize(load_jsonl(args.gate_off), "gate off (threshold 0.0)"))

    md = render_markdown(summaries)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(summaries, fh, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
