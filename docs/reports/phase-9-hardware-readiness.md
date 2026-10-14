# Phase 9: hardware readiness (no robot required)

Makes Jetson Orin NX deployment a verified-feasible path rather than an assumption, using only
what can be checked without the physical robot (PLAN.md section 15). This phase writes and
reviews; Phase 10 builds and measures on the device. No inference and no simulator run.

The first commit fixes the four small defects the Phase 8D review found (PLAN.md 15.0); they
change no number and no decision. The rest of the phase is new hardware-facing scope.

## 1. Phase 8D carry-over fixes (15.0)

1. `ml/safenav_ml/e2e_report.py`'s `_acted` docstring cited "D65 finding 2" for why `gate_passed`
   alone was wrong; the frozen file disproves that cause (no row has `gate_passed` true with an
   empty/`none` room). Corrected to the real cause (11C.0 finding 3: 8C never re-gated at 0.0 and
   reused the gate-on acted count). Re-ran `--regate 0.0` against `e2e150_production_8c.jsonl`
   to confirm the fix changes no number: 143/150 acted, 0.020 wrong-room, matching the figure
   already in `e2e150_report_8c.md` and `docs/reports/phase-8d-ship-text-anchor.md`.
2. `main()`'s summary label was a fixed string regardless of `--regate`. It now appends
   `, re-gated at <threshold>.2f` when `--regate` is passed, verified against the same rerun.
3. `e2e150_report_8c.md`'s opening paragraph had the "Corrected by D65" banner inserted
   mid-sentence, splitting the original run-condition text in two. Moved the run-condition
   sentence back after the original first paragraph and left the banner as its own paragraph;
   no wording changed.
4. `MANIFEST.md` had a per-file `text_anchor` note only on the `e2e150_production_8c.jsonl` row,
   though the 8D report claimed every file had one. Added the missing shared sentence below the
   JSONL table for the `phase8_*`, `e2e150_*_8b`, `e2e150_loopback_rescored`, `phase5a_full500`
   and `calibration_session*` files, and a one-line "Corrected in Phase 9" note at the 8D
   report's claim.

The two 15.0 context items (the unmeasured hardware timeout and the mostly-null nav start
latency) are carried into this phase's own deliverables: `bringup-checklist.md` items 9 and 11,
`cannot-verify.md` item 6, and `RESULTS.md` section 8.

## 2. `docker/Dockerfile.jetson` (not built)

New Dockerfile targeting a Jetson Orin NX on **JetPack 6** (L4T r36.x, Ubuntu 22.04 Jammy), not
JetPack 5 (Ubuntu 20.04): recorded as D66, since no prior phase specified a JetPack version and
the choice is load bearing (JetPack 5 has no official Humble apt repo for its Focal rootfs).
Reviewed line by line against the dev `docker/Dockerfile`:

- Same llama.cpp pin (`third_party/llama.cpp`, tag `b10941`), built with `-DGGML_CUDA=ON` and
  `-DCMAKE_CUDA_ARCHITECTURES=87` (Orin NX, sm_87) pinned explicitly rather than left to
  auto-detection, since the Docker build context has no GPU visible to it.
- `-j2` caps the llama.cpp CUDA build's parallelism (the dev Dockerfile uses `-j"$(nproc)"` for
  its CPU-only build); `ggml-cuda`'s per-unit memory cost can OOM an 8 GB Orin NX module at full
  parallelism.
- Only `semantic_waypoint_planner` is colcon-built into the image; `safenav_sim` (Gazebo,
  loopback simulator) is intentionally left out, it has no reason to ship on the robot.
- No OSRF Gazebo repo, no vendored `third_party/ros_src` simulation overlay build: Nav2 and
  TurtleBot4's hardware packages (not `turtlebot4-simulator`, which is the one package without
  arm64 binaries per the dev Dockerfile's own comment) install from apt directly.

**Reviewed, not built:** there is no Jetson and no `nvidia-container-toolkit` on this host to
build against. `docs/hardware/jetson-build.md` has three identified failure modes (JetPack
version mismatch, CUDA architecture auto-detection, out-of-memory at link time) each with its
remedy, and the recipe's expected build time is stated as an estimate, not a measurement.
Everything that can only be confirmed by actually running `docker build` on the device
(dependency resolution succeeding, the CUDA toolkit actually being present and at a version
`ggml-cuda` builds against, disk space holding up) is explicitly left to Phase 10.

Also corrected `docs/hardware/llama-server.md`'s "Jetson CUDA" section, written in Phase 5,
which said Phase 9 builds and measures the Jetson `llama-server`; the current plan (section 15)
assigns the actual build and measurement to Phase 10. Updated the flags shown there to match
`Dockerfile.jetson` (the `CMAKE_CUDA_ARCHITECTURES=87` pin, `-j2`).

## 3. Hardware and sim profiles in `planner_params.yaml`

