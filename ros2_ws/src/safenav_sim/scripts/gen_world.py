#!/usr/bin/env python3
"""Render worlds/safenav_lab.sdf from worlds/layout.yaml. Deterministic: run again to
regenerate after editing the layout, commit the output.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from safenav_sim.layout_geom import load_layout, wall_segments  # noqa: E402

SDF_HEADER = """<?xml version="1.0"?>
<sdf version="1.8">
  <world name="safenav_lab">
    <physics name="1ms" type="ignored">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="ignition-gazebo-physics-system" name="ignition::gazebo::systems::Physics"/>
    <plugin filename="ignition-gazebo-user-commands-system" name="ignition::gazebo::systems::UserCommands"/>
    <plugin filename="ignition-gazebo-scene-broadcaster-system" name="ignition::gazebo::systems::SceneBroadcaster"/>
    <plugin filename="ignition-gazebo-contact-system" name="ignition::gazebo::systems::Contact"/>
    <plugin filename="ignition-gazebo-sensors-system" name="ignition::gazebo::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>

    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>40 40</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>40 40</size></plane></geometry>
          <material><ambient>0.6 0.6 0.6 1</ambient><diffuse>0.6 0.6 0.6 1</diffuse></material>
        </visual>
      </link>
    </model>
"""

SDF_FOOTER = """  </world>
</sdf>
"""

WALL_MATERIAL = "<material><ambient>0.8 0.75 0.7 1</ambient><diffuse>0.8 0.75 0.7 1</diffuse></material>"
FURNITURE_MATERIAL = "<material><ambient>0.4 0.3 0.2 1</ambient><diffuse>0.4 0.3 0.2 1</diffuse></material>"


def wall_model(index: int, seg) -> str:
    dx, dy = seg.x2 - seg.x1, seg.y2 - seg.y1
    length = max((dx**2 + dy**2) ** 0.5, seg.thickness)
    yaw = 0.0 if dx == 0 and dy == 0 else __import__("math").atan2(dy, dx)
    cx, cy = (seg.x1 + seg.x2) / 2.0, (seg.y1 + seg.y2) / 2.0
    return f"""    <model name="wall_{index}">
      <static>true</static>
      <pose>{cx:.3f} {cy:.3f} {seg.height / 2:.3f} 0 0 {yaw:.6f}</pose>
      <link name="link">
        <collision name="collision">
          <geometry><box><size>{length:.3f} {seg.thickness:.3f} {seg.height:.3f}</size></box></geometry>
        </collision>
        <visual name="visual">
          <geometry><box><size>{length:.3f} {seg.thickness:.3f} {seg.height:.3f}</size></box></geometry>
          {WALL_MATERIAL}
        </visual>
      </link>
    </model>
"""


def furniture_model(item: dict) -> str:
    return f"""    <model name="furniture_{item['name']}">
      <static>true</static>
      <pose>{item['x']:.3f} {item['y']:.3f} 0.4 0 0 {item['yaw']:.6f}</pose>
      <link name="link">
        <collision name="collision">
          <geometry><box><size>{item['w']:.3f} {item['h']:.3f} 0.8</size></box></geometry>
        </collision>
        <visual name="visual">
          <geometry><box><size>{item['w']:.3f} {item['h']:.3f} 0.8</size></box></geometry>
          {FURNITURE_MATERIAL}
        </visual>
      </link>
    </model>
"""


def generate(layout_path: str, output_path: str) -> None:
    layout = load_layout(layout_path)
    segments = wall_segments(layout)

    parts = [SDF_HEADER]
    for i, seg in enumerate(segments):
        parts.append(wall_model(i, seg))
    for item in layout.get("furniture", []):
        parts.append(furniture_model(item))
    parts.append(SDF_FOOTER)

    with open(output_path, "w") as f:
        f.write("".join(parts))
    print(f"wrote {output_path}: {len(segments)} wall segments, "
          f"{len(layout.get('furniture', []))} furniture boxes")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default=os.path.join(here, "..", "worlds", "layout.yaml"))
    parser.add_argument("--output", default=os.path.join(here, "..", "worlds", "safenav_lab.sdf"))
    args = parser.parse_args()
    generate(args.layout, args.output)


if __name__ == "__main__":
    main()
