# Jetson / TurtleBot4 bring-up checklist

Written in Phase 9 (PLAN.md section 15) without a robot present. Every row below cites either a
simulation result that already exercised the seam, or `cannot-verify.md` if no simulation work
can de-risk it. Follow this top to bottom the first time the stack runs against real hardware;
each row says what to do and what already gives confidence it will work.

## 1. Model load and CUDA offload

**Do:** start `llama-server` on the Jetson with the production model
(`phi3-mini-4k-instruct.Q4_K_M.gguf`) and confirm it logs CUDA device detection and offloads all
layers, not a silent CPU fallback.
**Evidence:** `docker/Dockerfile.jetson` builds llama.cpp with `-DGGML_CUDA=ON` and
`CMAKE_CUDA_ARCHITECTURES=87` (Orin NX, sm_87); see `jetson-build.md` failure mode 2 for why
that flag is pinned rather than auto-detected. The model itself and the grammar-constrained
decoding path are unchanged from what Phases 3 through 8 ran on Metal (`docs/results/RESULTS.md`
section 3). **Not verified:** CUDA offload has never run on this project's model; Phase 10
confirms `llama-server`'s own startup log reports layers on GPU.

## 2. Grammar identity across backends

**Do:** run `ml/safenav_ml/backend_parity.py` against the Jetson `llama-server`'s HTTP endpoint
and confirm it still reports (near) 100 percent agreement with in-process decoding.
**Evidence:** Phase 5 ran this exact tool between in-process and HTTP-to-Metal-`llama-server`
backends and found 100 percent backend parity
(`docs/reports/phase-5-relational-decomposition-resolver-backend.md`, section on
`phase5_backend_parity.jsonl`; same GBNF grammar, same sampler). The HTTP seam itself, not the
host it talks to, is what was exercised; moving the `llama-server` process to the Jetson changes
only the host the HTTP backend talks to, not the resolver code path (`resolver_core.py`'s
`backend="http"` branch is backend-url-agnostic). **Not verified:** parity has never been run
against a CUDA-backed `llama-server`; GPU floating point execution order can differ slightly
from CPU/Metal and in principle changes the model's sampled tokens at the margin (unlikely at
temperature 0.3 with grammar constraints, but unmeasured).

## 3. The `/resolve_waypoint` contract

**Do:** confirm `ros2 service call /resolve_waypoint semantic_waypoint_planner/srv/ResolveWaypoint`
round-trips with the full `12.2` response shape against the Jetson-hosted resolver node.
**Evidence:** the service contract itself has been frozen and exercised since Phase 1
(PLAN.md section 12.2); it is pure ROS 2 IDL and does not depend on the host architecture.
`test_resolver_core_offline.py` (31 tests, host pytest, arch-independent) and the Phase 6 launch
test `test_semantic_nav_launch.py` already exercise the request/response shape end to end
against a real `bt_navigator`. **Not verified:** the service has never been called against a
resolver node that is itself backed by a remote (loopback) `llama-server` process on the same
physical machine as the ROS graph; Phase 10 is the first time these two processes share a Jetson
rather than a Mac host plus a Linux container.

## 4. The BT plugin load path in `bt_navigator`

