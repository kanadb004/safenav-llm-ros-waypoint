"""Fast path, edit distance, and feature vector tests that need no model (PLAN.md Phase 3)."""

import pytest

from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.resolver_core import (
    ResolveResult,
    fast_path_match,
    features,
    min_edit_distance,
    normalize_command,
)

FIXTURE = {
    "version": 1,
    "facility": "safenav_lab",
    "frame": "map",
    "rooms": [
        {
            "name": "kitchen",
            "aliases": ["break room", "kitchenette"],
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
        },
        {
            "name": "charging_dock",
            "aliases": ["dock", "charger"],
            "pose": {"x": 1.0, "y": 1.0, "theta": 0.0},
        },
    ],
    "edges": [],
}


def _graph():
    return AnnotationGraph.from_dict(FIXTURE)


def test_normalize_collapses_whitespace_and_case():
    assert normalize_command("  Go   TO the Kitchen  ") == "go to the kitchen"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("kitchen", "kitchen"),
        ("break room", "kitchen"),
        ("dock", "charging_dock"),
        ("go to the kitchen", "kitchen"),
        ("navigate to break room", "kitchen"),
        ("take me to the charger", "charging_dock"),
        ("head to dock", "charging_dock"),
    ],
)
def test_fast_path_matches(command, expected):
    assert fast_path_match(_graph(), command) == expected


@pytest.mark.parametrize(
    "command",
    ["somewhere I can charge the robot", "go to the cafeteria", ""],
)
def test_fast_path_misses(command):
    assert fast_path_match(_graph(), command) is None


def test_min_edit_distance_exact_match_is_zero():
    assert min_edit_distance("kitchen", ["break room"], "go to the kitchen now") == 0


def test_min_edit_distance_uses_alias():
    assert min_edit_distance("kitchen", ["break room"], "please visit the break room") == 0


def test_min_edit_distance_none_room_is_command_length():
    norm = normalize_command("go to the cafeteria")
    assert min_edit_distance(None, [], norm) == len(norm)


def test_features_vector_order():
    result = ResolveResult(
        room="kitchen",
        raw_confidence=0.9,
        reasoning="",
        token_entropy=0.1,
        room_ranking=[("kitchen", 0.9)],
        latency_ms=5.0,
        mode="fast_path",
        out_of_graph=False,
        raw_text="",
    )
    vec = features(result, "go to the kitchen", 30, aliases=["break room"])
    assert len(vec) == 5
    assert vec[0] == 0.9
    assert vec[1] == 0.1
    assert vec[2] == 30.0
    assert vec[3] == float(len(normalize_command("go to the kitchen")))
    assert vec[4] == 0.0
