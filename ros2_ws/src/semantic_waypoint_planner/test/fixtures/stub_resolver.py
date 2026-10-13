#!/usr/bin/env python3
"""Test fixture only: a deterministic stand-in for annotation_map_node + llm_resolver_node_py,
so the Phase 6 launch test can exercise SemanticNavigateToPose and semantic_goal_node without
loading the real GGUF model or standing up the full Nav2 stack. Not installed, not used outside
test/test_semantic_nav_launch.py.
"""

import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node

from semantic_waypoint_planner.srv import ListRooms, ResolveWaypoint

KNOWN_ROOMS = ["kitchen"]


class StubResolver(Node):
    def __init__(self):
        super().__init__("stub_resolver")
        self.create_service(ListRooms, "/list_rooms", self._list_rooms)
        self.create_service(ResolveWaypoint, "/resolve_waypoint", self._resolve_waypoint)

    def _list_rooms(self, request, response):
        response.canonical_names = KNOWN_ROOMS
        response.all_aliases = ["break room"]
        return response

    def _resolve_waypoint(self, request, response):
        command = request.natural_language_command
        if command == "go to the kitchen":
            response.success = True
            response.matched_room_name = "kitchen"
            response.raw_confidence = 0.95
            response.calibrated_confidence = 0.95
            response.resolver_mode = "fast_path"
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.orientation.w = 1.0
            response.resolved_pose = pose
        elif command == "go to the cafeteria":
            response.success = False
            response.matched_room_name = "none"
            response.raw_confidence = 0.0
            response.calibrated_confidence = 0.0
            response.resolver_mode = "llm_grammar"
        elif command == "slow command":
            time.sleep(2.0)
            response.success = True
            response.matched_room_name = "kitchen"
            response.raw_confidence = 0.95
            response.calibrated_confidence = 0.95
            response.resolver_mode = "fast_path"
        else:
            response.success = False
            response.matched_room_name = "none"
        response.reasoning = "stub"
        return response


def main():
    rclpy.init()
    node = StubResolver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
