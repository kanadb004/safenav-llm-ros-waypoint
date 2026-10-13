#!/usr/bin/env python3
"""Edge coverage audit (PLAN.md section 8.1, do this first).

For every ``spatial``/``multi_hop`` benchmark row, finds anchor rooms the command text names
(by alias or canonical name) and the relation keyword it uses, then checks whether the graph's
``related_rooms`` (or ``parent`` for ``within``) already reaches the row's expected room from
that anchor. This measures the graph's structural coverage independent of the model, which is
exactly the question section 8.1 asks before the relational decomposition is built: if the
edges are not there, no amount of model or prompt work can recover the answer.

Usage: python3 ml/safenav_ml/audit_edges.py
"""

import json
import os
import re
import sys
from typing import Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PKG_ROOT = os.path.join(_REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner")
sys.path.insert(0, _PKG_ROOT)

from semantic_waypoint_planner.graph import INVERSE_RELATIONS, AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.relations import resolve_relation  # noqa: E402

MAP_PATH = os.path.join(_PKG_ROOT, "maps", "room_annotations.json")
BENCHMARK_PATH = os.path.join(_REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")

RELATION_KEYWORDS = [
    (re.compile(r"\bleft\b"), "left_of"),
    (re.compile(r"\bright\b"), "right_of"),
    (re.compile(r"\b(adjacent|beside|next to)\b"), "adjacent"),
    (re.compile(r"\b(near|close|closest)\b"), "near"),
    (re.compile(r"\bwith(in)?\b"), "within"),
]


def detect_relations(command: str):
    found = []
    for pattern, relation in RELATION_KEYWORDS:
        if pattern.search(command):
            found.append(relation)
    return found or ["adjacent"]  # most spatial rows use "next to"/"beside" phrasing


_STOPWORDS = {"the", "room", "area", "space", "where", "we", "a", "of", "is", "are", "to"}


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _keywords(text: str):
    words = re.findall(r"[a-z]+", text.lower())
    return {_singular(w) for w in words if len(w) >= 4 and w not in _STOPWORDS}


def detect_anchors(graph: AnnotationGraph, command: str, expected: Optional[str] = None):
    """Word-level (not phrase-level) overlap, singularized, so "servers are kept" still
    matches "server_room"/"server rack room" even though no alias contains that exact
    phrase. This is the same lenient scoring relations.py's own disambiguation uses.

    ``expected`` excludes that room from the candidate set, which is appropriate for the
    model-accuracy ceiling check (section 2 of the phase 5 report) but not for the phase 5A
    relabel rule (8A.2), which must be label-blind; that caller passes ``expected=None``.
    """
    command_words = _keywords(command)
    anchors = []
    for room in graph.rooms:
        if expected is not None and room.name == expected:
            continue
        room_words = _keywords(room.name.replace("_", " "))
        for alias in room.aliases:
            room_words |= _keywords(alias)
        if room_words & command_words:
            anchors.append(room.name)
    return anchors


def check_row(graph: AnnotationGraph, command: str, expected: str):
    """Returns True if some (anchor, relation) pair found in the text already reaches
    ``expected`` in the current graph."""
    anchors = detect_anchors(graph, command, expected)
    relations = detect_relations(command)
    for anchor in anchors:
        for relation in relations:
            if relation == "within":
                room = graph.get_room(anchor)
                if room and room.parent == expected:
                    return True
            else:
                # Same query-side flip as relations.py: "left of the anchor" is answered by
                # the anchor's inverse relation (see relations.py's resolve_relation).
                query_relation = INVERSE_RELATIONS.get(relation, relation)
                if expected in graph.related_rooms(anchor, query_relation):
                    return True
    return False


def load_rows():
    rows = []
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["category"] in ("spatial", "multi_hop"):
                rows.append(row)
    return rows


def audit(graph: AnnotationGraph, rows):
    by_relation = {}
    served_rows = []
    unserved_rows = []
    for row in rows:
        ok = check_row(graph, row["command"], row["expected"])
        (served_rows if ok else unserved_rows).append(row)
        for relation in detect_relations(row["command"]):
            by_relation.setdefault(relation, [0, 0])
            by_relation[relation][1] += 1
            if ok:
                by_relation[relation][0] += 1
    return by_relation, served_rows, unserved_rows


def main():
    graph = AnnotationGraph.from_file(MAP_PATH)
    rows = load_rows()
    by_relation, served, unserved = audit(graph, rows)

    print(f"{len(rows)} spatial/multi_hop rows audited")
    print(f"{len(served)} served by an edge already in the graph, {len(unserved)} not\n")
    print(f"{'relation':<10} {'edges in graph':<16} {'rows served/total (text match)':<30}")
    for relation in ("left_of", "right_of", "adjacent", "near", "within"):
        n_edges = sum(1 for e in graph.edges if e.relation == relation)
        served_n, total_n = by_relation.get(relation, [0, 0])
        print(f"{relation:<10} {n_edges:<16} {served_n}/{total_n}")

    print("\nUnserved rows (candidate for missing edges, or a dataset artifact):")
    for row in unserved:
        print(f"  {row['id']} | {row['command']} -> {row['expected']}")


if __name__ == "__main__":
    main()
