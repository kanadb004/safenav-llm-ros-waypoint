import json
import math
import os

import pytest
import yaml

PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SWP_MAPS = os.path.abspath(os.path.join(
    PKG_ROOT, "..", "semantic_waypoint_planner", "maps", "room_annotations.json"))

import sys  # noqa: E402
sys.path.insert(0, PKG_ROOT)
from safenav_sim.layout_geom import load_layout, wall_segments  # noqa: E402


@pytest.fixture
def layout():
    return load_layout(os.path.join(PKG_ROOT, "worlds", "layout.yaml"))


def test_layout_has_ten_rooms_and_thirty_locations(layout):
    assert len(layout["rooms"]) == 10
    assert len(layout["locations"]) == 30
    names = [loc["name"] for loc in layout["locations"]]
    assert len(names) == len(set(names)), "duplicate location name in layout.yaml"


def test_room_names_match_locations(layout):
    room_names = {r["name"] for r in layout["rooms"]}
    location_names = {loc["name"] for loc in layout["locations"]}
    assert room_names <= location_names


def test_wall_segments_have_door_gaps_into_corridor(layout):
    segments = wall_segments(layout)
    corridor = layout["corridor"]
    door_width = layout["door_width"]

    for boundary_y in (corridor["y_min"], corridor["y_max"]):
        on_boundary = [s for s in segments if abs(s.y1 - boundary_y) < 1e-6 and abs(s.y2 - boundary_y) < 1e-6]
        total_length = sum(abs(s.x2 - s.x1) for s in on_boundary)
        full_length = corridor["x_max"] - corridor["x_min"]
        n_rooms_on_this_wall = 5
        expected_gap_total = n_rooms_on_this_wall * door_width
        assert total_length == pytest.approx(full_length - expected_gap_total, abs=1e-6)


def test_no_zero_length_segments(layout):
    for s in wall_segments(layout):
        length = math.hypot(s.x2 - s.x1, s.y2 - s.y1)
        assert length > 1e-6


def test_room_annotations_poses_match_layout():
    with open(os.path.join(PKG_ROOT, "worlds", "layout.yaml")) as f:
        layout = yaml.safe_load(f)
    with open(SWP_MAPS) as f:
        annotations = json.load(f)

    layout_poses = {loc["name"]: (loc["x"], loc["y"], loc["theta"]) for loc in layout["locations"]}
    annotation_poses = {
        r["name"]: (r["pose"]["x"], r["pose"]["y"], r["pose"]["theta"]) for r in annotations["rooms"]
    }

    assert set(layout_poses) == set(annotation_poses)
    for name, pose in layout_poses.items():
        assert annotation_poses[name] == pytest.approx(pose, abs=1e-9), name
