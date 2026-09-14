#!/usr/bin/env python3
"""Interactive and batch annotation tool for room_annotations.json.

Two modes:

- Default (RViz): subscribes to `/initialpose` and `/clicked_point`, prompts on the terminal
  for a canonical name, aliases, tags and parent, then adds the room through the running
  `/add_room` service if `annotation_map_node` is up, or writes the annotations file directly
  otherwise.
- `--from-yaml LAYOUT.yaml`: imports named location poses from a `safenav_sim` layout YAML
  (`locations: [{name, x, y, theta, aliases, tags, parent}, ...]`) without needing RViz, so the
  simulation annotation graph is reproducible from the world definition. New names are added,
  poses of existing names are overwritten to match the layout; aliases/tags/parent are only
  filled in for names that are new to the annotations file.
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import List

import yaml

from semantic_waypoint_planner.graph import AnnotationGraph, GraphValidationError, Room


def import_from_yaml(layout_path: str, annotations_path: str) -> AnnotationGraph:
    """Deterministically sync room poses in ``annotations_path`` from a layout YAML file.

    Returns the resulting graph (already saved to ``annotations_path``). Raises
    GraphValidationError if the result would be invalid.
    """
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = yaml.safe_load(f) or {}
    locations = layout.get("locations", [])
    if not locations:
        raise GraphValidationError(f"'{layout_path}' has no 'locations' entries")

    graph = AnnotationGraph.from_file(annotations_path)

    for loc in locations:
        name = loc["name"]
        pose = {"x": float(loc["x"]), "y": float(loc["y"]), "theta": float(loc["theta"]), "frame": "map"}
        existing = graph.get_room(name)
        if existing is not None:
            existing.pose = pose
        else:
            room = Room(
                name=name,
                aliases=list(loc.get("aliases", [])),
                pose=pose,
                tags=list(loc.get("tags", [])),
                parent=loc.get("parent", ""),
            )
            graph.add_room(room)

    graph.save(annotations_path)
    return graph


def _prompt_list(label: str) -> List[str]:
    raw = input(f"{label} (comma separated, blank for none): ").strip()
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _run_interactive(annotations_path: str) -> None:
    import rclpy
    from geometry_msgs.msg import PointStamped, PoseWithCovarianceStamped
    from rclpy.node import Node

    from semantic_waypoint_planner.srv import AddRoom

    class AnnotatorNode(Node):
        def __init__(self) -> None:
            super().__init__("annotate_map")
            self.annotations_path = annotations_path
            self.add_room_client = self.create_client(AddRoom, "/add_room")
            self.create_subscription(
                PoseWithCovarianceStamped, "/initialpose", self._on_pose, 10
            )
            self.create_subscription(PointStamped, "/clicked_point", self._on_point, 10)
            self.get_logger().info(
                "waiting for /initialpose (2D Pose Estimate) or /clicked_point (Publish Point) in RViz"
            )

        def _on_pose(self, msg: "PoseWithCovarianceStamped") -> None:
            q = msg.pose.pose.orientation
            theta = 2.0 * math.atan2(q.z, q.w)
            self._prompt_and_add(msg.pose.pose.position.x, msg.pose.pose.position.y, theta)

        def _on_point(self, msg: "PointStamped") -> None:
            self._prompt_and_add(msg.point.x, msg.point.y, 0.0)

        def _prompt_and_add(self, x: float, y: float, theta: float) -> None:
            print(f"\nGot a point at x={x:.2f}, y={y:.2f}, theta={theta:.2f}")
            name = input("canonical name (lowercase_snake_case): ").strip().lower()
            if not name:
                print("empty name, skipping")
                return
            aliases = _prompt_list("aliases")
            tags = _prompt_list("tags")
            parent = input("parent (blank for none): ").strip()

            if self.add_room_client.wait_for_service(timeout_sec=1.0):
                req = AddRoom.Request()
                req.name = name
                req.aliases = aliases
                req.pose.position.x = x
                req.pose.position.y = y
                req.pose.orientation.z = math.sin(theta / 2.0)
                req.pose.orientation.w = math.cos(theta / 2.0)
                req.tags = tags
                req.parent = parent
                future = self.add_room_client.call_async(req)
                rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
                if future.done() and future.result().success:
                    print(f"added '{name}' via /add_room")
                else:
                    print(f"failed to add '{name}': {future.result().message if future.done() else 'timeout'}")
            else:
                graph = AnnotationGraph.from_file(self.annotations_path)
                try:
                    graph.add_room(
                        Room(
                            name=name,
                            aliases=aliases,
                            pose={"x": x, "y": y, "theta": theta, "frame": "map"},
                            tags=tags,
                            parent=parent,
                        )
                    )
                    graph.save(self.annotations_path)
                    print(f"added '{name}' directly to {self.annotations_path}")
                except GraphValidationError as e:
                    print(f"could not add '{name}': {e}")

    rclpy.init()
    node = AnnotatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--annotations-path", default="maps/room_annotations.json",
        help="room_annotations.json to read/write",
    )
    parser.add_argument(
        "--from-yaml", metavar="LAYOUT_YAML", default=None,
        help="import poses from a safenav_sim layout.yaml instead of running interactively",
    )
    args = parser.parse_args(argv)

    if args.from_yaml:
        try:
            graph = import_from_yaml(args.from_yaml, args.annotations_path)
        except (GraphValidationError, FileNotFoundError, KeyError) as e:
            print(f"import failed: {e}", file=sys.stderr)
            return 1
        print(f"synced {len(graph.canonical_names)} rooms into {args.annotations_path}")
        return 0

    _run_interactive(args.annotations_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
