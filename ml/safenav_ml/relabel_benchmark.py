#!/usr/bin/env python3
"""Phase 5A benchmark re-audit (PLAN.md section 8A.2). Frozen before being run.

The rule (verbatim, also copied into data/benchmark/RELABEL.md):

  For every spatial and multi_hop row, compute from the graph alone whether a unique target
  exists: enumerate plausible anchors (audit_edges.detect_anchors, label-blind: expected=None),
  apply the row's relation (audit_edges.detect_relations), and apply the section 8.1
  disambiguation policy (relations.py traversal: alias/tag overlap, symmetric/inverse
  materialization). Collect the set of distinct targets reached by any (anchor, relation) pair
  found in the command text.

    - Exactly one surviving target: structurally_answerable = true, expected unchanged.
    - Zero or more than one surviving target: structurally_answerable = false, expected
      becomes "none".

  The rule sees only the graph and the command text. It never sees a model prediction. It runs
  over all 130 spatial/multi_hop rows and its output is whatever it is: no hand-picking, no
  exceptions, no post-hoc adjustment. Rows outside spatial/multi_hop are passed through
  unchanged (structurally_answerable is not applicable and is recorded as null).

This reuses audit_edges.py's detect_anchors/detect_relations (the same functions the D32
ceiling check used) rather than a second implementation that could disagree with it.

Usage: python3 ml/safenav_ml/relabel_benchmark.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PKG_ROOT = os.path.join(_REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner")
sys.path.insert(0, _PKG_ROOT)

from audit_edges import MAP_PATH, detect_anchors, detect_relations  # noqa: E402
from semantic_waypoint_planner.graph import INVERSE_RELATIONS, AnnotationGraph  # noqa: E402

BENCHMARK_PATH = os.path.join(_REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")
OUTPUT_PATH = os.path.join(_REPO_ROOT, "data", "benchmark", "synthetic_500_v2.jsonl")
RELABEL_DOC_PATH = os.path.join(_REPO_ROOT, "data", "benchmark", "RELABEL.md")

RULE_TEXT = (
    "For every spatial and multi_hop row, compute from the graph alone whether a unique "
    "target exists: enumerate plausible anchors (label-blind word/alias overlap with the "
    "command text, never the row's own expected label), apply the relation keyword(s) found "
    "in the command text, and apply the section 8.1 disambiguation policy (symmetric and "
    "inverse edge materialization, alias/tag overlap). Collect the set of distinct targets "
    "reached by any (anchor, relation) pair the text supports. Exactly one surviving target: "
    "structurally_answerable = true, expected unchanged. Zero or more than one surviving "
    "target: structurally_answerable = false, expected becomes \"none\". The rule sees only "
    "the graph and the command text, never a model prediction. It runs over all 130 rows "
    "unmodified by hand."
)


def structurally_answerable_targets(graph: AnnotationGraph, command: str):
    """Same primitives as audit_edges.check_row (detect_anchors, detect_relations, the
    left_of/right_of inverse flip, related_rooms, parent for within), restructured to collect
    every target reached rather than testing against one known-correct label."""
    anchors = detect_anchors(graph, command, expected=None)
    relations = detect_relations(command)
    targets = set()
    for anchor in anchors:
        for relation in relations:
            if relation == "within":
                room = graph.get_room(anchor)
                if room and room.parent:
                    targets.add(room.parent)
            else:
                query_relation = INVERSE_RELATIONS.get(relation, relation)
                targets |= set(graph.related_rooms(anchor, query_relation))
    return targets


def relabel_row(graph: AnnotationGraph, row: dict) -> dict:
    targets = structurally_answerable_targets(graph, row["command"])
    out = dict(row)
    out["expected_original"] = row["expected"]
    if len(targets) == 1:
        out["structurally_answerable"] = True
        out["expected"] = row["expected"]
        out["relabel_reasoning"] = f"unique candidate target: {next(iter(targets))}"
    elif len(targets) == 0:
        out["structurally_answerable"] = False
        out["expected"] = "none"
        out["relabel_reasoning"] = "no candidate anchor/relation combination reached a target"
    else:
        out["structurally_answerable"] = False
        out["expected"] = "none"
        out["relabel_reasoning"] = f"{len(targets)} distinct candidate targets: {sorted(targets)}"
    return out


def main():
    graph = AnnotationGraph.from_file(MAP_PATH)
    rows = []
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    out_rows = []
    relabeled = []
    for row in rows:
        if row["category"] in ("spatial", "multi_hop"):
            out = relabel_row(graph, row)
            if out["expected"] != out["expected_original"]:
                relabeled.append(out)
        else:
            out = dict(row)
            out["expected_original"] = row["expected"]
            out["structurally_answerable"] = None
            out["relabel_reasoning"] = "not applicable (category is not spatial/multi_hop)"
        out_rows.append(out)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row) + "\n")

    by_category = {}
    for row in out_rows:
        if row["category"] not in ("spatial", "multi_hop"):
            continue
        by_category.setdefault(row["category"], [0, 0])
        by_category[row["category"]][1] += 1
        if row["expected"] != row["expected_original"]:
            by_category[row["category"]][0] += 1

    examples = relabeled[:10]
    doc_lines = [
        "# Benchmark relabel (PLAN.md section 8A.2, D39)",
        "",
        "Frozen rule, run once, unmodified by hand:",
        "",
        f"> {RULE_TEXT}",
        "",
        "## Counts by category",
        "",
        "| category | relabelled to none | total |",
        "|---|---|---|",
    ]
    for cat, (n_relabeled, total) in sorted(by_category.items()):
        doc_lines.append(f"| {cat} | {n_relabeled} | {total} |")
    doc_lines += [
        "",
        f"Total relabelled: {len(relabeled)} / 130.",
        "",
        "## Ten worked examples",
        "",
    ]
    for row in examples:
        doc_lines.append(f"- `{row['id']}` ({row['category']}): \"{row['command']}\"")
        doc_lines.append(f"  - original label: `{row['expected_original']}`")
        doc_lines.append(f"  - corrected label: `{row['expected']}`")
        doc_lines.append(f"  - reasoning: {row['relabel_reasoning']}")
    doc_lines.append("")

    with open(RELABEL_DOC_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(doc_lines) + "\n")

    print(f"wrote {OUTPUT_PATH}")
    print(f"wrote {RELABEL_DOC_PATH}")
    print(f"total relabelled: {len(relabeled)} / 130")
    for cat, (n_relabeled, total) in sorted(by_category.items()):
        print(f"  {cat}: {n_relabeled}/{total}")


if __name__ == "__main__":
    main()
