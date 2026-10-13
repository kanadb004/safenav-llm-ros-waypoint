"""Host pytest for relations.py: the hop matrix, zero target and multi target abstention."""

import json
import os
import sys

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.relations import resolve_relation  # noqa: E402

MAP_PATH = os.path.join(_PKG_ROOT, "maps", "room_annotations.json")


@pytest.fixture()
def shipped_graph():
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        return AnnotationGraph.from_dict(json.load(f))


@pytest.fixture()
def tie_graph():
    """A synthetic graph with a deliberate two-target tie, one of which is disambiguable."""
    data = {
        "version": 1,
        "facility": "test",
        "frame": "map",
        "rooms": [
            {"name": "hub", "aliases": [], "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
             "tags": [], "parent": ""},
            {"name": "room_a", "aliases": ["printer room"], "pose": {"x": 1.0, "y": 0.0, "theta": 0.0},
             "tags": ["work_area"], "parent": ""},
            {"name": "room_b", "aliases": ["storage closet"], "pose": {"x": -1.0, "y": 0.0, "theta": 0.0},
             "tags": ["utility"], "parent": ""},
            {"name": "isolated", "aliases": [], "pose": {"x": 5.0, "y": 5.0, "theta": 0.0},
             "tags": [], "parent": ""},
            {"name": "child", "aliases": ["coffee maker"], "pose": {"x": 1.1, "y": 0.1, "theta": 0.0},
             "tags": [], "parent": "room_a"},
        ],
        "edges": [
            {"from": "hub", "to": "room_a", "relation": "adjacent"},
            {"from": "hub", "to": "room_b", "relation": "adjacent"},
        ],
    }
    return AnnotationGraph.from_dict(data)


def test_adjacent_single_target_resolves(shipped_graph):
    name, n = resolve_relation(shipped_graph, "charging_dock", "adjacent", "go to the server room")
    assert n >= 1
    assert name in shipped_graph.related_rooms("charging_dock", "adjacent")


def test_left_of_uses_materialized_inverse(shipped_graph):
    name, n = resolve_relation(shipped_graph, "storage_room", "right_of", "whatever")
    assert name == "charging_dock"
    assert n == 1


def test_within_resolves_to_parent(shipped_graph):
    name, n = resolve_relation(shipped_graph, "coffee_machine", "within", "the room with the coffee machine")
    assert name == "kitchen"
    assert n == 1


def test_within_zero_targets_when_no_parent(shipped_graph):
    name, n = resolve_relation(shipped_graph, "lab_floor_1", "within", "whatever")
    assert name is None
    assert n == 0


def test_within_zero_targets_when_unknown_anchor(shipped_graph):
    name, n = resolve_relation(shipped_graph, "not_a_room", "within", "whatever")
    assert name is None
    assert n == 0


def test_zero_targets_abstains(shipped_graph):
    name, n = resolve_relation(shipped_graph, "main_entrance", "left_of", "whatever")
    assert name is None
    assert n == 0


def test_multi_target_disambiguated_by_alias(tie_graph):
    name, n = resolve_relation(tie_graph, "hub", "adjacent", "take me to the printer room")
    assert n == 2
    assert name == "room_a"


def test_multi_target_disambiguated_by_tag(tie_graph):
    name, n = resolve_relation(tie_graph, "hub", "adjacent", "I need something from the utility space")
    assert n == 2
    assert name == "room_b"


def test_multi_target_still_tied_abstains(tie_graph):
    name, n = resolve_relation(tie_graph, "hub", "adjacent", "go to the room nearby")
    assert n == 2
    assert name is None


def test_multi_target_no_match_abstains(tie_graph):
    name, n = resolve_relation(tie_graph, "hub", "adjacent", "go somewhere unrelated entirely")
    assert n == 2
    assert name is None


def test_none_relation_has_no_edges_and_abstains(tie_graph):
    # resolve_relation is only called for non-none relations by resolver_core; "none" has no
    # matching edges in any graph, so it abstains rather than guessing.
    name, n = resolve_relation(tie_graph, "hub", "none", "go to hub")
    assert name is None
    assert n == 0
