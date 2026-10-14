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

# PLAN.md 11B.2: the relations the text anchor rule covers. "within" is excluded, since it
# legitimately anchors on whatever sub location the model names (the contract this rule does
# not override); "none" means there is no hop to anchor at all.
TEXT_ANCHOR_RELATIONS = ("left_of", "right_of", "adjacent", "near")

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


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


def _normalize_for_anchor(text: str) -> str:
    """Lowercase, punctuation to spaces, collapsed whitespace (PLAN.md 11B.2 step 2)."""
    lowered = text.strip().lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", no_punct).strip()


def _edge_bearing_rooms(graph: AnnotationGraph) -> set:
    """Rooms that appear in at least one ``edges`` entry. Sub locations have no edges and
    cannot anchor a left, right, adjacent or near hop (11B.2 step 2)."""
    names = set()
    for edge in graph.edges:
        names.add(edge.from_)
        names.add(edge.to)
    return names


def _cue_end(normalized_command: str, cues: List[str]) -> Optional[int]:
    """Index just past the first cue phrase in ``normalized_command``: the earliest starting
    match, longest cue first on a tie. ``None`` when no cue is present."""
    best: Optional[Tuple[int, int]] = None
    for cue in cues:
        cue_norm = _normalize_for_anchor(cue)
        if not cue_norm:
            continue
        idx = normalized_command.find(cue_norm)
        if idx == -1:
            continue
        end = idx + len(cue_norm)
        if best is None or idx < best[0] or (idx == best[0] and end > best[1]):
            best = (idx, end)
    return best[1] if best else None


def extract_text_anchor(
    graph: AnnotationGraph, command: str, cues: Optional[List[str]] = None
) -> Optional[str]:
    """PLAN.md 11B.2 step 2: the anchor room named in ``command``'s text, independent of what
    the model emitted. Searches the text after the first relational cue phrase for canonical
    names (underscores as spaces) and aliases of edge bearing rooms, longest match first, on
    word boundaries. Returns the single matching room, or ``None`` when the cue is missing, no
    edge bearing room follows it, or more than one distinct room does (both fall back to the
    model's own room as anchor in the caller, PLAN.md 11B.2 step 4)."""
    if cues is None:
        cues = load_cues()
    normalized = _normalize_for_anchor(command)
    end = _cue_end(normalized, cues)
    if end is None:
        return None
    remainder = normalized[end:]

    edge_rooms = _edge_bearing_rooms(graph)
    phrases: List[Tuple[str, str]] = []
    for name in edge_rooms:
        room = graph.get_room(name)
        candidates = [name.replace("_", " ")] + (list(room.aliases) if room else [])
        for phrase in candidates:
            phrase_norm = _normalize_for_anchor(phrase)
            if phrase_norm:
                phrases.append((phrase_norm, name))
    # Longest phrase first, so a shorter alias of a different room never pre-empts a longer,
    # more specific match at the same position (11B.2 step 2).
    phrases.sort(key=lambda p: len(p[0]), reverse=True)

    found_rooms: List[str] = []
    for phrase_norm, name in phrases:
        if name in found_rooms:
            continue
        if re.search(r"\b" + re.escape(phrase_norm) + r"\b", remainder):
            found_rooms.append(name)

    distinct = set(found_rooms)
    if len(distinct) == 1:
        return next(iter(distinct))
    return None


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


def apply_relational_hop(
    graph: AnnotationGraph,
    command: str,
    relation: str,
    model_room: str,
    text_anchor_enabled: bool = True,
    cues: Optional[List[str]] = None,
) -> Tuple[str, str, str, int]:
    """PLAN.md 11B.2: given the model's own ``relation`` and ``room`` (``model_room``, v1
    semantics: the anchor before any hop), decide the hop anchor and perform the single hop.

    Returns ``(final_room, anchor_used, anchor_source, n_relation_targets)``. ``anchor_source``
    is ``""`` when no hop is attempted at all (``relation == "none"`` or ``model_room`` is not a
    canonical name: the model abstained or named nothing resolvable), ``"text"`` when a unique
    text anchor was found and used, ``"model"`` otherwise (today's behaviour, including every
    ``within`` hop, which this rule never overrides).

    Called identically by the resolver (``resolver_core.py``) and the held-out replay
    (``ml/safenav_ml/replay_text_anchor.py``, PLAN.md 11B.3); never reimplement this decision
    elsewhere.
    """
    if relation == "none" or model_room in ("", "none") or model_room not in graph.canonical_names:
        return (model_room or "none"), model_room, "", 0

    anchor = model_room
    anchor_source = "model"
    if text_anchor_enabled and relation in TEXT_ANCHOR_RELATIONS:
        text_anchor_room = extract_text_anchor(graph, command, cues)
        if text_anchor_room is not None:
            anchor = text_anchor_room
            anchor_source = "text"

    target, n_targets = resolve_relation(graph, anchor, relation, command)
    final_room = target if target is not None else "none"
    return final_room, anchor, anchor_source, n_targets
