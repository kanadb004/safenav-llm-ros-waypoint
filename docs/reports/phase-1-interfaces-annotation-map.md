# Phase 1 report: interfaces and annotation map node

Date: 2026-09-15. Issue #3.

## What was built

- Package `semantic_waypoint_planner` (ament_cmake, C++17) under `ros2_ws/src/`:
  - `msg/SemanticGoal.msg`, `msg/ClarificationRequest.msg`, `srv/ResolveWaypoint.srv`,
    `srv/AddRoom.srv`, `srv/ListRooms.srv`, `srv/GetRoomPose.srv`, transcribed verbatim from
    PLAN.md section 12, generated with `rosidl_generate_interfaces` and linked into the node
    with `rosidl_get_typesupport_target`.
  - `annotation_graph.{hpp,cpp}`: a small C++ library (`nlohmann-json-dev`) that loads,
    validates, queries, and atomically persists `room_annotations.json`. Validation rejects
    duplicate names, duplicate or name-colliding aliases, non-finite pose fields, unknown edge
    endpoints, and non snake_case names, mirroring the Python core exactly.
  - `annotation_map_node.{hpp,cpp}`: rclcpp node, parameter `annotations_path` (default:
    `<share>/maps/room_annotations.json`), exits non-zero with a logged error on an invalid
    file. Serves `/get_room_pose`, `/add_room` (persists atomically: temp file then rename),
    `/list_rooms`. Publishes `/semantic_markers` (`MarkerArray`, transient local, one
    `TEXT_VIEW_FACING` marker per room) and `/annotation_graph_updated` (`std_msgs/Empty`,
    transient local) once per successful `AddRoom`.
  - Python core `semantic_waypoint_planner/graph.py` (no ROS imports): `AnnotationGraph`,
    `Room`, `validate()`, alias index, `resolve_alias`, `adjacency_text` (renders edges as
    sentences for the Phase 3 prompt builder), `add_room`, atomic `save`. Same validation rules
    as the C++ side.
  - `scripts/annotate_map.py`: interactive RViz mode (subscribes `/initialpose`,
    `/clicked_point`, prompts on the terminal, calls `/add_room` if the node is running else
    writes the file directly) and `--from-yaml LAYOUT.yaml` for deterministic import of
    `{name, x, y, theta, aliases, tags, parent}` entries under a `locations:` key (see "Open
    risks" below: this is the schema Phase 2's `layout.yaml` needs to match).
  - `maps/room_annotations.json`: 10 rooms, 20 sub locations, 30 canonical names total, 93
    aliases (no duplicates), deliberate overlaps (`dock` -> `charging_dock`,
    `docking bay` -> `storage_room`), 16 edges (`adjacent`, `near`, `left_of`, `right_of`).
    Poses are a placeholder grid layout; Phase 2 overwrites them via `annotate_map.py
    --from-yaml` once `layout.yaml` exists, per the plan.
  - Tests: `test/test_annotation_graph.cpp` (12 gtest cases, validation and CRUD), a
    `launch_testing` test starting the node against a fixture JSON and exercising all three
    services (7 cases), `test/python/test_graph.py` and `test/python/test_annotate_map.py`
    (20 pytest cases, host and container).

## Verification

All commands run inside the container from `/ws/ros2_ws` unless noted.

```
$ colcon build --symlink-install --packages-select semantic_waypoint_planner
Finished <<< semantic_waypoint_planner [1.8s]
```
No warnings from our sources (`-Wall -Wextra -Wpedantic` are on for the package; the only build
output is the finished line above).

```
$ ros2 interface show semantic_waypoint_planner/srv/ResolveWaypoint
```
Matches PLAN.md section 12.2 field for field (request, response, extension fields, comments).

```
$ ros2 run semantic_waypoint_planner annotation_map_node
[INFO] loaded 30 rooms from .../maps/room_annotations.json

$ ros2 service call /list_rooms semantic_waypoint_planner/srv/ListRooms
canonical_names: 30 entries, all_aliases: 93 entries (matches the file)

$ ros2 service call /get_room_pose ... '{name: charging_dock}'
found=True, pose.header.frame_id='map', position=(6.0, -6.0, 0.0)

$ ros2 service call /get_room_pose ... '{name: nonexistent_place}'
found=False
```

```
$ ros2 service call /add_room ... '{name: test_room_phase1, aliases: [test alias], ...}'
success=True, message='added room test_room_phase1'

$ ros2 service call /list_rooms ...   # now 31 canonical_names, JSON on disk has the entry
$ ros2 topic echo --once /semantic_markers | grep -c 'ns: semantic_waypoint_planner'
31
$ ros2 topic echo --once /annotation_graph_updated
{}   # latched Empty message present

$ ros2 service call /add_room ... '{name: test_room_phase1, ...}'   # same name again
success=False, message='duplicate room name: test_room_phase1'
```
(The install-tree copy of `room_annotations.json` used for this manual check is not the
tracked source file; `git status` confirms the source tree is unmodified.)

```
$ colcon test --packages-select semantic_waypoint_planner
$ colcon test-result --verbose
Summary: 39 tests, 0 errors, 0 failures, 0 skipped
```
(12 gtest, 7 launch_testing, 20 pytest under `ament_cmake_pytest`.)

Host (`tf_env`, no ROS):
```
$ /opt/anaconda3/envs/tf_env/bin/python -m pytest ros2_ws/src/semantic_waypoint_planner/test/python -q
20 passed in 0.07s
```
`graph.py` has no ROS imports, confirmed by running the same test file outside the container.

## Deviations

- D9 (new, recorded in PLAN.md section 14): `/semantic_markers` publishes one text marker per
  room instead of a text-plus-arrow pair, so the marker count equals the room count exactly as
  the DoD checks it. Noted as a follow-up for Phase 2 if an orientation arrow becomes useful in
  RViz.

## Build and tooling notes

- The container's globally installed `launch_testing` and `launch_ros` pytest11 plugins
  (`launch_testing.pytest.hooks`, `launch_testing_ros_pytest_entrypoint`) are incompatible with
  the pinned pytest version's hookspec and raise `PluginValidationError` / `INTERNALERROR` on
  collection, even for plain pytest files with no launch imports. The `ament_cmake_pytest`
  target for the ROS-free core (`test_python_core`) disables both with
  `PYTEST_ADDOPTS=-p no:launch_testing -p no:launch_ros`. This will likely recur for any future
  pure Python `ament_add_pytest_test` target in this image; the launch-based tests themselves
  are unaffected since they invoke `launch_testing.launch_test` directly, not through pytest.
- `rosidl_generate_interfaces()` already calls `ament_python_install_package(${PROJECT_NAME})`
  internally for the generated msg/srv Python bindings; calling it a second time for our own
  `graph.py` produced duplicate CMake target names and failed configure. `graph.py` is instead
  installed with a plain `install(FILES ...)` into the same `${PYTHON_INSTALL_DIR}/${PROJECT_NAME}`
  directory the generated bindings already own, so `semantic_waypoint_planner.graph`,
  `semantic_waypoint_planner.msg`, and `semantic_waypoint_planner.srv` resolve as one package.
- `nlohmann-json-dev` (rosdep key `nlohmann-json-dev`, CMake package `nlohmann_json`) was already
  present in the Phase 0 image; no Dockerfile change was needed.

## Open risks for Phase 2

- `annotate_map.py --from-yaml` expects `layout.yaml` to have a top level `locations:` list of
  `{name, x, y, theta, aliases, tags, parent}` entries. This schema was designed in this phase
  since `safenav_sim/worlds/layout.yaml` does not exist yet; Phase 2 should either match it or
  the two need to be reconciled together with the wall/door layout format.
- Room poses in `room_annotations.json` are a placeholder grid (not yet checked against real
  wall geometry); Phase 2's DoD requires them to equal `layout.yaml` after the sync, which will
  change every x/y/theta value.
- The launch_testing/launch_ros pytest plugin conflict above should be watched in Phase 2 and
  Phase 3 if their packages add pure Python `ament_add_pytest_test` targets.
