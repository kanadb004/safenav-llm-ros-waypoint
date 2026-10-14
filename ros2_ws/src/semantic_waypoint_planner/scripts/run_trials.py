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
variant's intended room is CORRECTED_SPATIAL_LABELS[room], frozen by PLAN.md 11A.1 from
relations.resolve_relation() (the resolver's own traversal direction), not the room key the
command text was built from; the check is re-run at import time as a guard against the graph
drifting. Commands are byte-identical to Phase 8 (D57): only the scored intended room changed.

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
from typing import Dict, List, Optional, Tuple

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ament_index_python.packages import get_package_share_directory
from semantic_waypoint_planner.msg import ClarificationRequest, SemanticGoal
from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.relations import resolve_relation
from semantic_waypoint_planner.resolver_core import min_edit_distance, normalize_command

ANNOTATIONS_PATH = os.path.join(
    get_package_share_directory("semantic_waypoint_planner"), "maps", "room_annotations.json")
MAP_YAML_PATH = os.path.join(
    get_package_share_directory("safenav_sim"), "maps", "safenav_lab.yaml")

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

# (anchor, relation) per spatial command, keyed by the room that built the command (commands
# stay byte-identical across the 8B relabel, PLAN.md 11A.1). This mapping is NOT the intended
# room for scoring; see CORRECTED_SPATIAL_LABELS below.
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

# PLAN.md 11A.1: the relabel rule, frozen before rescoring. For each spatial command, the
# intended room is whatever relations.resolve_relation(graph, anchor, relation, command)
# returns for the command's own (anchor, relation) pair above, or "none" when it abstains.
# This is the resolver's own graph traversal, never a model output, and it is the INVERSE
# direction of AnnotationGraph.related_rooms(anchor, relation), which is what the original
# e2e150 suite checked and which D57 finding 3 established is the wrong direction for this
# query (an edge "A right_of B" means A is right of B, not that something right of B is A).
# Six of the ten room keys are left_of/right_of phrasings and are affected; the four near
# phrasings are symmetric and unaffected. Keyed by the room that built the command, not by
# the corrected target, so build_commands() keeps generating byte-identical command text.
CORRECTED_SPATIAL_LABELS = {
    "reception": "meeting_room_a",
    "kitchen": "meeting_room_b",
    "meeting_room_a": "office",
    "meeting_room_b": "none",
    "office": "office",
    "server_room": "storage_room",
    "charging_dock": "charging_dock",
    "storage_room": "storage_room",
    "lab": "lab",
    "workshop": "storage_room",
}


def parse_reasoning(reasoning: str) -> Dict[str, object]:
    """PLAN.md 11B.1: the resolver already forwards ``reasoning`` (llm_resolver.py's
    ``_encode_reasoning``) inside ``/semantic_goal_result``; this only extracts it into run
    record columns, a harness gap only, with no interface change. Empty/default when
    ``reasoning`` is empty or carries none of these keys (fast path, cue-free, or a "none"
    relation that never attempted a hop)."""
    defaults = {
        "model_room": "", "anchor_room": "", "anchor_source": "", "relation": "none",
        "n_relation_targets": 0, "grammar_version": "",
    }
    if not reasoning:
        return defaults
    try:
        payload = json.loads(reasoning)
    except (json.JSONDecodeError, TypeError):
        return defaults
    out = dict(defaults)
    for key in defaults:
        if key in payload:
            out[key] = payload[key]
    return out


def _map_bounds(yaml_path: str = MAP_YAML_PATH) -> Tuple[float, float, float, float]:
    """(x_min, x_max, y_min, y_max) from the map YAML's origin/resolution and the referenced
    PGM's width/height, read from disk rather than hardcoded (PLAN.md 11A.3 off-map guard)."""
    import yaml as _yaml

    with open(yaml_path, "r", encoding="utf-8") as f:
        meta = _yaml.safe_load(f)
    origin_x, origin_y = float(meta["origin"][0]), float(meta["origin"][1])
    resolution = float(meta["resolution"])
    pgm_path = os.path.join(os.path.dirname(yaml_path), meta["image"])
    with open(pgm_path, "rb") as f:
        magic = f.readline().strip()
        if magic != b"P5":
            raise ValueError(f"{pgm_path}: expected a P5 (binary greyscale) PGM")
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        width, height = (int(v) for v in line.split())
    return origin_x, origin_x + width * resolution, origin_y, origin_y + height * resolution


def _spatial_phrase(anchor: str, relation: str) -> str:
    anchor_text = anchor.replace("_", " ")
    if relation in ("left_of", "right_of"):
        side = "left" if relation == "left_of" else "right"
        return f"Go to the room to the {side} of the {anchor_text}."
    return f"Go to the room {relation} the {anchor_text}."


def build_commands() -> List[Dict[str, str]]:
    """One row per (room, category); e2e150 repeats each 3 times at call time. Every row
    carries ``intended``, the room scored against; for spatial rows this is
    CORRECTED_SPATIAL_LABELS[room] (possibly "none"), not ``room`` itself."""
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    rows = []
    for room in ROOMS:
        anchor, relation = SPATIAL_ANCHORS[room]
        spatial_command = _spatial_phrase(anchor, relation)
        target, _ = resolve_relation(graph, anchor, relation, spatial_command)
        corrected = target or "none"
        if corrected != CORRECTED_SPATIAL_LABELS[room]:
            raise RuntimeError(
                f"CORRECTED_SPATIAL_LABELS[{room!r}] = {CORRECTED_SPATIAL_LABELS[room]!r} but "
                f"relations.resolve_relation(graph, {anchor!r}, {relation!r}, ...) now returns "
                f"{corrected!r}. The graph has drifted since the 11A.1 relabel; fix the table."
            )
        room_text = room.replace("_", " ")
        rows.append({"room": room, "intended": room, "category": "direct", "command": f"Can you take me to {room_text}?"})
        rows.append({"room": room, "intended": room, "category": "alias", "command": f"Could you guide me to the {ALIASES[room]}?"})
        rows.append({"room": room, "intended": room, "category": "negation", "command": NEGATIONS[room]})
        rows.append({"room": room, "intended": room, "category": "abbreviation", "command": f"Head to {ABBREVIATIONS[room]}, please."})
        rows.append({"room": room, "intended": corrected, "category": "spatial", "command": spatial_command})
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

    def _drain(self, timeout_sec: float) -> None:
        """rclpy.spin_once services at most one ready callback per call; with five
        subscriptions (/semantic_goal_result, /clarification_request,
        /semantic_resolution_result, /odom, /cmd_vel) all busy during navigation, a single
        spin_once per poll starves the others and drops queued /cmd_vel messages past its
        depth-10 queue before they are ever serviced. This is the capture bug behind the null
        t_nav_start rows (PLAN.md 11A.3): drain everything ready, not just one callback, before
        waiting again."""
        rclpy.spin_once(self, timeout_sec=timeout_sec)
        for _ in range(50):
            rclpy.spin_once(self, timeout_sec=0.0)

    def wait_ready(self) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            self._drain(0.2)
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
            self._drain(0.2)
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
    parser.add_argument("--start-row", type=int, default=0,
                         help="PLAN.md 11A.3: resume after an off-map guard stop, in append mode.")
    args = parser.parse_args()

    base_commands = build_commands()
    graph = AnnotationGraph.from_file(args.graph)
    room_poses = {r.name: r.pose for r in graph.rooms}
    room_aliases = {r.name: r.aliases for r in graph.rooms}
    x_min, x_max, y_min, y_max = _map_bounds()
    print(f"map bounds: x [{x_min:.2f}, {x_max:.2f}], y [{y_min:.2f}, {y_max:.2f}]")

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

    total_rows = len(base_commands) * args.trials
    all_rows = [(trial, entry) for trial in range(args.trials) for entry in base_commands]

    out_of_graph_count = 0
    rows_written = args.start_row
    consecutive_invalid = 0
    guard_tripped = False
    mode = "a" if args.start_row else "w"
    try:
        with open(args.out, mode, encoding="utf-8") as fh:
            for run_idx, (trial, entry) in enumerate(all_rows[args.start_row:], start=args.start_row + 1):
                row = node.run_one(entry["command"], args.gate_threshold, args.timeout)
                intended = entry["intended"]
                resolved = row.get("resolved_room") or row.get("attempted_room") or ""
                command_norm = normalize_command(entry["command"])
                edit_distance = min_edit_distance(resolved, room_aliases.get(resolved, []), command_norm)
                pose = room_poses.get(intended, {})

                nav_invalid = False
                if row.get("pose_x") is None:
                    nav_invalid = True
                elif not (x_min <= row["pose_x"] <= x_max and y_min <= row["pose_y"] <= y_max):
                    nav_invalid = True

                reached = None
                if not nav_invalid and intended != "none" and pose:
                    dx = row["pose_x"] - pose.get("x", 0.0)
                    dy = row["pose_y"] - pose.get("y", 0.0)
                    reached = (dx * dx + dy * dy) ** 0.5 < 0.5

                if nav_invalid:
                    consecutive_invalid += 1
                else:
                    consecutive_invalid = 0

                out_of_graph = bool(row.get("out_of_graph", False))
                if out_of_graph:
                    out_of_graph_count += 1
                reasoning_fields = parse_reasoning(row.get("reasoning", ""))
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
                    "nav_invalid": nav_invalid,
                    "out_of_graph": out_of_graph,
                    "reasoning": row.get("reasoning", ""),
                    "model_room": reasoning_fields["model_room"],
                    "anchor_room": reasoning_fields["anchor_room"],
                    "anchor_source": reasoning_fields["anchor_source"],
                    "relation": reasoning_fields["relation"],
                    "n_relation_targets": reasoning_fields["n_relation_targets"],
                    "grammar_version": reasoning_fields["grammar_version"],
                }
                fh.write(json.dumps(record) + "\n")
                fh.flush()
                rows_written += 1
                print(f"[{rows_written}/{total_rows}] "
                      f"{entry['command']!r} -> {record['resolved_room']!r} "
                      f"(gate_passed={record['gate_passed']}, nav={record['nav_result']}, "
                      f"nav_invalid={nav_invalid})")

                if consecutive_invalid >= 3:
                    guard_tripped = True
                    print(f"\nOFF-MAP GUARD: 3 consecutive nav_invalid rows ending at row {run_idx}. "
                          f"Stopping. Relaunch the stack and resume with --start-row {run_idx} "
                          f"(appends to {args.out}).")
                    break
    finally:
        stop_bag(bag_proc)
        node.destroy_node()
        rclpy.shutdown()

    print(f"wrote {rows_written - args.start_row} rows this invocation to {args.out}; "
          f"out_of_graph_count={out_of_graph_count}; guard_tripped={guard_tripped}")
    return 1 if guard_tripped else 0


if __name__ == "__main__":
    sys.exit(main())
