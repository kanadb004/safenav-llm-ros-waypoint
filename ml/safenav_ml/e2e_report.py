"""Phase 8 e2e150 report (PLAN.md section 11): success rate, false start rate, time to
navigation start p50/p90, end to end latency p50/p90/p99, resolver latency p50/p90/p99, and
out of graph counts, computed from the run_trials.py JSONL output for one or more e2e150
suites (production, grammar off, gate off). Writes a markdown table per suite plus a combined
comparison table into docs/results/.

Usage:
    python3 ml/safenav_ml/e2e_report.py \
        --production data/runs/e2e150_loopback.jsonl \
        --grammar-off data/runs/e2e150_grammar_off.jsonl \
        --gate-off data/runs/e2e150_gate_off.jsonl \
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
        return {"p50": None, "p90": None, "p99": None}
    return {
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "p99": _percentile(values, 0.99),
    }


def summarize(rows: List[dict], label: str) -> Dict:
    n = len(rows)
    nav_success = sum(1 for r in rows if r.get("nav_result") == "succeeded")
    gate_passed = sum(1 for r in rows if r.get("gate_passed"))
    reached = [r for r in rows if r.get("reached_intended") is not None]
    reached_true = sum(1 for r in reached if r.get("reached_intended"))
    out_of_graph = sum(1 for r in rows if r.get("out_of_graph"))

    # A "false start" is a gate pass that did not actually reach the intended room, i.e. the
    # gate accepted a resolution that turned out wrong once driven, not merely a non-abstention.
    false_starts = sum(
        1 for r in rows
        if r.get("gate_passed") and r.get("reached_intended") is False
    )

    e2e_ms = [r.get("e2e_ms") for r in rows if r.get("e2e_ms") is not None]
    resolver_ms = [r.get("resolver_ms") for r in rows if r.get("resolver_ms") is not None]
    t_nav_start = []
    for r in rows:
        if r.get("t_nav_start") is not None and r.get("t_command") is not None:
            t_nav_start.append((r["t_nav_start"] - r["t_command"]) * 1000.0)

    return {
        "label": label,
        "n": n,
        "success_rate": nav_success / n if n else None,
        "gate_pass_rate": gate_passed / n if n else None,
        "reached_intended_rate": (reached_true / len(reached)) if reached else None,
        "false_start_rate": (false_starts / gate_passed) if gate_passed else None,
        "out_of_graph_count": out_of_graph,
        "out_of_graph_rate": out_of_graph / n if n else None,
        "e2e_ms": _percentiles(e2e_ms),
        "resolver_ms": _percentiles(resolver_ms),
        "time_to_nav_start_ms": _percentiles(t_nav_start),
    }


def render_markdown(summaries: List[Dict]) -> str:
    lines = ["# Phase 8: e2e150 suite results", ""]
    lines.append("| suite | n | success rate | gate pass rate | reached intended | false start rate | "
                  "out of graph | e2e p50/p90/p99 ms | resolver p50/p90/p99 ms | nav start p50/p90 ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    def fmt3(v: Optional[float]) -> str:
        return "n/a" if v is None else f"{v:.3f}"

    def fmt_lat(p: Dict[str, Optional[float]]) -> str:
        if p["p50"] is None:
            return "n/a"
        return f"{p['p50']:.0f}/{p['p90']:.0f}/{p['p99']:.0f}"

    def fmt_nav_start(p: Dict[str, Optional[float]]) -> str:
        if p["p50"] is None:
            return "n/a"
        return f"{p['p50']:.0f}/{p['p90']:.0f}"

    for s in summaries:
        lines.append(
            f"| {s['label']} | {s['n']} | {fmt3(s['success_rate'])} | {fmt3(s['gate_pass_rate'])} | "
            f"{fmt3(s['reached_intended_rate'])} | {fmt3(s['false_start_rate'])} | "
            f"{s['out_of_graph_count']} ({fmt3(s['out_of_graph_rate'])}) | "
            f"{fmt_lat(s['e2e_ms'])} | {fmt_lat(s['resolver_ms'])} | "
            f"{fmt_nav_start(s['time_to_nav_start_ms'])} |"
        )
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
