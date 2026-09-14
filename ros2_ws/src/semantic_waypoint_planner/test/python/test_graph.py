"""Host pytest for the ROS free annotation graph core (no ROS imports required)."""

import copy
import json
import math
import os
import sys

import pytest

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from semantic_waypoint_planner.graph import (  # noqa: E402
    AnnotationGraph,
    GraphValidationError,
    Room,
    validate,
)

MAP_PATH = os.path.join(_PKG_ROOT, "maps", "room_annotations.json")


@pytest.fixture()
def base_data():
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_shipped_map_is_valid(base_data):
    validate(base_data)
    graph = AnnotationGraph.from_dict(base_data)
    assert len(graph.canonical_names) == 30
    assert len(set(graph.canonical_names)) == 30


def test_alias_and_canonical_lookup(base_data):
    graph = AnnotationGraph.from_dict(base_data)
    assert graph.resolve_alias("charging_dock") == "charging_dock"
    assert graph.resolve_alias("dock") == "charging_dock"
    assert graph.resolve_alias("docking bay") == "storage_room"
    assert graph.resolve_alias("not_a_real_place") is None


def test_get_room(base_data):
    graph = AnnotationGraph.from_dict(base_data)
    room = graph.get_room("charging_dock")
    assert room is not None
    assert room.pose["x"] == pytest.approx(6.0)
    assert graph.get_room("nonexistent") is None


def test_adjacency_text(base_data):
    graph = AnnotationGraph.from_dict(base_data)
    text = graph.adjacency_text("charging_dock")
    assert "charging_dock" in text
    assert "storage_room" in text or "server_room" in text


def test_duplicate_name_rejected(base_data):
    data = copy.deepcopy(base_data)
    data["rooms"].append(dict(data["rooms"][0]))
    with pytest.raises(GraphValidationError):
        validate(data)


def test_duplicate_alias_rejected(base_data):
    data = copy.deepcopy(base_data)
    data["rooms"][1]["aliases"] = list(data["rooms"][1]["aliases"]) + [data["rooms"][0]["aliases"][0]]
    with pytest.raises(GraphValidationError):
        validate(data)


def test_alias_colliding_with_name_rejected(base_data):
    data = copy.deepcopy(base_data)
    data["rooms"][1]["aliases"] = list(data["rooms"][1]["aliases"]) + [data["rooms"][0]["name"]]
    with pytest.raises(GraphValidationError):
        validate(data)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_pose_rejected(base_data, bad_value):
    data = copy.deepcopy(base_data)
    data["rooms"][0]["pose"]["x"] = bad_value
    with pytest.raises(GraphValidationError):
        validate(data)


def test_non_finite_pose_json_roundtrip_rejected(base_data):
    # NaN/Infinity are not valid JSON tokens under strict parsing; simulate a bad value
    # arriving as a non-numeric type instead (e.g. a string written by a buggy client).
    data = copy.deepcopy(base_data)
    data["rooms"][0]["pose"]["theta"] = "not-a-number"
    with pytest.raises(GraphValidationError):
        validate(data)


def test_unknown_edge_endpoint_rejected(base_data):
    data = copy.deepcopy(base_data)
    data["edges"].append({"from": "charging_dock", "to": "nonexistent_room", "relation": "near"})
    with pytest.raises(GraphValidationError):
        validate(data)


def test_bad_name_format_rejected(base_data):
    data = copy.deepcopy(base_data)
    data["rooms"][0]["name"] = "Not Snake Case"
    with pytest.raises(GraphValidationError):
        validate(data)


def test_add_room_success_and_duplicate(base_data):
    graph = AnnotationGraph.from_dict(base_data)
    new_room = Room(
        name="new_room",
        aliases=["a new place"],
        pose={"x": 0.0, "y": 0.0, "theta": 0.0, "frame": "map"},
        tags=["test"],
        parent="lab_floor_1",
    )
    graph.add_room(new_room)
    assert "new_room" in graph.canonical_names
    assert len(graph.canonical_names) == 31
    assert graph.resolve_alias("a new place") == "new_room"

    with pytest.raises(GraphValidationError):
        graph.add_room(new_room)


def test_save_atomic_roundtrip(base_data, tmp_path):
    graph = AnnotationGraph.from_dict(base_data)
    out_path = str(tmp_path / "annotations.json")
    graph.save(out_path)
    reloaded = AnnotationGraph.from_file(out_path)
    assert reloaded.canonical_names == graph.canonical_names
    # no leftover temp files
    leftovers = [p for p in os.listdir(tmp_path) if p != "annotations.json"]
    assert leftovers == []
