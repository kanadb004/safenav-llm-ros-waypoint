"""Host pytest for annotate_map.py --from-yaml (no ROS imports required)."""

import json
import os
import sys

import pytest
import yaml

_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_DIR = os.path.join(_PKG_ROOT, "scripts")
for p in (_PKG_ROOT, _SCRIPTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from annotate_map import import_from_yaml  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph, GraphValidationError  # noqa: E402

BASE_DOC = {
    "version": 1,
    "facility": "test_facility",
    "frame": "map",
    "rooms": [
        {
            "name": "existing_room",
            "aliases": ["old alias"],
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0, "frame": "map"},
            "tags": [],
            "parent": "floor_1",
        }
    ],
    "edges": [],
}


@pytest.fixture()
def annotations_file(tmp_path):
    path = tmp_path / "room_annotations.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(BASE_DOC, f)
    return str(path)


def _write_yaml(tmp_path, locations):
    path = tmp_path / "layout.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"locations": locations}, f)
    return str(path)


def test_from_yaml_adds_new_room(tmp_path, annotations_file):
    layout = _write_yaml(
        tmp_path,
        [
            {"name": "existing_room", "x": 0.0, "y": 0.0, "theta": 0.0},
            {
                "name": "new_room",
                "x": 5.0,
                "y": 6.0,
                "theta": 1.57,
                "aliases": ["fresh room"],
                "tags": ["new"],
                "parent": "floor_1",
            },
        ],
    )
    graph = import_from_yaml(layout, annotations_file)
    assert set(graph.canonical_names) == {"existing_room", "new_room"}
    new_room = graph.get_room("new_room")
    assert new_room.pose["x"] == pytest.approx(5.0)
    assert graph.resolve_alias("fresh room") == "new_room"


def test_from_yaml_updates_existing_pose_without_touching_aliases(tmp_path, annotations_file):
    layout = _write_yaml(tmp_path, [{"name": "existing_room", "x": 9.0, "y": 9.0, "theta": 3.14}])
    graph = import_from_yaml(layout, annotations_file)
    room = graph.get_room("existing_room")
    assert room.pose["x"] == pytest.approx(9.0)
    assert room.pose["y"] == pytest.approx(9.0)
    # aliases are untouched for rooms that already existed
    assert room.aliases == ["old alias"]


def test_from_yaml_result_is_persisted(tmp_path, annotations_file):
    layout = _write_yaml(tmp_path, [{"name": "existing_room", "x": 1.0, "y": 1.0, "theta": 0.0}])
    import_from_yaml(layout, annotations_file)
    reloaded = AnnotationGraph.from_file(annotations_file)
    assert reloaded.get_room("existing_room").pose["x"] == pytest.approx(1.0)


def test_from_yaml_empty_locations_raises(tmp_path, annotations_file):
    layout = _write_yaml(tmp_path, [])
    with pytest.raises(GraphValidationError):
        import_from_yaml(layout, annotations_file)


def test_from_yaml_invalid_new_room_raises(tmp_path, annotations_file):
    layout = _write_yaml(tmp_path, [{"name": "Bad Name", "x": 0.0, "y": 0.0, "theta": 0.0}])
    with pytest.raises(GraphValidationError):
        import_from_yaml(layout, annotations_file)
