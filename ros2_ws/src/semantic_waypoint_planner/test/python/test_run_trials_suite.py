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


def test_spatial_anchors_resolve_uniquely_against_committed_graph(run_trials):
    graph = run_trials.AnnotationGraph.from_file(run_trials.ANNOTATIONS_PATH)
    for room, (anchor, relation) in run_trials.SPATIAL_ANCHORS.items():
        assert graph.related_rooms(anchor, relation) == [room], (
            f"({anchor}, {relation}) no longer resolves uniquely to {room}; "
            "the graph has drifted since the e2e150 suite was authored"
        )
