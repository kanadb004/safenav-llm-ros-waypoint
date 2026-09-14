"""Launch test: starts annotation_map_node against a fixture JSON and calls all three services.

Run with `colcon test --packages-select semantic_waypoint_planner`.
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

from semantic_waypoint_planner.srv import AddRoom, GetRoomPose, ListRooms

FIXTURE_DOC = {
    "version": 1,
    "facility": "test_facility",
    "frame": "map",
    "rooms": [
        {
            "name": "fixture_room_a",
            "aliases": ["room alpha"],
            "pose": {"x": 1.0, "y": 2.0, "theta": 0.0, "frame": "map"},
            "tags": ["test"],
            "parent": "floor_1",
        },
        {
            "name": "fixture_room_b",
            "aliases": ["room beta"],
            "pose": {"x": 3.0, "y": 4.0, "theta": 1.57, "frame": "map"},
            "tags": [],
            "parent": "floor_1",
        },
    ],
    "edges": [{"from": "fixture_room_a", "to": "fixture_room_b", "relation": "adjacent"}],
}


def _write_fixture_file() -> str:
    fd, path = tempfile.mkstemp(prefix="fixture_annotations_", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(FIXTURE_DOC, f)
    return path


FIXTURE_PATH = _write_fixture_file()


def generate_test_description():
    node = launch_ros.actions.Node(
        package="semantic_waypoint_planner",
        executable="annotation_map_node",
        name="annotation_map_node",
        parameters=[{"annotations_path": FIXTURE_PATH}],
        output="screen",
    )
    return launch.LaunchDescription([
        node,
        launch_testing.actions.ReadyToTest(),
    ]), {"annotation_map_node": node}


class TestAnnotationMapNodeServices(unittest.TestCase):
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

    def _call(self, client_type, service_name, request, timeout=10.0):
        client = self.node.create_client(client_type, service_name)
        self.assertTrue(
            client.wait_for_service(timeout_sec=timeout),
            f"{service_name} did not become available",
        )
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=timeout)
        self.assertTrue(future.done(), f"{service_name} call timed out")
        return future.result()

    def test_list_rooms_returns_fixture_rooms(self):
        # Tests share one running node instance in unittest's alphabetical order, so this only
        # asserts the fixture rooms are present, not that they are the only rooms (see
        # test_add_room_then_list_and_duplicate_rejected, which adds a third room).
        resp = self._call(ListRooms, "/list_rooms", ListRooms.Request())
        self.assertIn("fixture_room_a", resp.canonical_names)
        self.assertIn("fixture_room_b", resp.canonical_names)
        self.assertIn("room alpha", resp.all_aliases)
        self.assertIn("room beta", resp.all_aliases)

    def test_get_room_pose_found_and_not_found(self):
        req = GetRoomPose.Request()
        req.name = "fixture_room_a"
        resp = self._call(GetRoomPose, "/get_room_pose", req)
        self.assertTrue(resp.found)
        self.assertEqual(resp.pose.header.frame_id, "map")
        self.assertAlmostEqual(resp.pose.pose.position.x, 1.0)

        req_missing = GetRoomPose.Request()
        req_missing.name = "not_a_room"
        resp_missing = self._call(GetRoomPose, "/get_room_pose", req_missing)
        self.assertFalse(resp_missing.found)

    def test_add_room_then_list_and_duplicate_rejected(self):
        req = AddRoom.Request()
        req.name = "fixture_room_c"
        req.aliases = ["room gamma"]
        req.pose.position.x = 5.0
        req.pose.position.y = 6.0
        req.pose.orientation.w = 1.0
        req.tags = ["test"]
        req.parent = "floor_1"
        resp = self._call(AddRoom, "/add_room", req)
        self.assertTrue(resp.success)

        list_resp = self._call(ListRooms, "/list_rooms", ListRooms.Request())
        self.assertIn("fixture_room_c", list_resp.canonical_names)
        self.assertEqual(len(list_resp.canonical_names), 3)

        dup_resp = self._call(AddRoom, "/add_room", req)
        self.assertFalse(dup_resp.success)


@launch_testing.post_shutdown_test()
class TestNodeShutdown(unittest.TestCase):
    def test_exit_code(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info)
        if os.path.exists(FIXTURE_PATH):
            os.remove(FIXTURE_PATH)
