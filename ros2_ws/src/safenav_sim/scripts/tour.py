#!/usr/bin/env python3
"""ros2 run safenav_sim tour [--sim-mode gazebo|loopback] [--output PATH.jsonl]

Sends NavigateToPose to all 10 room docking poses in sequence via nav2_simple_commander
and appends one JSON line per attempt with the outcome and elapsed time.
"""

import argparse
import json
import time
from datetime import datetime, timezone

import rclpy
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.node import Node
from semantic_waypoint_planner.srv import GetRoomPose

# A "snake" order along the corridor (top row left to right, cross over, bottom row right
# to left) so consecutive goals are always adjacent rooms, minimizing total travel distance
# for the 5 minute loopback DoD target.
ROOMS = [
    "reception", "kitchen", "meeting_room_a", "meeting_room_b", "office",
    "workshop", "lab", "storage_room", "charging_dock", "server_room",
]


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
    parser.add_argument("--sim-mode", default="unknown", choices=["gazebo", "loopback", "unknown"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rclpy.init()
    lookup_node = Node("tour_lookup")
    navigator = BasicNavigator()
    navigator.waitUntilNav2Active(localizer='bt_navigator')

    n_reached = 0
    with open(args.output, "a") as f:
        for room in ROOMS:
            pose = get_room_pose(lookup_node, room)
            start = time.monotonic()
            navigator.goToPose(pose)
            while not navigator.isTaskComplete():
                time.sleep(0.1)
            elapsed = time.monotonic() - start
            result = navigator.getResult()
            succeeded = result == TaskResult.SUCCEEDED
            n_reached += int(succeeded)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sim_mode": args.sim_mode,
                "room": room,
                "pose_x": pose.pose.position.x,
                "pose_y": pose.pose.position.y,
                "result": str(result),
                "reached": succeeded,
                "elapsed_s": elapsed,
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            print(f"{room}: {result} in {elapsed:.2f}s")

    lookup_node.destroy_node()
    rclpy.shutdown()
    print(f"tour complete: {n_reached}/{len(ROOMS)} reached, logged to {args.output}")
    return 0 if n_reached == len(ROOMS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
