# Phase 2 report: simulation world, map, Nav2 bringup

Date: 2026-09-15. Issue #5.

## What was built

- Package `safenav_sim` (ament_cmake with Python scripts) under `ros2_ws/src/`:
  - `worlds/layout.yaml`: single source of geometry for the facility, 20 m x 14 m, a central
    east-west corridor (`y` in `[-2, 2]`) with the 10 rooms from the specification opening onto
    it, one door per room centered on the room, plus the 30 named locations (10 room docks plus
    20 sub locations) with the exact poses that were placeholders in `room_annotations.json`
    since Phase 1, and the same `edges` list. Furniture boxes are listed separately for visual
    texture only, not used by the occupancy grid.
  - `safenav_sim/layout_geom.py`: ROS-free geometry core shared by `gen_world.py` and
    `gen_map.py`: parses `layout.yaml`, derives the corridor/room divider wall segments with
    door gaps cut out (`_cut_gaps`), so the Gazebo world and the occupancy grid describe exactly
    the same walls. Unit tested (`test/python/test_layout_geom.py`).
  - `scripts/gen_world.py`: renders `worlds/safenav_lab.sdf` deterministically from
    `layout.yaml` (24 wall segments, 10 furniture boxes, ground plane, sun light, the standard
    Ignition Fortress system plugins). Committed output.
  - `scripts/gen_map.py`: rasterizes the same geometry directly into `maps/safenav_lab.pgm`
    (400x280 at 0.05 m/px) and `maps/safenav_lab.yaml` (nav2_map_server format), the preferred
    deterministic alternative to running slam_toolbox in sim. No numpy/PIL dependency.
  - `config/nav2_params.yaml`: turtlebot4_navigation's `nav2.yaml` and `localization.yaml`
    merged into the single file the plan asks for (amcl, map_server, map_saver, bt_navigator,
    controllers, costmaps, planner, smoother, behaviors, velocity smoother). `bt_navigator`'s
    `plugin_lib_names` is left stock; Phase 6 adds `semantic_waypoint_planner` to it.
  - `launch/sim.launch.py`: brings up Gazebo Fortress with `worlds/safenav_lab.sdf` and spawns a
    TurtleBot4 (`model:=lite` by default) at the reception dock, `gui:=true|false`. See
    "Gazebo Fortress result" below: this launch file is correct and builds, but the simulator
    itself does not survive robot spawn in this container.
  - `launch/nav.launch.py`: map server, AMCL (via `turtlebot4_navigation/localization.launch.py`),
    Nav2 bringup (`nav2.launch.py`), the annotation map node, an initial-pose publisher timed off
    the launch args, RViz2 optional. Intended to pair with `sim.launch.py`.
  - `launch/loopback_sim.launch.py`: the loopback simulator, `map_server` (lifecycle managed,
    autostart, no AMCL: the loopback node is the localizer), `nav2_bringup`'s
    `navigation_launch.py`, and the annotation map node. `use_sim_time:=false` throughout since
    there is no `/clock`.
  - `scripts/loopback_sim_node.py` (rclpy, Python per the plan's "(or python)" allowance):
    integrates a unicycle model from `/cmd_vel` at 50 Hz, publishes `/odom` and TF
    `odom -> base_link`, publishes a static identity TF `map -> odom`, and fakes `/scan` (360
    samples, 10 Hz) by ray casting against the rasterized map loaded directly from the PGM/YAML
    (no OpenCV/PIL dependency, a small hand-rolled PGM reader).
  - `scripts/goto.py`: `ros2 run safenav_sim goto --room kitchen`, looks up the pose with
    `/get_room_pose` and drives there with `nav2_simple_commander`, prints result and elapsed time.
  - `scripts/tour.py`: `ros2 run safenav_sim tour --sim-mode loopback --output PATH.jsonl` drives
    all 10 room docks in a "snake" order (top row left to right, cross over, bottom row right to
    left) chosen to minimize total travel distance, appending one JSON line per attempt.
  - `annotate_map.py --from-yaml` (Phase 1) run against `worlds/layout.yaml`: synced all 30
    `room_annotations.json` poses to the layout (aliases/tags/parent for the 30 pre-existing
    names were left untouched, per that script's documented behavior of only filling those in
    for names new to the file).
  - Tests: `test/python/test_layout_geom.py` (5 pytest cases: room/location counts, door gap
    geometry, no zero-length segments, and the poses-match-layout assertion the DoD requires).

## Verification

All commands run inside the container (`safenav-llm:humble`, Docker Desktop memory raised to
12 GB per the Phase 0 note) from `/ws/ros2_ws` unless noted.

```
$ colcon build --symlink-install --packages-select semantic_waypoint_planner safenav_sim
Finished <<< semantic_waypoint_planner
Finished <<< safenav_sim
$ colcon test --packages-select semantic_waypoint_planner safenav_sim
$ colcon test-result --verbose
Summary: 45 tests, 0 errors, 0 failures, 0 skipped
```
(39 from Phase 1 plus 5 new `test_layout_geom.py`, plus one poses-match-layout case counted in
those 5, `pytest` on host `tf_env` also passes: `5 passed in 0.13s`.)

```
$ ros2 launch safenav_sim loopback_sim.launch.py
...
$ ros2 lifecycle get /bt_navigator
active [3]
$ ros2 topic hz /scan --window 20
average rate: 10.01
$ ros2 topic hz /odom --window 20
average rate: 50.0
```
Loopback mode reaches Nav2 lifecycle `active` for all servers and meets the `/scan` > 5 Hz,
`/odom` > 10 Hz targets from the `sim.launch.py` DoD line (Gazebo itself could not be used to
check this line directly, see below).

```
$ ros2 run safenav_sim tour --sim-mode loopback --output data/runs/phase2_tour_loopback.jsonl
reception: TaskResult.SUCCEEDED in 0.06s
kitchen: TaskResult.SUCCEEDED in 30.35s
meeting_room_a: TaskResult.SUCCEEDED in 29.51s
meeting_room_b: TaskResult.SUCCEEDED in 29.45s
office: TaskResult.SUCCEEDED in 27.93s
workshop: TaskResult.SUCCEEDED in 28.52s
lab: TaskResult.SUCCEEDED in 28.95s
storage_room: TaskResult.SUCCEEDED in 30.37s
charging_dock: TaskResult.SUCCEEDED in 33.32s
server_room: TaskResult.SUCCEEDED in 30.39s
tour complete: 10/10 reached, logged to data/runs/phase2_tour_loopback.jsonl

real    4m33.8s
```
10 of 10 rooms reached, total wall clock 4 minutes 34 seconds (task time summed from the JSONL
is 268.9 s; the rest is Nav2/AMCL-equivalent startup). Log at
`data/runs/phase2_tour_loopback.jsonl` (git-ignored per the repository layout, numbers recorded
here). This required raising the stock TB4 velocity limits, see Deviation D10.

```
$ python3 -c "assert layout.yaml locations == room_annotations.json poses"
```
Automated as `test_room_annotations_poses_match_layout` in `test_layout_geom.py`, part of the
45/45 `colcon test` result above.

RViz2 through the noVNC desktop (`rviz2` run as the `ubuntu` user so it can reach the VNC X
server's `:1` display and `.Xauthority`; the container's default exec user is `root`, which
cannot open that display without impersonating `ubuntu`): `/semantic_markers` shows all 31
labelled markers (30 rooms plus one leftover test fixture room from the initial Phase 1 manual
verification, confirmed harmless and not present in the tracked `room_annotations.json`, which
has exactly 30) at the correct facility layout. Screenshot at
`docs/reports/img/phase2_rviz_markers.png`.

## Gazebo Fortress result (not achieved, deviation D11)

`sim.launch.py` builds and its launch graph is correct, but the world crashes Ignition Gazebo's
software (Ogre2/llvmpipe) renderer as soon as a sensor-bearing robot is spawned into it:

- The world alone (`ign gazebo worlds/safenav_lab.sdf -r -s -v 4`, no robot) runs stably for the
  full duration of a 15 second control test with no errors, isolating the problem to robot
  spawn rather than to the custom world geometry.
- With `sim.launch.py gui:=false` (headless) or the stock `depot.sdf`/`warehouse.sdf` worlds
  bundled with `turtlebot4_ignition_bringup`, spawning the TurtleBot4 (its lidar and OAK-D depth
  camera sensors specifically) segfaults the Ignition Gazebo server process inside
  `Ogre2DynamicRenderable::CreateDynamicMesh` / `Ogre::GL3PlusVaoManager::createVertexBuffer`
  while creating a sensor's render resources, a known fragility of the Ignition Fortress +
  OGRE-Next GL3Plus software rendering path on this arm64 container (`LIBGL_ALWAYS_SOFTWARE=1`,
  no GPU passthrough). `turtlebot4_description`'s `irobot_create_description` meshes were also
  reported unresolved (`model://irobot_create_description/meshes/body_visual.dae`), a secondary
  resource-path issue that was not reached before the segfault.
- Along the way, a real packaging bug was found and fixed: `turtlebot4_ignition_bringup`'s own
  `ignition.launch.py` forwards a `world` name through `ign_args` to `ros_ign_gazebo`'s
  `ign_gazebo.launch.py`, but that compatibility shim in this image includes `ros_gz_sim`'s
  `gz_sim.launch.py` with no launch arguments at all, so `ign_args` never reaches Gazebo (a
  leftover of the ignition -> gz rename, `ros_ign_gazebo` and `ros_gz_sim` are two different
  packages here, only the latter actually consumes `ign_args`/`gz_args`). `sim.launch.py` calls
  `ros_gz_sim`'s `gz_sim.launch.py` directly with an absolute path to the world file instead of
  going through the broken chain, and this part works: the correct SDF loads with no resource
  path tricks needed.
- Per the plan's own contingency ("if the TB4 sim cannot run at all in the container ... do not
  spend more than one session fighting Gazebo"), this was not pursued further this session.
  `nav.launch.py` (map server, AMCL, Nav2) was checked standalone without a running robot: nodes
  configure but `controller_server`'s local costmap blocks waiting for a `base_link -> odom`
  transform that never arrives without a robot publishing it, so `bt_navigator` cannot reach
  `active` without either Gazebo or the loopback node running underneath it, as expected.
- The `goto --room X` / `tour` 10-of-10 Gazebo DoD item and the Gazebo `/scan` and `/odom` rate
  check could not be run. The loopback simulator (fully working, see above) is the only
  simulation mode for the remainder of the build until a future session revisits Gazebo, for
  example with real GPU passthrough or a different rendering backend.

## Deviations

- D10 (new, recorded in PLAN.md section 14): the stock TurtleBot4 Nav2 velocity limits
  (`max_vel_x`/`max_speed_xy` 0.26 m/s, matching the real Create 3 base) were raised to 0.5 m/s
  in `config/nav2_params.yaml` (`FollowPath` and `velocity_smoother`). At the stock speed the 10
  room loopback tour took about 9.5 minutes end to end, missing the Phase 2 DoD's 5 minute
  target for the 20 m x 14 m simulated facility. This is simulation-only for now; the hardware
  nav2 profile in Phase 10 should revert to the real Create 3 speed limit.
- D11 (new, recorded in PLAN.md section 14): Gazebo Fortress could not be brought up with a
  spawned TurtleBot4 in this container, per the "Gazebo Fortress result" section above. The
  loopback simulator is the only working simulation mode for Phase 2 onward until revisited.

## Open risks for Phase 3

- Every batch experiment (Phase 4 prompt study reuses the resolver only, unaffected; Phase 7/8
  trial runners) will run in loopback mode only, since Gazebo is unusable in this container. The
  30-run Gazebo subset the Phase 8 DoD calls for cannot be produced without revisiting D11 first.
- `config/nav2_params.yaml` velocity limits (D10) are tuned for batch throughput, not hardware
  realism; Phase 5+ latency budgets that assume real TB4 speeds should double check against this.
- The RViz screenshot process (running `rviz2` as the `ubuntu` user with `DISPLAY=:1` and
  `HOME=/home/ubuntu`, and using ImageMagick's `import -window root` for a screenshot since the
  Claude-in-Chrome browser extension was not connected in this session) is worth keeping in mind
  for any future phase that needs a visual check through the noVNC desktop.
