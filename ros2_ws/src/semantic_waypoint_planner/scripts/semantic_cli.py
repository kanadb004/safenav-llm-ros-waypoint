#!/usr/bin/env python3
"""``ros2 run semantic_waypoint_planner semantic_cli "go to the kitchen"``: calls
``/resolve_waypoint`` and prints the full response as JSON, for manual checks."""

import argparse
import json
import sys

import rclpy
from rclpy.node import Node

from semantic_waypoint_planner.srv import ResolveWaypoint


def response_to_dict(resp) -> dict:
    return {
        "matched_room_name": resp.matched_room_name,
        "raw_confidence": resp.raw_confidence,
        "calibrated_confidence": resp.calibrated_confidence,
        "reasoning": resp.reasoning,
        "success": resp.success,
        "token_entropy": resp.token_entropy,
        "inference_ms": resp.inference_ms,
        "resolver_mode": resp.resolver_mode,
        "out_of_graph": resp.out_of_graph,
        "calibrator_loaded": resp.calibrator_loaded,
        "top_k_rooms": list(resp.top_k_rooms),
        "top_k_scores": list(resp.top_k_scores),
        "resolved_pose": {
            "frame_id": resp.resolved_pose.header.frame_id,
            "x": resp.resolved_pose.pose.position.x,
            "y": resp.resolved_pose.pose.position.y,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="natural language navigation command")
    parser.add_argument("--candidates", nargs="*", default=[])
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args(argv)

    rclpy.init()
    node = Node("semantic_cli")
    client = node.create_client(ResolveWaypoint, "/resolve_waypoint")
    if not client.wait_for_service(timeout_sec=10.0):
        print("error: /resolve_waypoint service not available", file=sys.stderr)
        rclpy.shutdown()
        sys.exit(1)

    request = ResolveWaypoint.Request()
    request.natural_language_command = args.command
    request.candidate_room_names = args.candidates

    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=args.timeout)

    if future.result() is None:
        print("error: no response (timeout)", file=sys.stderr)
        rclpy.shutdown()
        sys.exit(1)

    print(json.dumps(response_to_dict(future.result()), indent=2))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