Added `llm_resolver_node_py_hardware` and `semantic_goal_node_hardware` beside the existing
`llm_resolver_node_py` and `semantic_goal_node` blocks in the same file (PLAN.md's "both present
in `config/planner_params.yaml`"). Not wired into any launch file; Phase 10 decides how the
hardware profile is selected at launch time. The hardware block differs from the sim block in
exactly four resolver fields plus one `semantic_goal_node` field:

| field | sim | hardware |
|---|---|---|
| `n_threads` | 8 | 6 (conservative Orin NX 8 GB module core count; Phase 10 confirms the module and may raise to 8) |
| `timeout_ms` (resolver) | 300000 | 3000 (specification value, D54: internally set) |
| `backend` | `inprocess` | `http` |
| `backend_url` | `http://host.docker.internal:8080` | `http://127.0.0.1:8080` |
| `default_timeout_ms` (`semantic_goal_node`) | 300000 | 3000 |

Everything else (`model_path`, `grammar_on`, `fewshot_count`, `allow_none`, `text_anchor`,
`calibrator_path` left unset so it keeps the Phase 7 default) is identical on purpose: the
resolver's own behaviour should not change between simulation and hardware. Explicitly spelled
out `backend`/`backend_url` in the sim block too (previously implicit via the node's own
defaults) so the two blocks are directly comparable field by field.

`test_resolver_core_offline.py` gains three tests: both profiles load with the expected
hardware values, the hardware resolver profile's parameter set matches the sim one's exactly
except the four documented fields, and both `semantic_goal_node` variants load with their
expected timeouts. Host pytest: 31 passed (28 before, one of those three now split across the
new tests plus the two pre-existing new-default tests from 8D).

## 4. Nav2 hardware velocity variant

New `ros2_ws/src/safenav_sim/config/nav2_params_hardware.yaml`, a copy of `nav2_params.yaml`
with the Create 3 velocity limits reverted to the stock TurtleBot4 default of 0.26 m/s
(`FollowPath.max_vel_x`, `max_speed_xy`, and `velocity_smoother`'s linear `max_velocity`/
`min_velocity` entries), reversing D10 for hardware only. D10's reasoning (touring the 20x14 m
simulated facility at 0.5 m/s so a batch run finishes in reasonable time) does not apply to a
real robot. Nothing else in the file changed; `amcl`'s noise parameters stay loosened for the
loopback simulator's noise-free odometry even in the hardware copy, since real sensor noise is
not something this file can be correct about without a real SLAM map (`cannot-verify.md` item
1). New `test/python/test_nav2_params_hardware_profile.py` (3 tests): both profiles load, the
hardware velocity fields are exactly 0.26 (sim's are 0.5), and the two documents are identical
once the five velocity leaves are blanked out, so nothing else moved.

## 5. `docs/hardware/`

- `jetson-build.md`: prerequisites (JetPack 6, `nvidia-container-toolkit`, 40 GB free), the
  build command, an estimated build time, and the three failure modes named above.
- `bringup-checklist.md`: 11 items, each with a "Do" step and an "Evidence" citing a specific
  report/section/test, and a "Not verified" line naming the exact gap. Covers model load and
  CUDA offload, grammar identity across backends, the `/resolve_waypoint` contract, the BT
  plugin load path, the annotation graph against a fresh SLAM map, TF frames, the calibrator
  file, `/tts_text`, the latency gate, Create 3 velocity limits, and nav start latency.
- `cannot-verify.md`: 6 items (real sensor noise into AMCL, Create 3 docking, Orin thermal
  throttling, real human phrasing vs. persona-generated phrasing (D7), audio hardware for TTS,
  and the hardware latency gate itself), each with the specific reason simulation cannot reach
  it, not just that it is untested.

Every bring-up checklist item cites either a report/section or `cannot-verify.md`; none is left
unsourced (DoD).

## 6. `RESULTS.md` section 8

New "Hardware readiness" section: verified / argued / untested, one line per claim, pointing
back at the two new hardware docs rather than duplicating their detail.

## 7. Tests

```
cd ros2_ws/src/semantic_waypoint_planner && PYTHONPATH=. python3 -m pytest test/python/test_resolver_core_offline.py -q
# 31 passed

cd ros2_ws/src/safenav_sim && PYTHONPATH=. python3 -m pytest test/python -q
# 8 passed (5 existing, 3 new)
```

Run on the host conda env (`tf_env`), not inside the Docker container: these are pure-Python,
architecture-independent yaml/offline tests with no `rclpy` dependency, same as the precedent
set by `test_text_anchor_default_agrees_in_yaml_core_and_node` in 8D. `colcon build`/`colcon
test` inside the container were not run this phase: no C++ or launch-time code changed, only
config, docs, a Python ML script and host-level pytest files, so the build is unaffected.

## 8. What stands unchanged

`docker/Dockerfile` (the dev/sim image), `semantic_nav.launch.py`, `resolver_core.py`,
`llm_resolver.py`'s declared parameters, the BT plugin, the graph schema, and the calibrator
itself are all untouched. The sim profile's values in `planner_params.yaml` and
`nav2_params.yaml` are unchanged except for the explicit `backend`/`backend_url` spell-out
(section 3) and a one-line comment update at `max_vel_x` (pointing at the new hardware file
instead of saying "revisit... in Phase 10").

## 9. Deviations

D66 (JetPack 6 over JetPack 5 for `Dockerfile.jetson`'s base), recorded in PLAN.md section 14.

## 10. Open items for Phase 10

- Build `Dockerfile.jetson` on the real device; record what had to change.
- Measure resolver latency against a CUDA `llama-server` before any trial; `timeout_ms: 3000`
  is unvalidated (`cannot-verify.md` item 6, `bringup-checklist.md` item 9).
- Decide how the hardware profile (`llm_resolver_node_py_hardware`,
  `semantic_goal_node_hardware`, `nav2_params_hardware.yaml`) is selected at launch time; none
  of the three is wired into a launch file yet.
- Confirm the Orin NX module (6 vs. 8 core) and adjust `n_threads` if it is the 16 GB variant.
- Work through `bringup-checklist.md` top to bottom against the real robot.
