#!/usr/bin/env python3
"""ros2 run semantic_waypoint_planner say.py "go to the kitchen"

Publishes a SemanticGoal on /semantic_goal and waits for the matching /semantic_goal_result
(matched by command text), printing it as JSON. Used for the Phase 6 DoD manual checks and by
any operator driving the stack interactively.
"""

import argparse
import json
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from semantic_waypoint_planner.msg import SemanticGoal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--confidence-threshold", type=float, default=0.85)
    parser.add_argument("--timeout", type=float, default=310.0)
    args = parser.parse_args()

    rclpy.init()
    node = Node("say")
    goal_pub = node.create_publisher(SemanticGoal, "/semantic_goal", 1)

    results = []
    node.create_subscription(String, "/semantic_goal_result", lambda msg: results.append(msg.data), 10)

    # Let discovery settle: /semantic_goal_result is reliable/volatile, not latched, so a result
    # published before this subscription has matched the long-lived semantic_goal_node publisher
    # would be lost.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        if node.count_subscribers("/semantic_goal") > 0 and node.count_publishers(
                "/semantic_goal_result") > 0:
            break
    time.sleep(0.5)

    goal = SemanticGoal()
    goal.command = args.command
    goal.confidence_threshold = args.confidence_threshold
    goal_pub.publish(goal)

    deadline = time.monotonic() + args.timeout
    result = None
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        for raw in results:
            parsed = json.loads(raw)
            if parsed.get("command") == args.command:
                result = parsed
                break
        if result is not None:
            break

    node.destroy_node()
    rclpy.shutdown()

    if result is None:
        print(json.dumps({"command": args.command, "error": "no result received"}))
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result.get("nav_result") == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
