"""Relational decomposition traversal (PLAN.md section 8.1, D29).

The model names an anchor room and a spatial relation; this module performs the actual hop
over the annotation graph's edges in code. ROS free, ``AnnotationGraph`` is the only
dependency, so it is exercised the same way on the host and inside the resolver node.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .graph import INVERSE_RELATIONS, AnnotationGraph

RELATIONS = ("none", "left_of", "right_of", "adjacent", "near", "within")

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.strip().lower())


def _candidate_score(graph: AnnotationGraph, room_name: str, normalized_command: str) -> int:
    """Count alias/tag words of ``room_name`` that appear in the normalized command."""
    room = graph.get_room(room_name)
    if room is None:
        return 0
    score = 0
    for alias in room.aliases:
        if alias and alias in normalized_command:
            score += 1
    for tag in room.tags:
        tag_text = tag.replace("_", " ")
        if tag_text and tag_text in normalized_command:
            score += 1
    if room_name.replace("_", " ") in normalized_command:
        score += 1
    return score


def resolve_relation(
    graph: AnnotationGraph, anchor: str, relation: str, command: str
) -> Tuple[Optional[str], int]:
    """Traverse ``relation`` from ``anchor``. Returns ``(target_name_or_none, n_targets)``.

    ``n_targets`` is the count of candidate targets before disambiguation, returned even on
    abstention so Phase 7 can use it as a feature. Never guesses: zero or still-tied targets
    abstain with ``None``.
    """
    if relation == "within":
        room = graph.get_room(anchor)
        parent = room.parent if room else ""
        if not parent or graph.get_room(parent) is None:
            return None, 0
        return parent, 1

    if relation not in RELATIONS:
        return None, 0

    # "room is left_of/right_of" describes the user's intent as a direction relative to the
    # anchor ("the room to the left of the kitchen"), i.e. the target satisfies
    # target <relation> anchor, not anchor <relation> target. An edge (A, B, "left_of") in
    # room_annotations.json means "A is left_of B" (12.7), so finding the target requires the
    # query to pivot through the inverse relation: "the thing left_of kitchen" is whatever
    # kitchen is right_of. Symmetric relations (adjacent/near) and "within" need no such flip.
    query_relation = INVERSE_RELATIONS.get(relation, relation)
    targets = graph.related_rooms(anchor, query_relation)
    if not targets:
        return None, 0
    if len(targets) == 1:
        return targets[0], 1

    normalized_command = _normalize(command)
    scored = [(t, _candidate_score(graph, t, normalized_command)) for t in targets]
    best_score = max(score for _, score in scored)
    best = [t for t, score in scored if score == best_score]
    if best_score > 0 and len(best) == 1:
        return best[0], len(targets)
    return None, len(targets)
