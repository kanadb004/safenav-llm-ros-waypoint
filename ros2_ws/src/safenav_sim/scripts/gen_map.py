#!/usr/bin/env python3
"""Rasterize worlds/layout.yaml directly into an occupancy grid: maps/safenav_lab.pgm
and maps/safenav_lab.yaml (nav2_map_server format). Preferred over running slam_toolbox
in sim because it is deterministic and matches the wall geometry exactly.

No numpy/PIL dependency so this also runs with the plain system python3 in the container.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from safenav_sim.layout_geom import load_layout, wall_segments  # noqa: E402

FREE = 254
OCCUPIED = 0


def occupied_rect(seg):
    """Axis aligned occupied rectangle for a wall segment, extended half a thickness
    at each end so segments meeting at a corner or T-junction leave no pinhole gap.
    All layout walls are axis aligned (horizontal or vertical), so this is exact.
    """
    half = seg.thickness / 2.0
    if abs(seg.y2 - seg.y1) < 1e-9:  # horizontal
        x0, x1 = sorted((seg.x1, seg.x2))
        return (x0 - half, x1 + half, seg.y1 - half, seg.y1 + half)
    else:  # vertical
        y0, y1 = sorted((seg.y1, seg.y2))
        return (seg.x1 - half, seg.x1 + half, y0 - half, y1 + half)


def rasterize(layout: dict):
    bounds = layout["bounds"]
    resolution = layout["resolution"]
    x_min, x_max = bounds["x_min"], bounds["x_max"]
    y_min, y_max = bounds["y_min"], bounds["y_max"]

    width = int(round((x_max - x_min) / resolution))
    height = int(round((y_max - y_min) / resolution))

    rects = [occupied_rect(s) for s in wall_segments(layout)]

    # grid[row][col], row 0 is the top of the image (highest y), matching PGM/map_server
    # convention where the map origin (x_min, y_min) is the bottom left corner.
    grid = bytearray([FREE]) * (width * height)
    for row in range(height):
        y = y_max - (row + 0.5) * resolution
        for col in range(width):
            x = x_min + (col + 0.5) * resolution
            for rx0, rx1, ry0, ry1 in rects:
                if rx0 <= x <= rx1 and ry0 <= y <= ry1:
                    grid[row * width + col] = OCCUPIED
                    break
    return grid, width, height


def write_pgm(path: str, grid: bytearray, width: int, height: int) -> None:
    with open(path, "wb") as f:
        f.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        f.write(bytes(grid))


def write_yaml(path: str, pgm_name: str, layout: dict) -> None:
    bounds = layout["bounds"]
    resolution = layout["resolution"]
    with open(path, "w") as f:
        f.write(f"image: {pgm_name}\n")
        f.write(f"resolution: {resolution}\n")
        f.write(f"origin: [{bounds['x_min']}, {bounds['y_min']}, 0.0]\n")
        f.write("negate: 0\n")
        f.write("occupied_thresh: 0.65\n")
        f.write("free_thresh: 0.25\n")


def generate(layout_path: str, output_dir: str, name: str) -> None:
    layout = load_layout(layout_path)
    grid, width, height = rasterize(layout)
    pgm_path = os.path.join(output_dir, f"{name}.pgm")
    yaml_path = os.path.join(output_dir, f"{name}.yaml")
    write_pgm(pgm_path, grid, width, height)
    write_yaml(yaml_path, f"{name}.pgm", layout)
    occupied = sum(1 for b in grid if b == OCCUPIED)
    print(f"wrote {pgm_path} ({width}x{height}, {occupied} occupied cells) and {yaml_path}")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default=os.path.join(here, "..", "worlds", "layout.yaml"))
    parser.add_argument("--output-dir", default=os.path.join(here, "..", "maps"))
    parser.add_argument("--name", default="safenav_lab")
    args = parser.parse_args()
    generate(args.layout, args.output_dir, args.name)


if __name__ == "__main__":
    main()
