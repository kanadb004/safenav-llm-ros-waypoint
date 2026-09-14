#!/usr/bin/env python3
"""ros2 run safenav_sim goto --room kitchen

Looks up the room's pose with /get_room_pose and sends it to Nav2 with
nav2_simple_commander, printing the result and elapsed time.
"""

import argparse
import time

import rclpy
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.node import Node
from semantic_waypoint_planner.srv import GetRoomPose


def get_room_pose(node: Node, room: str):
    client = node.create_client(GetRoomPose, "/get_room_pose")
    if not client.wait_for_service(timeout_sec=10.0):
        raise RuntimeError("/get_room_pose service not available")
    req = GetRoomPose.Request()
    req.name = room
    future = client.call_async(req)
    rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
    resp = future.result()
    if resp is None or not resp.found:
        raise RuntimeError(f"room '{room}' not found")
    return resp.pose


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", required=True)
    args = parser.parse_args()

    rclpy.init()
    lookup_node = Node("goto_lookup")
    pose = get_room_pose(lookup_node, args.room)
    lookup_node.destroy_node()

    navigator = BasicNavigator()
    navigator.waitUntilNav2Active(localizer='bt_navigator')

    start = time.monotonic()
    navigator.goToPose(pose)
    while not navigator.isTaskComplete():
        time.sleep(0.1)
    elapsed = time.monotonic() - start

    result = navigator.getResult()
    succeeded = result == TaskResult.SUCCEEDED
    print(f"room={args.room} result={result} succeeded={succeeded} elapsed_s={elapsed:.2f}")

    rclpy.shutdown()
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
