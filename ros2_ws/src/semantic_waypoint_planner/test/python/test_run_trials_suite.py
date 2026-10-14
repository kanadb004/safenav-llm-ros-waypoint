"""Phase 8: sanity checks for the e2e150 command table in scripts/run_trials.py, independent
of ROS (no rclpy import at module scope in run_trials.py beyond what's needed to build the
command list, so this runs under plain pytest like the other test/python/ modules)."""

import importlib.util
import os
import sys

import pytest

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "run_trials.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("run_trials", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_trials"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run_trials():
    return _load_module()


def test_build_commands_returns_fifty_unique_rows(run_trials):
    rows = run_trials.build_commands()
    assert len(rows) == 50
    commands = [r["command"] for r in rows]
    assert len(set(commands)) == 50


def test_build_commands_covers_ten_rooms_five_categories(run_trials):
    rows = run_trials.build_commands()
    rooms = {r["room"] for r in rows}
    categories = {r["category"] for r in rows}
    assert rooms == set(run_trials.ROOMS)
    assert categories == {"direct", "alias", "negation", "abbreviation", "spatial"}
    for room in run_trials.ROOMS:
        room_categories = {r["category"] for r in rows if r["room"] == room}
        assert room_categories == categories


def test_spatial_anchors_resolve_to_corrected_labels(run_trials):
    """PLAN.md 11A.1: the relabel rule is relations.resolve_relation(), the resolver's own
    traversal direction, not AnnotationGraph.related_rooms() (D57 finding 3: that function is
    the wrong direction for "the room <relation> the anchor" queries)."""
    graph = run_trials.AnnotationGraph.from_file(run_trials.ANNOTATIONS_PATH)
    for room, (anchor, relation) in run_trials.SPATIAL_ANCHORS.items():
        command = run_trials._spatial_phrase(anchor, relation)
        target, _ = run_trials.resolve_relation(graph, anchor, relation, command)
        corrected = target or "none"
        assert corrected == run_trials.CORRECTED_SPATIAL_LABELS[room], (
            f"({anchor}, {relation}) now resolves to {corrected!r}, not "
            f"{run_trials.CORRECTED_SPATIAL_LABELS[room]!r}; the graph has drifted since the "
            "11A.1 relabel was authored"
        )


def test_corrected_spatial_labels_against_hand_read_edges(run_trials):
    """Independent check (11A.1): the answer read off room_annotations.json's edge direction
    by hand, for the six left_of/right_of phrasings, computed without calling either
    AnnotationGraph.related_rooms() or relations.resolve_relation(). An edge
    {"from": A, "to": B, "relation": "left_of"} means A is left_of B, i.e. B is to the right
    of A; "the room to the right of the kitchen" is therefore whatever the kitchen is left_of.
    The four near phrasings are symmetric and are not re-checked here."""
    with open(run_trials.ANNOTATIONS_PATH, "r", encoding="utf-8") as f:
        import json
        edges = json.load(f)["edges"]

    def room_the_anchor_is_left_of(anchor):
        matches = [e["to"] for e in edges if e["from"] == anchor and e["relation"] == "left_of"]
        assert len(matches) <= 1
        return matches[0] if matches else None

    def room_left_of_the_anchor(anchor):
        matches = [e["from"] for e in edges if e["to"] == anchor and e["relation"] == "left_of"]
        assert len(matches) <= 1
        return matches[0] if matches else None

    hand_read = {
        # room: (anchor, relation) -> "the room to the {left,right} of the anchor"
        "reception": room_the_anchor_is_left_of("kitchen"),  # right_of kitchen
        "kitchen": room_the_anchor_is_left_of("meeting_room_a"),  # right_of meeting_room_a
        "meeting_room_a": room_the_anchor_is_left_of("meeting_room_b"),  # right_of meeting_room_b
        "meeting_room_b": room_the_anchor_is_left_of("office"),  # right_of office, no such edge
        "server_room": room_the_anchor_is_left_of("charging_dock"),  # right_of charging_dock
        "workshop": room_left_of_the_anchor("lab"),  # left_of lab
    }
    for room, answer in hand_read.items():
        expected = answer or "none"
        assert expected == run_trials.CORRECTED_SPATIAL_LABELS[room], (
            f"hand-read answer for {room!r} is {expected!r}, table says "
            f"{run_trials.CORRECTED_SPATIAL_LABELS[room]!r}"
        )
