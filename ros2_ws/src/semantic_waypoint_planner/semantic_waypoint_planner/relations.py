"""Relational decomposition traversal (PLAN.md section 8.1, D29) and cue gating (8A.1, D38).

The model names an anchor room and a spatial relation; this module performs the actual hop
over the annotation graph's edges in code. ROS free, ``AnnotationGraph`` is the only
dependency, so it is exercised the same way on the host and inside the resolver node.
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional, Tuple

from .graph import INVERSE_RELATIONS, AnnotationGraph

RELATIONS = ("none", "left_of", "right_of", "adjacent", "near", "within")

_WS_RE = re.compile(r"\s+")


def _default_cues_path() -> str:
    # Mirrors prompt.py's _default_prompt_dir: ament's share directory when installed, the
    # source tree's config/ otherwise, since this module has no ROS imports of its own.
    try:
        from ament_index_python.packages import get_package_share_directory

        return os.path.join(
            get_package_share_directory("semantic_waypoint_planner"), "config", "relational_cues.json"
        )
    except Exception:
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(package_dir, "config", "relational_cues.json")


DEFAULT_CUES_PATH = _default_cues_path()


def load_cues(path: str = DEFAULT_CUES_PATH) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return list(json.load(f)["cues"])


def has_relational_cue(command: str, cues: Optional[List[str]] = None) -> bool:
    """True if ``command`` contains at least one frozen cue phrase (8A.1, case-insensitive
    substring match). Cue-free commands are resolved against the v1 grammar with the hop
    suppressed; this function makes no other decision and sees only the command text."""
    if cues is None:
        cues = load_cues()
    lowered = command.lower()
    return any(cue in lowered for cue in cues)


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
