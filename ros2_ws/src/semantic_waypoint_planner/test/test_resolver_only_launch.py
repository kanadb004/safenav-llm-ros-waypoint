"""Launch test: starts annotation_map_node plus llm_resolver_node_py against a small fixture
graph and calls /resolve_waypoint for five commands (PLAN.md Phase 3 DoD). Loads the real GGUF
model, so this is slower than the other launch tests; run with `colcon test`.
"""

import json
import os
import tempfile
import unittest

import launch
import launch_ros.actions
import launch_testing
import launch_testing.actions
import rclpy
from rclpy.node import Node

from semantic_waypoint_planner.srv import ResolveWaypoint

FIXTURE_DOC = {
    "version": 1,
    "facility": "test_facility",
    "frame": "map",
    "rooms": [
        {
            "name": "kitchen",
            "aliases": ["break room"],
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0, "frame": "map"},
            "tags": [],
            "parent": "",
        },
        {
            "name": "charging_dock",
            "aliases": ["dock", "charging station"],
            "pose": {"x": 1.0, "y": 1.0, "theta": 0.0, "frame": "map"},
            "tags": [],
            "parent": "",
        },
        {
            "name": "office",
            "aliases": ["workspace"],
            "pose": {"x": 2.0, "y": 2.0, "theta": 0.0, "frame": "map"},
            "tags": [],
            "parent": "",
        },
    ],
    "edges": [],
}


def _write_fixture_file() -> str:
    fd, path = tempfile.mkstemp(prefix="fixture_annotations_", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(FIXTURE_DOC, f)
    return path


FIXTURE_PATH = _write_fixture_file()


def generate_test_description():
    annotation_node = launch_ros.actions.Node(
        package="semantic_waypoint_planner",
        executable="annotation_map_node",
        name="annotation_map_node",
        parameters=[{"annotations_path": FIXTURE_PATH}],
        output="screen",
    )
    resolver_node = launch_ros.actions.Node(
        package="semantic_waypoint_planner",
        executable="llm_resolver.py",
        name="llm_resolver_node_py",
        parameters=[{
            "annotations_path": FIXTURE_PATH,
            "timeout_ms": 90000,
            "n_threads": 8,
            "fewshot_count": 0,
        }],
        output="screen",
    )
    return launch.LaunchDescription([
        annotation_node,
        resolver_node,
        launch_testing.actions.ReadyToTest(),
    ]), {"annotation_node": annotation_node, "resolver_node": resolver_node}


class TestResolverService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = Node("test_client")

    def tearDown(self):
        self.node.destroy_node()

    def _resolve(self, command, timeout=100.0):
        client = self.node.create_client(ResolveWaypoint, "/resolve_waypoint")
        self.assertTrue(
            client.wait_for_service(timeout_sec=timeout), "/resolve_waypoint did not come up"
        )
        request = ResolveWaypoint.Request()
        request.natural_language_command = command
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=timeout)
        self.assertTrue(future.done(), f"resolve_waypoint timed out for {command!r}")
        return future.result()

    def test_five_commands(self):
        known = {"kitchen", "charging_dock", "office", "none"}
        cases = [
            "kitchen",
            "go to the office",
            "somewhere I can charge the robot",
            "go to the cafeteria",
            "please navigate to the break room",
        ]
        for command in cases:
            resp = self._resolve(command)
            self.assertIn(resp.matched_room_name, known, command)
            self.assertGreaterEqual(resp.inference_ms, 0.0, command)
            self.assertIn(resp.resolver_mode, ("fast_path", "llm_grammar", "llm_free"), command)


@launch_testing.post_shutdown_test()
class TestNodeShutdown(unittest.TestCase):
    def test_exit_code(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info)
        if os.path.exists(FIXTURE_PATH):
            os.remove(FIXTURE_PATH)
