#!/usr/bin/env python3
"""PLAN.md 11A.1: rescore an e2e150 JSONL file against the corrected spatial labels, without
rerunning inference. Only the production suite (Phase 8's e2e150_loopback.jsonl) needs this:
it predates the relabel fix in scripts/run_trials.py. The gate-off and grammar-off reruns
(11A.4) use the fixed runner directly and need no rescoring.

For each spatial row, the committed ``intended_room`` field is the room key the command was
built from (e.g. "reception"), which is also CORRECTED_SPATIAL_LABELS' key; the corrected
target comes from that frozen table, not from re-running any resolver or model. Original-label
numbers are kept alongside, not overwritten, matching Phase 5A's practice.

Usage:
    python3 ml/safenav_ml/rescore_e2e150.py --in data/runs/e2e150_loopback.jsonl \
        --out data/runs/e2e150_loopback_rescored.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)
sys.path.insert(0, os.path.join(ROS2_PY_PATH, "scripts"))

from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "run_trials", os.path.join(ROS2_PY_PATH, "scripts", "run_trials.py"))
_RUN_TRIALS = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("run_trials", _RUN_TRIALS)
try:
    _SPEC.loader.exec_module(_RUN_TRIALS)
except ModuleNotFoundError:
    # run_trials.py imports rclpy at module scope for the live runner; only the pure-Python
    # pieces (CORRECTED_SPATIAL_LABELS, _map_bounds) are needed here. Fall back to re-deriving
    # them directly rather than requiring a sourced ROS 2 environment for an offline rescore.
    _RUN_TRIALS = None

if _RUN_TRIALS is not None:
    CORRECTED_SPATIAL_LABELS = _RUN_TRIALS.CORRECTED_SPATIAL_LABELS
    _map_bounds = _RUN_TRIALS._map_bounds
else:
    CORRECTED_SPATIAL_LABELS = {
        "reception": "meeting_room_a", "kitchen": "meeting_room_b",
        "meeting_room_a": "office", "meeting_room_b": "none", "office": "office",
        "server_room": "storage_room", "charging_dock": "charging_dock",
        "storage_room": "storage_room", "lab": "lab", "workshop": "storage_room",
    }

    def _map_bounds():
        import yaml
        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "ros2_ws", "src", "safenav_sim", "maps", "safenav_lab.yaml")
        with open(yaml_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        origin_x, origin_y = float(meta["origin"][0]), float(meta["origin"][1])
        resolution = float(meta["resolution"])
        pgm_path = os.path.join(os.path.dirname(yaml_path), meta["image"])
        with open(pgm_path, "rb") as f:
            magic = f.readline().strip()
            assert magic == b"P5"
            line = f.readline()
            while line.startswith(b"#"):
                line = f.readline()
            width, height = (int(v) for v in line.split())
        return origin_x, origin_x + width * resolution, origin_y, origin_y + height * resolution

ANNOTATIONS_PATH = os.path.join(ROS2_PY_PATH, "maps", "room_annotations.json")


def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def rescore(rows: List[dict], graph: AnnotationGraph, bounds) -> List[dict]:
    x_min, x_max, y_min, y_max = bounds
    room_poses = {r.name: r.pose for r in graph.rooms}
    out = []
    for row in rows:
        row = dict(row)
        original_intended = row["intended_room"]
        if row["category"] == "spatial":
            corrected_intended = CORRECTED_SPATIAL_LABELS[original_intended]
        else:
            corrected_intended = original_intended

        pose_x, pose_y = row.get("pose_x"), row.get("pose_y")
        nav_invalid = row.get("nav_invalid")
        if nav_invalid is None:
            if pose_x is None or pose_y is None:
                nav_invalid = True
            else:
                nav_invalid = not (x_min <= pose_x <= x_max and y_min <= pose_y <= y_max)

        def _reached(intended: str):
            if nav_invalid or intended == "none":
                return None
            pose = room_poses.get(intended, {})
            if not pose or pose_x is None:
                return None
            dx = pose_x - pose.get("x", 0.0)
            dy = pose_y - pose.get("y", 0.0)
            return math.hypot(dx, dy) < 0.5

        row["nav_invalid"] = nav_invalid
        row["original_intended_room"] = original_intended
        row["original_reached_intended"] = row.get("reached_intended")
        row["intended_room"] = corrected_intended
        row["reached_intended"] = _reached(corrected_intended)
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graph", default=ANNOTATIONS_PATH)
    args = parser.parse_args()

    graph = AnnotationGraph.from_file(args.graph)
    bounds = _map_bounds()
    rows = load_jsonl(args.in_path)
    rescored = rescore(rows, graph, bounds)

    n_spatial = sum(1 for r in rescored if r["category"] == "spatial")
    n_relabelled = sum(
        1 for r in rescored
        if r["category"] == "spatial" and r["original_intended_room"] != r["intended_room"]
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rescored:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rescored)} rows to {args.out}; "
          f"{n_relabelled}/{n_spatial} spatial rows relabelled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