**Do:** confirm `bt_navigator`'s log reports `semantic_waypoint_planner_bt_node` registered via
pluginlib with no missing-symbol or ABI errors, on the arm64/CUDA build.
**Evidence:** `test_semantic_nav_launch.py` loads a real `nav2_bt_navigator` process with
`plugin_lib_names` including `semantic_waypoint_planner_bt_node` and asserts the tree executes
all three DoD paths (success, low-confidence, timeout; see that file's module docstring).
`docker/Dockerfile.jetson` builds this package with `colcon build` against the same
`ament_cmake`/`rclcpp` toolchain, just for arm64 instead of the dev image's arm64-under-QEMU.
**Not verified:** pluginlib's dynamic loading mechanism (`dlopen` under the hood) has not been
exercised on an actual Jetson binary; cross-architecture ABI mismatches are unlikely for a
same-arch (arm64-to-arm64) build but the dev image never produced a binary that ran outside its
own container.

## 5. The annotation graph and its poses against a fresh SLAM map

**Do:** regenerate `room_annotations.json`'s room poses from a SLAM map of the real facility
(not `safenav_lab.yaml`'s synthetic layout), then re-run the edge coverage audit.
**Evidence:** the coverage audit methodology and tooling exist and were exercised once already
(PLAN.md section 8.1, "Edge coverage audit"; `ml/safenav_ml/audit_edges.py`). The graph schema
(12.7) and relational hop logic (`relations.py`, `apply_relational_hop`) are architecture- and
map-independent; they operate on names and edges, not pixel coordinates. **Not verified:** no
real SLAM map of any physical facility has been built; every pose in the committed
`room_annotations.json` is hand-authored against the synthetic Gazebo world. This is listed
again in `cannot-verify.md` because building a SLAM map needs the robot driving around a real
room, not something a checklist item alone resolves.

## 6. TF frames

**Do:** confirm `map` -> `odom` -> `base_link` is being published by AMCL and the Create 3's own
odometry (not a static stub), and that `transform_tolerance` values in the hardware nav2 profile
are not routinely exceeded.
**Evidence:** the TF tree's shape (`global_frame: map`, `odom_frame_id: odom`,
`base_frame_id: base_link`) is unchanged from `nav2_params.yaml` into
`nav2_params_hardware.yaml` (Phase 9 touches only the Create 3 velocity limits, see item 10
below); `test_semantic_nav_launch.py` publishes a static `map` -> `base_link` transform as a
stand-in and the graph resolves correctly around it. **Not verified:** a static transform is not
AMCL. Real sensor noise feeding AMCL's particle filter against a real map has never run; this is
also listed in `cannot-verify.md`.

## 7. The calibrator file

**Do:** confirm the resolver node logs `calibrator_loaded=true` on the Jetson and that
`ResolveWaypoint.srv`'s `calibrated_confidence` field is populated (not falling back to
`raw_confidence`).
**Evidence:** `calibrator.json` (Phase 7, threshold 0.85) is loaded by path, not by any
architecture-specific code; `planner_params.yaml`'s hardware profile leaves `calibrator_path`
unset so it keeps the Phase 7 default of `<share>/config/calibrator.json`, same file the sim
profile loads. `test_resolver_core_offline.py`'s feature-vector tests (`test_features_vector_order`
and neighbors) exercise the same calibration math the node runs. **Not verified:** the
calibrator was trained on simulated session data (`calibration_session{1,2}_trials.jsonl`,
Phase 7); its five features (12.8) were never computed from a real microphone or a real Jetson's
timing distribution, only simulated commands and simulated latency. Listed again in
`cannot-verify.md` as a generalization risk, not a loading risk.

## 8. `/tts_text`

**Do:** confirm `/tts_text` messages reach a real `espeak-ng` process and audible speech comes
out of the robot's speaker.
**Evidence:** `bt_speak_text.cpp` publishes `/tts_text` as a plain `std_msgs/String`, and
`test_semantic_nav_launch.py` subscribes to it and asserts a message with the expected content
arrives on all three DoD paths (success, low confidence, timeout). `espeak-ng` is installed in
both `docker/Dockerfile` and `docker/Dockerfile.jetson`. **Not verified:** no audio has ever
played; the project has never run with real audio hardware. Listed in `cannot-verify.md`.

## 9. Latency gate under the hardware backend

**Do:** measure resolver p50/p90/p99 against the Jetson `llama-server` before running any trial
suite, the same way `docs/results/RESULTS.md` section 3 measures the Metal paths.
**Evidence:** the specification's "about 0.7 s" Orin figure is an expectation, never a
measurement (PLAN.md section 13). The measured ROS-path latency on this project's one real
backend, the macOS host, is p50 3797 to 3942 ms and p90 5160 to 5540 ms (8B gate-off rerun, 8C
production run, both GPU-isolated; `docs/results/RESULTS.md` section 3), above both the
hardware profile's `timeout_ms: 3000` and the 5 s BT tick default. **Not verified: this is the
single largest open risk Phase 9 carries forward (PLAN.md 15.0).** If the Jetson's measured
latency is anywhere near the macOS ROS-path figures rather than the specification's 0.7 s, most
requests will time out into clarification under the hardware profile as written. Phase 10 must
measure this before running any accuracy trial, and raise `timeout_ms` (with a recorded
deviation) rather than silently absorbing timeouts as clarifications if the measured number
does not support 3000.

## 10. Create 3 velocity limits

**Do:** confirm the robot moves at its stock 0.26 m/s linear limit under the hardware nav2
profile, not the sim profile's 0.5 m/s touring speed.
**Evidence:** `nav2_params_hardware.yaml` reverts `FollowPath.max_vel_x`, `max_speed_xy` and
`velocity_smoother`'s linear `max_velocity`/`min_velocity` entries to 0.26 (D10 reversed for
hardware only), tested by
`test/python/test_nav2_params_hardware_profile.py::test_hardware_velocity_limits_are_stock_turtlebot4_default`.
**Not verified:** no real Create 3 has executed any trajectory at any speed; this is a
configuration-correctness check, not a motion-safety one. First real movement should be
supervised at walking pace regardless of what the config says.

## 11. Nav start latency

**Do:** when measuring time-to-navigation-start on hardware, report both the figure and how many
rows it is missing from.
**Evidence/caveat:** the shipped e2e150 run (`e2e150_production_8c.jsonl`) has
`time_to_nav_start` null for 103 of 150 rows (8B production had 79 of 150 null); any hardware
figure quoting this metric must give n and the null count or be marked unverified (PLAN.md
15.0). Do not treat a clean-looking hardware number as representative without checking its null
rate the same way.
