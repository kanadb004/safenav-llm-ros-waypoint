#!/usr/bin/env python3
"""Phase 8 e2e150 trial runner (PLAN.md section 11).

Unlike `ml/safenav_ml/run_trials.py` (Phase 7, D49: calls ResolverCore directly), this script
drives the real ROS graph: it publishes SemanticGoal on /semantic_goal exactly as say.py does,
waits for the matching /semantic_goal_result, and also listens to /clarification_request,
/semantic_resolution_result, /odom and /cmd_vel for the extra section 12.9 fields that
/semantic_goal_result alone does not carry (t_resolved, pose, reached_intended). It records one
row per trial to a JSONL file and, unless --no-bag is given, one mcap bag per invocation
covering /semantic_goal, /clarification_request, /cmd_vel, /odom, /tts_text.

The "e2e150" suite is 10 navigable rooms (the Phase 2 ten room tour) x 5 phrasing variants
(direct, alias, negation, abbreviation, spatial) x 3 trials = 150 commands. Each spatial
variant's (anchor, relation) pair was checked against AnnotationGraph.related_rooms() to return
exactly the intended room before being hardcoded here (see the module docstring on
SPATIAL_VARIANTS); the check is re-run at import time as a guard against the graph drifting.

Usage (inside the running stack, e.g. semantic_nav.launch.py already up):
    ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 \
        --out /ws/data/runs/e2e150_loopback.jsonl --grammar-on --gate-threshold 0.85
    ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 \
        --out /ws/data/runs/e2e150_grammar_off.jsonl --no-grammar-on --gate-threshold 0.85
    ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 \
        --out /ws/data/runs/e2e150_gate_off.jsonl --grammar-on --gate-threshold 0.0
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ament_index_python.packages import get_package_share_directory
from semantic_waypoint_planner.msg import ClarificationRequest, SemanticGoal
from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.resolver_core import min_edit_distance, normalize_command

ANNOTATIONS_PATH = os.path.join(
    get_package_share_directory("semantic_waypoint_planner"), "maps", "room_annotations.json")

ROOMS = [
    "reception", "kitchen", "meeting_room_a", "meeting_room_b", "office",
    "server_room", "charging_dock", "storage_room", "lab", "workshop",
]

ALIASES = {
    "reception": "front desk", "kitchen": "break room",
    "meeting_room_a": "conference room a", "meeting_room_b": "conference room b",
    "office": "office area", "server_room": "server closet",
    "charging_dock": "charging station", "storage_room": "storage",
    "lab": "laboratory", "workshop": "work room",
}

ABBREVIATIONS = {
    "reception": "recep", "kitchen": "kitch", "meeting_room_a": "meet rm A",
    "meeting_room_b": "meet rm B", "office": "ofc", "server_room": "server rm",
    "charging_dock": "charge dock", "storage_room": "storage rm", "lab": "the lab",
    "workshop": "shop",
}

NEGATIONS = {
    "reception": "I don't want the kitchen, take me to the front desk instead.",
    "kitchen": "Not the lobby, I want the break room.",
    "meeting_room_a": "I don't want meeting room b, take me to conference room a instead.",
    "meeting_room_b": "Not meeting room a, I want conference room b.",
    "office": "I don't want the lab, take me to the office instead.",
    "server_room": "Not the charging dock, take me to the data room.",
    "charging_dock": "I don't want the server room, take me to the charging station instead.",
    "storage_room": "Not the lab, take me to the storage area instead.",
    "lab": "I don't want the workshop, take me to the laboratory instead.",
    "workshop": "Not the lab, take me to the fabrication room instead.",
}

# (anchor, relation) -> intended room, derived from AnnotationGraph.related_rooms() so that each
# pair resolves to exactly this one room given the committed room_annotations.json edges.
SPATIAL_ANCHORS = {
    "reception": ("kitchen", "right_of"),
    "kitchen": ("meeting_room_a", "right_of"),
    "meeting_room_a": ("meeting_room_b", "right_of"),
    "meeting_room_b": ("office", "right_of"),
    "office": ("workshop", "near"),
    "server_room": ("charging_dock", "right_of"),
    "charging_dock": ("kitchen", "near"),
    "storage_room": ("meeting_room_a", "near"),
    "lab": ("meeting_room_b", "near"),
    "workshop": ("lab", "left_of"),
}


def _spatial_phrase(anchor: str, relation: str) -> str:
    anchor_text = anchor.replace("_", " ")
    if relation in ("left_of", "right_of"):
        side = "left" if relation == "left_of" else "right"
        return f"Go to the room to the {side} of the {anchor_text}."
    return f"Go to the room {relation} the {anchor_text}."


def build_commands() -> List[Dict[str, str]]:
    """One row per (room, category); e2e150 repeats each 3 times at call time."""
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    rows = []
    for room in ROOMS:
        anchor, relation = SPATIAL_ANCHORS[room]
        found = graph.related_rooms(anchor, relation)
        if found != [room]:
            raise RuntimeError(
                f"SPATIAL_ANCHORS[{room!r}] = ({anchor!r}, {relation!r}) resolves to {found!r} "
                f"against the current room_annotations.json, not [{room!r}] as hardcoded. "
                "The graph has drifted since this suite was authored; fix SPATIAL_ANCHORS."
            )
        room_text = room.replace("_", " ")
        rows.append({"room": room, "category": "direct", "command": f"Can you take me to {room_text}?"})
        rows.append({"room": room, "category": "alias", "command": f"Could you guide me to the {ALIASES[room]}?"})
        rows.append({"room": room, "category": "negation", "command": NEGATIONS[room]})
        rows.append({"room": room, "category": "abbreviation", "command": f"Head to {ABBREVIATIONS[room]}, please."})
        rows.append({"room": room, "category": "spatial", "command": _spatial_phrase(anchor, relation)})
    return rows


class TrialRunner(Node):
    def __init__(self, bag_topics: Optional[List[str]] = None):
        super().__init__("run_trials")
        self.goal_pub = self.create_publisher(SemanticGoal, "/semantic_goal", 1)
        self._results: Dict[str, dict] = {}
        self._clarifications: Dict[str, dict] = {}
        self._resolutions: Dict[str, dict] = {}
        self._last_odom = None
        self._first_cmd_vel_after: Dict[str, float] = {}
        self._awaiting_cmd_vel_since: Optional[float] = None
        self.create_subscription(String, "/semantic_goal_result", self._on_result, 10)
        self.create_subscription(ClarificationRequest, "/clarification_request", self._on_clarification, 10)
        self.create_subscription(String, "/semantic_resolution_result", self._on_resolution, 10)
        try:
            from nav_msgs.msg import Odometry
            from geometry_msgs.msg import Twist
            self.create_subscription(Odometry, "/odom", self._on_odom, 10)
            self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, 10)
        except ImportError:
            pass

    def _on_result(self, msg: String) -> None:
        parsed = json.loads(msg.data)
        self._results.setdefault(parsed["command"], []).append(parsed)

    def _on_clarification(self, msg: ClarificationRequest) -> None:
        self._clarifications[msg.command] = {"reason": msg.reason}

    def _on_resolution(self, msg: String) -> None:
        parsed = json.loads(msg.data)
        self._resolutions[parsed["command"]] = {"t_resolved": time.monotonic(), **parsed}

    def _on_odom(self, msg) -> None:
        p = msg.pose.pose.position
        self._last_odom = (p.x, p.y, time.monotonic())

    def _on_cmd_vel(self, msg) -> None:
        if self._awaiting_cmd_vel_since is not None:
            nonzero = abs(msg.linear.x) > 1e-6 or abs(msg.angular.z) > 1e-6
            if nonzero and "t_nav_start" not in self._first_cmd_vel_after:
                self._first_cmd_vel_after["t_nav_start"] = time.monotonic()

    def wait_ready(self) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            if self.count_subscribers("/semantic_goal") > 0 and self.count_publishers(
                    "/semantic_goal_result") > 0:
                break
        time.sleep(0.5)

    def run_one(self, command: str, confidence_threshold: float, timeout: float) -> dict:
        self._first_cmd_vel_after = {}
        self._awaiting_cmd_vel_since = time.monotonic()
        t_command = time.monotonic()
        goal = SemanticGoal()
        goal.command = command
        goal.confidence_threshold = confidence_threshold
        self.goal_pub.publish(goal)

        deadline = time.monotonic() + timeout
        result = None
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            pending = self._results.get(command)
            if pending:
                result = pending.pop(0)
                break
        t_done = time.monotonic()

        if result is None:
            return {"command": command, "error": "no result received", "e2e_ms": (t_done - t_command) * 1000.0}

        resolution = self._resolutions.pop(command, {})
        clarification = self._clarifications.pop(command, {})
        pose = self._last_odom
        row = dict(result)
        row["t_command_s"] = t_command
        row["t_resolved_s"] = resolution.get("t_resolved")
        row["t_nav_start_s"] = self._first_cmd_vel_after.get("t_nav_start")
        row["t_nav_end_s"] = t_done
        if row["t_resolved_s"] is not None:
            row["resolver_ms"] = (row["t_resolved_s"] - t_command) * 1000.0
        else:
            row["resolver_ms"] = None
        row["clarification_reason"] = clarification.get("reason", "")
        if pose is not None:
            row["pose_x"], row["pose_y"], _ = pose
        else:
            row["pose_x"], row["pose_y"] = None, None
        row["pose_theta"] = None
        self._awaiting_cmd_vel_since = None
        return row


def set_grammar_on(node: Node, value: bool) -> None:
    subprocess.run(
        ["ros2", "param", "set", "/llm_resolver_node_py", "grammar_on", "true" if value else "false"],
        check=True, capture_output=True,
    )


def start_bag(bag_path: str) -> Optional[subprocess.Popen]:
    topics = ["/semantic_goal", "/clarification_request", "/cmd_vel", "/odom", "/tts_text"]
    proc = subprocess.Popen(
        ["ros2", "bag", "record", "-o", bag_path, "--storage", "mcap", *topics],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    return proc


def stop_bag(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="e2e150", choices=["e2e150"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--gate-threshold", type=float, default=0.85)
    parser.add_argument("--timeout", type=float, default=310.0)
    grammar = parser.add_mutually_exclusive_group()
    grammar.add_argument("--grammar-on", dest="grammar_on", action="store_true", default=True)
    grammar.add_argument("--no-grammar-on", dest="grammar_on", action="store_false")
    parser.add_argument("--bag-dir", default="")
    parser.add_argument("--no-bag", action="store_true")
    parser.add_argument("--graph", default=ANNOTATIONS_PATH)
    args = parser.parse_args()

    base_commands = build_commands()
    graph = AnnotationGraph.from_file(args.graph)
    room_poses = {r.name: r.pose for r in graph.rooms}
    room_aliases = {r.name: r.aliases for r in graph.rooms}

    rclpy.init()
    node = TrialRunner()
    node.wait_ready()

    set_grammar_on(node, args.grammar_on)
    time.sleep(0.5)

    bag_proc = None
    if not args.no_bag:
        bag_dir = args.bag_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(args.out))), "bags",
            os.path.splitext(os.path.basename(args.out))[0] + "_" + uuid.uuid4().hex[:8])
        os.makedirs(os.path.dirname(bag_dir), exist_ok=True)
        bag_proc = start_bag(bag_dir)
        print(f"recording bag to {bag_dir}")

    out_of_graph_count = 0
    rows_written = 0
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            run_idx = 0
            for trial in range(args.trials):
                for entry in base_commands:
                    run_idx += 1
                    row = node.run_one(entry["command"], args.gate_threshold, args.timeout)
                    intended = entry["room"]
                    resolved = row.get("resolved_room") or row.get("attempted_room") or ""
                    command_norm = normalize_command(entry["command"])
                    edit_distance = min_edit_distance(resolved, room_aliases.get(resolved, []), command_norm)
                    pose = room_poses.get(intended, {})
                    reached = None
                    if row.get("pose_x") is not None and pose:
                        dx = row["pose_x"] - pose.get("x", 0.0)
                        dy = row["pose_y"] - pose.get("y", 0.0)
                        reached = (dx * dx + dy * dy) ** 0.5 < 0.5
                    out_of_graph = bool(row.get("out_of_graph", False))
                    if out_of_graph:
                        out_of_graph_count += 1
                    record = {
                        "run_id": f"e2e150-{trial}-{run_idx}",
                        "timestamp": time.time(),
                        "suite": args.suite,
                        "sim_mode": "loopback",
                        "command": entry["command"],
                        "category": entry["category"],
                        "intended_room": intended,
                        "resolved_room": row.get("resolved_room", ""),
                        "attempted_room": row.get("attempted_room", ""),
                        "raw_confidence": row.get("raw_confidence"),
                        "calibrated_confidence": row.get("calibrated_confidence"),
                        "token_entropy": row.get("token_entropy"),
                        "n_candidates": 30,
                        "command_length": len(entry["command"].strip()),
                        "edit_distance": edit_distance,
                        "resolver_mode": row.get("resolver_mode"),
                        "grammar_on": args.grammar_on,
                        "gate_threshold": args.gate_threshold,
                        "gate_passed": row.get("gate_passed"),
                        "bt_status": "SUCCESS" if row.get("gate_passed") else "FAILURE_FALLBACK",
                        "clarification_reason": row.get("clarification_reason", ""),
                        "nav_result": row.get("nav_result"),
                        "t_command": row.get("t_command_s"),
                        "t_resolved": row.get("t_resolved_s"),
                        "t_nav_start": row.get("t_nav_start_s"),
                        "t_nav_end": row.get("t_nav_end_s"),
                        "resolver_ms": row.get("resolver_ms"),
                        "e2e_ms": row.get("e2e_ms"),
                        "pose_x": row.get("pose_x"),
                        "pose_y": row.get("pose_y"),
                        "pose_theta": row.get("pose_theta"),
                        "reached_intended": reached,
                        "out_of_graph": out_of_graph,
                    }
                    fh.write(json.dumps(record) + "\n")
                    fh.flush()
                    rows_written += 1
                    print(f"[{rows_written}/{len(base_commands) * args.trials}] "
                          f"{entry['command']!r} -> {record['resolved_room']!r} "
                          f"(gate_passed={record['gate_passed']}, nav={record['nav_result']})")
    finally:
        stop_bag(bag_proc)
        node.destroy_node()
        rclpy.shutdown()

    print(f"wrote {rows_written} rows to {args.out}; out_of_graph_count={out_of_graph_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
