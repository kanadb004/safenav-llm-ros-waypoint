#!/usr/bin/env python3
"""PLAN.md 11B.3: the held-out, paired effect of the spatial anchor fix (D64), with no new
inference. The prompt and grammar do not change and the fix acts after decoding, so replaying
each cached row's stored ``room``/``relation`` (``anchor_room`` when ``relation != "none"``,
else ``resolved_room``) through ``relations.apply_relational_hop`` with ``text_anchor_enabled
=True`` gives the exact fixed-resolver output up to temperature 0.3 sampling noise, which
never re-enters since the model is not re-run.

Three sets, per 11B.3:
  - ``data/frozen/phase5a_full500.jsonl`` x ``data/benchmark/synthetic_500_v2.jsonl``: raw
    top-1 (uncapped) and gated top-1 (through the deployed calibrator, the
    ``gated_benchmark_500`` path in train_calibrator.py), before and after, per category, plus
    every row whose final room changes.
  - ``calibration_session1_trials.jsonl`` and ``calibration_session2_trials.jsonl``: final room
    before and after, edit_distance recomputed against the new final room (section 12.8: it is
    computed on the final room), calibrated_confidence reconstructed through the deployed
    calibrator the same way offline_gate_comparison.py does (both sessions were collected with
    calibrator_loaded=False). Session 2's false pass and false rejection rate at 0.85, before
    and after.

This is e2e150's development set (PLAN.md 11B.0), not held-out evidence (11B.3's own warning);
only this file's three sets count toward the 11B.5 decision rule.

Usage:
    python3 ml/safenav_ml/replay_text_anchor.py --out docs/results/text_anchor_replay.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from safenav_ml import metrics  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.relations import apply_relational_hop, load_cues  # noqa: E402
from semantic_waypoint_planner.resolver_core import (  # noqa: E402
    Calibrator,
    min_edit_distance,
    normalize_command,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")
CALIBRATOR_PATH = os.path.join(ROS2_PY_PATH, "config", "calibrator.json")
BENCHMARK_V2 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")
PHASE5A_RUN = os.path.join(REPO_ROOT, "data", "frozen", "phase5a_full500.jsonl")
SESSION1_RUN = os.path.join(REPO_ROOT, "data", "frozen", "calibration_session1_trials.jsonl")
SESSION2_RUN = os.path.join(REPO_ROOT, "data", "frozen", "calibration_session2_trials.jsonl")

GATE_THRESHOLD = 0.85


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _room_or_none(value: Optional[str]) -> str:
    return value if value else "none"


def replay_room(graph: AnnotationGraph, cues: List[str], command: str, relation: str,
                 anchor_room: str, resolved_room: str) -> tuple:
    """Returns ``(after_room, anchor_used, anchor_source)``. Rows where the model never
    attempted a hop (``relation == "none"`` or no cached anchor) are unaffected by the fix:
    ``after_room`` equals the stored ``resolved_room``."""
    if relation == "none" or not anchor_room or anchor_room == "none":
        return _room_or_none(resolved_room), anchor_room, ""
    after_room, anchor_used, anchor_source, _n = apply_relational_hop(
        graph, command, relation, anchor_room, True, cues
    )
    return _room_or_none(after_room), anchor_used, anchor_source


# ---------------------------------------------------------------------------
# Corrected 500 benchmark
# ---------------------------------------------------------------------------

def build_500_replay(graph: AnnotationGraph, cues: List[str]) -> List[dict]:
    run_rows = {r["id"]: r for r in load_jsonl(PHASE5A_RUN)}
    labeled_rows = load_jsonl(BENCHMARK_V2)

    out = []
    for labeled in labeled_rows:
        rid = labeled["id"]
        run_row = run_rows.get(rid)
        if run_row is None:
            continue
        relation = run_row.get("relation", "none")
        anchor_room = run_row.get("anchor_room", "")
        command = run_row["command"]
        before = _room_or_none(run_row["resolved_room"])
        # Sanity check: replaying with the fix disabled must reproduce the cached output
        # exactly, confirming this replay is a faithful stand-in for re-running the resolver.
        if relation != "none" and anchor_room and anchor_room != "none":
            reproduced = _room_or_none(
                apply_relational_hop(graph, command, relation, anchor_room, False, cues)[0]
            )
            if reproduced != before:
                raise RuntimeError(
                    f"{rid}: replay with text_anchor=False gives {reproduced!r}, cached "
                    f"resolved_room is {before!r}; the graph or cue list has drifted since "
                    "this run"
                )
        after, anchor_used, anchor_source = replay_room(
            graph, cues, command, relation, anchor_room, before
        )
        out.append({
            "id": rid,
            "category": labeled["category"],
            "command": command,
            "expected": labeled["expected"],
            "before": before,
            "after": after,
            "anchor_room": anchor_room,
            "anchor_source": anchor_source,
            "raw_confidence": run_row["raw_confidence"],
            "token_entropy": run_row["token_entropy"],
        })
    return out


def _top1_rows(rows: List[dict], room_key: str) -> List[dict]:
    return [{"predicted": r[room_key], "expected": r["expected"], "category": r["category"]} for r in rows]


def gated_500(rows: List[dict], room_key: str, graph: AnnotationGraph, calibrator: Calibrator) -> dict:
    out_rows = []
    for r in rows:
        room = None if r[room_key] in (None, "none") else r[room_key]
        aliases = graph.get_room(room).aliases if room and graph.get_room(room) else []
        command_norm = normalize_command(r["command"])
        edit_distance = min_edit_distance(room, aliases, command_norm)
        feat = [r["raw_confidence"], r["token_entropy"], float(len(graph.canonical_names)),
                 float(len(command_norm)), float(edit_distance)]
        calibrated = calibrator.calibrate(r["raw_confidence"], feat)
        predicted = r[room_key] if calibrated >= calibrator.threshold else "none"
        out_rows.append({"predicted": predicted, "expected": r["expected"], "category": r["category"]})
    return {"n": len(out_rows), "top1": metrics.top1(out_rows), "per_category": metrics.per_category_top1(out_rows)}


# ---------------------------------------------------------------------------
# Calibration sessions
# ---------------------------------------------------------------------------

def build_session_replay(path: str, graph: AnnotationGraph, cues: List[str],
                          calibrator: Calibrator) -> List[dict]:
    rows = load_jsonl(path)
    out = []
    for r in rows:
        relation = r.get("relation", "none")
        anchor_room = r.get("anchor_room", "")
        command = r["command"]
        before = _room_or_none(r.get("resolved_room"))
        after, anchor_used, anchor_source = replay_room(graph, cues, command, relation, anchor_room, before)

        before_room = None if before == "none" else before
        before_aliases = graph.get_room(before_room).aliases if before_room and graph.get_room(before_room) else []
        before_feat = [r["raw_confidence"], r["token_entropy"], r["n_candidates"], r["command_length"],
                       r["edit_distance"]]
        before_calibrated = calibrator.calibrate(r["raw_confidence"], before_feat)

        after_room = None if after == "none" else after
        after_aliases = graph.get_room(after_room).aliases if after_room and graph.get_room(after_room) else []
        command_norm = normalize_command(command)
        after_edit_distance = min_edit_distance(after_room, after_aliases, command_norm)
        after_feat = [r["raw_confidence"], r["token_entropy"], r["n_candidates"], r["command_length"],
                      float(after_edit_distance)]
        after_calibrated = calibrator.calibrate(r["raw_confidence"], after_feat)

        out.append({
            "run_id": r.get("run_id", ""),
            "category": r["category"],
            "command": command,
            "intended_room": r["intended_room"],
            "before_room": before,
            "after_room": after,
            "anchor_source": anchor_source,
            "before_edit_distance": r["edit_distance"],
            "after_edit_distance": after_edit_distance,
            "before_calibrated": before_calibrated,
            "after_calibrated": after_calibrated,
        })
    return out


def gate_rates(rows: List[dict], room_key: str, calibrated_key: str, threshold: float) -> dict:
    probs = [r[calibrated_key] for r in rows]
    labels = [int(r[room_key] == r["intended_room"]) for r in rows]
    return {
        "false_pass_rate": metrics.false_pass_rate(probs, labels, threshold),
        "false_rejection_rate": metrics.false_rejection_rate(probs, labels, threshold),
        "n_correct": sum(labels),
        "n": len(rows),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _changed_rows_500(rows: List[dict]) -> List[dict]:
    changed = []
    for r in rows:
        if r["before"] == r["after"]:
            continue
        before_correct = r["before"] == r["expected"]
        after_correct = r["after"] == r["expected"]
        if after_correct and not before_correct:
            direction = "to correct"
        elif before_correct and not after_correct:
            direction = "from correct"
        else:
            direction = "wrong to wrong"
        changed.append({**r, "direction": direction})
    return changed


def _changed_rows_session(rows: List[dict]) -> List[dict]:
    changed = []
    for r in rows:
        if r["before_room"] == r["after_room"]:
            continue
        before_correct = r["before_room"] == r["intended_room"]
        after_correct = r["after_room"] == r["intended_room"]
        if after_correct and not before_correct:
            direction = "to correct"
        elif before_correct and not after_correct:
            direction = "from correct"
        else:
            direction = "wrong to wrong"
        changed.append({**r, "direction": direction})
    return changed


def render(rows_500, gated_before, gated_after, session1_rows, session2_rows,
           session2_before_gate, session2_after_gate) -> str:
    lines = ["# PLAN.md 11B.3: text anchor fix, held-out replay (D64)\n"]

    raw_before = metrics.top1(_top1_rows(rows_500, "before"))
    raw_after = metrics.top1(_top1_rows(rows_500, "after"))
    cat_before = metrics.per_category_top1(_top1_rows(rows_500, "before"))
    cat_after = metrics.per_category_top1(_top1_rows(rows_500, "after"))
    changed_500 = _changed_rows_500(rows_500)
    to_correct = sum(1 for c in changed_500 if c["direction"] == "to correct")
    from_correct = sum(1 for c in changed_500 if c["direction"] == "from correct")

    lines.append("## Corrected 500 benchmark (phase5a_full500.jsonl x synthetic_500_v2.jsonl)\n")
    lines.append(f"n = {len(rows_500)}. Rows changed: {len(changed_500)} "
                 f"({to_correct} to correct, {from_correct} from correct, "
                 f"{len(changed_500) - to_correct - from_correct} wrong to wrong).\n")
    lines.append("| | raw top-1 (uncapped) | gated top-1 (0.85) |")
    lines.append("|---|---|---|")
    lines.append(f"| before | {raw_before:.3f} | {gated_before['top1']:.3f} |")
    lines.append(f"| after | {raw_after:.3f} | {gated_after['top1']:.3f} |")
    lines.append("")
    lines.append("Per category, raw top-1:\n")
    lines.append("| category | before | after |")
    lines.append("|---|---|---|")
    for cat in sorted(cat_before):
        lines.append(f"| {cat} | {cat_before[cat]:.3f} | {cat_after[cat]:.3f} |")
    lines.append("")
    lines.append("Per category, gated top-1 (0.85):\n")
    lines.append("| category | before | after |")
    lines.append("|---|---|---|")
    for cat in sorted(gated_before["per_category"]):
        b = gated_before["per_category"][cat]
        a = gated_after["per_category"][cat]
        lines.append(f"| {cat} | {b:.3f} | {a:.3f} |")
    lines.append("")
    lines.append("Every changed row:\n")
    lines.append("| id | category | before | after | expected | anchor source | direction |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in sorted(changed_500, key=lambda r: r["id"]):
        lines.append(
            f"| {c['id']} | {c['category']} | {c['before']} | {c['after']} | {c['expected']} | "
            f"{c['anchor_source']} | {c['direction']} |"
        )
    lines.append("")

    for label, rows in (("session 1", session1_rows), ("session 2", session2_rows)):
        changed = _changed_rows_session(rows)
        to_c = sum(1 for c in changed if c["direction"] == "to correct")
        from_c = sum(1 for c in changed if c["direction"] == "from correct")
        lines.append(f"## Calibration {label} (n={len(rows)})\n")
        lines.append(f"Rows changed: {len(changed)} ({to_c} to correct, {from_c} from correct, "
                     f"{len(changed) - to_c - from_c} wrong to wrong).\n")
        lines.append("| run_id | category | before room | after room | intended | "
                     "before edit_distance | after edit_distance | before calibrated | "
                     "after calibrated | anchor source | direction |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for c in sorted(changed, key=lambda r: r["run_id"]):
            lines.append(
                f"| {c['run_id']} | {c['category']} | {c['before_room']} | {c['after_room']} | "
                f"{c['intended_room']} | {c['before_edit_distance']} | {c['after_edit_distance']} | "
                f"{c['before_calibrated']:.3f} | {c['after_calibrated']:.3f} | {c['anchor_source']} | "
                f"{c['direction']} |"
            )
        lines.append("")

    lines.append(f"## Session 2 gate rates at {GATE_THRESHOLD}\n")
    lines.append("| | false pass rate | false rejection rate | n correct / n |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| before | {session2_before_gate['false_pass_rate']:.3f} | "
        f"{session2_before_gate['false_rejection_rate']:.3f} | "
        f"{session2_before_gate['n_correct']}/{session2_before_gate['n']} |"
    )
    lines.append(
        f"| after | {session2_after_gate['false_pass_rate']:.3f} | "
        f"{session2_after_gate['false_rejection_rate']:.3f} | "
        f"{session2_after_gate['n_correct']}/{session2_after_gate['n']} |"
    )
    lines.append("")

    gain = (raw_after - raw_before) >= 0.0 if raw_before is not None else False
    rows_gained_minus_lost = to_correct - from_correct
    lines.append("## PLAN.md 11B.5 decision rule inputs\n")
    lines.append(f"- session 2 false pass at {GATE_THRESHOLD}, after: "
                 f"{session2_after_gate['false_pass_rate']:.3f} "
                 f"({'<=' if session2_after_gate['false_pass_rate'] <= 0.05 else '>'} 0.05)")
    lines.append(f"- corrected 500 top-1, rows gained minus lost: {rows_gained_minus_lost} "
                 f"({'>= 0' if rows_gained_minus_lost >= 0 else '< 0'})")
    lines.append("")

    return "\n".join(lines)


def _write_jsonl(path: str, rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "results", "text_anchor_replay.md"))
    parser.add_argument("--out-rows-dir", default=os.path.join(REPO_ROOT, "data", "runs"),
                         help="Row-level replay JSONL files (11B.3/11B.6 data freeze).")
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    cues = load_cues()
    calibrator = Calibrator(CALIBRATOR_PATH)

    rows_500 = build_500_replay(graph, cues)
    gated_before = gated_500(rows_500, "before", graph, calibrator)
    gated_after = gated_500(rows_500, "after", graph, calibrator)

    session1_rows = build_session_replay(SESSION1_RUN, graph, cues, calibrator)
    session2_rows = build_session_replay(SESSION2_RUN, graph, cues, calibrator)

    session2_before_gate = gate_rates(session2_rows, "before_room", "before_calibrated", GATE_THRESHOLD)
    session2_after_gate = gate_rates(session2_rows, "after_room", "after_calibrated", GATE_THRESHOLD)

    text = render(
        rows_500, gated_before, gated_after, session1_rows, session2_rows,
        session2_before_gate, session2_after_gate,
    )
    print(text)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nwrote {args.out}")

    _write_jsonl(os.path.join(args.out_rows_dir, "text_anchor_replay_500.jsonl"), rows_500)
    _write_jsonl(os.path.join(args.out_rows_dir, "text_anchor_replay_session1.jsonl"), session1_rows)
    _write_jsonl(os.path.join(args.out_rows_dir, "text_anchor_replay_session2.jsonl"), session2_rows)
    print(f"wrote row-level replay files to {args.out_rows_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
