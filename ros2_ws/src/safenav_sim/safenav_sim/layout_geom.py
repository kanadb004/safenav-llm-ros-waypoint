"""ROS free geometry helpers shared by gen_world.py and gen_map.py.

Both scripts need the same list of wall segments (with door gaps cut out) so the
Gazebo world and the occupancy grid describe the same physical space. This module
is the single place that turns worlds/layout.yaml into that segment list.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class WallSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    height: float


def load_layout(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _cut_gaps(x0: float, x1: float, gap_centers: list[float], gap_width: float) -> list[tuple[float, float]]:
    """Return sub ranges of [x0, x1] with a gap of gap_width removed at each gap center."""
    gaps = []
    for c in gap_centers:
        g0, g1 = c - gap_width / 2.0, c + gap_width / 2.0
        g0, g1 = max(g0, x0), min(g1, x1)
        if g1 > g0:
            gaps.append((g0, g1))
    gaps.sort()

    ranges = []
    cursor = x0
    for g0, g1 in gaps:
        if g0 > cursor:
            ranges.append((cursor, g0))
        cursor = max(cursor, g1)
    if cursor < x1:
        ranges.append((cursor, x1))
    return ranges


def wall_segments(layout: dict) -> list[WallSegment]:
    """Build the full list of wall segments (outer boundary, corridor walls with
    door gaps, and inter room dividers) for the facility described by layout.
    """
    bounds = layout["bounds"]
    thickness = layout["wall_thickness"]
    height = layout["wall_height"]
    door_width = layout["door_width"]
    corridor = layout["corridor"]
    rooms = layout["rooms"]

    x_min, x_max = bounds["x_min"], bounds["x_max"]
    y_min, y_max = bounds["y_min"], bounds["y_max"]

    segments: list[WallSegment] = []

    # Outer boundary, fully enclosed.
    segments.append(WallSegment(x_min, y_min, x_max, y_min, thickness, height))
    segments.append(WallSegment(x_min, y_max, x_max, y_max, thickness, height))
    segments.append(WallSegment(x_min, y_min, x_min, y_max, thickness, height))
    segments.append(WallSegment(x_max, y_min, x_max, y_max, thickness, height))

    top_rooms = [r for r in rooms if r["y_min"] >= corridor["y_max"] - 1e-6]
    bottom_rooms = [r for r in rooms if r["y_max"] <= corridor["y_min"] + 1e-6]

    # Corridor / room divider walls, with one door per room centered on the room.
    top_door_centers = [(r["x_min"] + r["x_max"]) / 2.0 for r in top_rooms]
    for x0, x1 in _cut_gaps(corridor["x_min"], corridor["x_max"], top_door_centers, door_width):
        segments.append(WallSegment(x0, corridor["y_max"], x1, corridor["y_max"], thickness, height))

    bottom_door_centers = [(r["x_min"] + r["x_max"]) / 2.0 for r in bottom_rooms]
    for x0, x1 in _cut_gaps(corridor["x_min"], corridor["x_max"], bottom_door_centers, door_width):
        segments.append(WallSegment(x0, corridor["y_min"], x1, corridor["y_min"], thickness, height))

    # Dividers between neighboring rooms in the same row, no doors: robots use the corridor.
    def dividers(row_rooms, y0, y1):
        xs = sorted(r["x_min"] for r in row_rooms)[1:]
        return [WallSegment(x, y0, x, y1, thickness, height) for x in xs]

    segments.extend(dividers(top_rooms, corridor["y_max"], y_max))
    segments.extend(dividers(bottom_rooms, y_min, corridor["y_min"]))

    return segments
