# SafeNav-LLM

Semantic waypoint resolution for ROS 2 Nav2: an on-device language model (Phi-3 mini Q4_K_M via
llama.cpp) resolves natural language commands such as "go to the room to the left of the
kitchen" into a named location from a closed, human curated annotation graph. The output is
constrained at the token sampler with a GBNF grammar (never a post-hoc regex), the resolution
runs inside a native Nav2 BehaviorTree plugin, and a calibrated confidence gate decides between
navigating and asking the operator to rephrase.

Current target: software simulation (TurtleBot4 in a loopback simulator, ROS 2 Humble) inside
Docker. Gazebo Fortress does not run in the container (D11, D30; see Limitations below); every
simulation result in this project is loopback. Hardware deployment on a TurtleBot4 with a Jetson
Orin NX is Phase 9/10.

## Documents

- `docs/PLAN.md`: the master build plan, phase by phase, with definitions of done, the recorded
  deviation log, and the metric gate provenance (section 1).
- `docs/results/RESULTS.md`: every measured number in the project, one table per phase, with the
  file each number traces back to.
- `docs/reference/`: the project specification, architectural analysis, and review reports.
- `docs/reports/`: per-phase build reports.
- `CLAUDE.md`: conventions for Claude Code sessions (workflow, git rules, environments).

## Quick start

```bash
docker/build.sh                                      # one time, builds safenav-llm:humble
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml exec dev bash

# inside the container
cd /ws/ros2_ws
colcon build --symlink-install
source install/setup.bash

ros2 launch semantic_waypoint_planner semantic_nav.launch.py
```

Desktop (RViz2) at http://localhost:6080. Models live in `models/` (see `docs/PLAN.md` Phase 0),
bind-mounted read-only into the container; never commit them.

In a second shell inside the same container:

```bash
ros2 run semantic_waypoint_planner say.py "go to the kitchen"
ros2 run semantic_waypoint_planner say.py "the room to the left of the kitchen"
```

`say.py` publishes a `SemanticGoal`, waits for the matching `/semantic_goal_result`, and prints
it as JSON (`resolved_room`, `raw_confidence`, `calibrated_confidence`, `nav_result`, `e2e_ms`).

### Using the host Metal backend instead of the container's CPU

The container has no GPU passthrough, so in-process inference there takes tens of seconds to
minutes per call (D16, D18). The measured and deployed path is `backend: http` against a
`llama-server` running on the macOS host with Metal (`docs/hardware/llama-server.md`):

```bash
# on the host, once llama-server is built (see docs/hardware/llama-server.md)
./third_party/llama.cpp/build/bin/llama-server \
  --model models/phi3-mini-4k-instruct.Q4_K_M.gguf --port 8080 --ctx-size 2048 -ngl 99

# in the container
ros2 launch semantic_waypoint_planner semantic_nav.launch.py \
  backend:=http backend_url:=http://host.docker.internal:8080
```

## Package tour

```
ros2_ws/src/semantic_waypoint_planner/
  msg/, srv/              SemanticGoal, ClarificationRequest, ResolveWaypoint, AddRoom,
                           ListRooms, GetRoomPose (frozen after Phase 1, PLAN.md section 12)
  src/annotation_map_node.cpp, annotation_graph.cpp
                           serves /get_room_pose, /add_room, /list_rooms, /semantic_markers
  src/bt_semantic_plugin.cpp, bt_speak_text.cpp
                           SemanticNavigateToPose (BT.CPP action node) and SpeakText, loaded by
                           bt_navigator through plugin_lib_names
  src/semantic_goal_node.cpp
                           operator-facing lifecycle node: /semantic_goal in, renders the per-
                           goal BT XML (D6), sends NavigateToPose, publishes /semantic_goal_result
  semantic_waypoint_planner/   ROS-free Python core (ament_python_install_package):
    graph.py               annotation graph, alias resolution, relation traversal index
    grammar.py              GBNF generation (v1 single-field, v2 relational, section 12.6)
    prompt.py                system/fewshot prompt construction
    resolver_core.py        ResolverCore: fast path, grammar decode, hop, calibration features
    relations.py             deterministic spatial hop over graph edges (Phase 5, D29)
    backends.py              InProcessBackend (llama-cpp-python) / HttpBackend (llama-server)
    calibrator.py            Platt-scaled logistic calibration, loaded from config/calibrator.json
  scripts/
    annotate_map.py          authors/validates room_annotations.json
    llm_resolver.py           rclpy node serving /resolve_waypoint
    say.py                    one-shot command CLI
    semantic_cli.py           resolver-only CLI with full JSON output (anchor_room, relation, ...)
    run_trials.py             Phase 8 e2e150 suite runner (drives the full ROS graph)
  behavior_trees/semantic_navigate_to_pose.xml
  maps/room_annotations.json  30 named locations, aliases, tags, parent, edges
  config/planner_params.yaml, config/calibrator.json, config/prompts/
  launch/semantic_nav.launch.py, resolver_only.launch.py
  test/                     gtest, launch tests, pytest wrapper (colcon test)

ros2_ws/src/safenav_sim/
  worlds/layout.yaml, scripts/gen_world.py     facility geometry, single source of truth
  maps/safenav_lab.yaml/.pgm                    rasterized occupancy grid
  src/loopback_sim_node.cpp                     unicycle integrator + ray-cast /scan (D30)
  config/nav2_params.yaml                       Nav2 params, raised velocity limits (D10)
  launch/sim.launch.py, loopback_sim.launch.py, nav.launch.py

ml/safenav_ml/            host-side tooling (conda env tf_env): dataset generation, prompt
                          study, benchmark runners, model ablation, calibration training,
                          metrics, e2e150 report, figures
data/
  benchmark/              synthetic_500.jsonl (original), synthetic_500_v2.jsonl (5A-corrected
                          labels, RELABEL.md), adversarial_50.jsonl, personas/
  calibration/            session1_sim.jsonl (200), session2_sim.jsonl (100)
  runs/, bags/            regenerable run output and ros2 bags (gitignored)
```

## Running the experiments

| Experiment | Command |
|---|---|
| Resolver-only CLI | `ros2 run semantic_waypoint_planner semantic_cli "go to the kitchen"` |
| Full 500 benchmark | `python3 ml/safenav_ml/run_phase5_benchmark.py --rows full --out data/runs/full500.jsonl` |
| Benchmark relabel | `python3 ml/safenav_ml/relabel_benchmark.py` (frozen rule, `data/benchmark/RELABEL.md`) |
| Calibrator training | `python3 ml/safenav_ml/train_calibrator.py` |
| Model ablation (3 models, full 500) | `python3 ml/safenav_ml/model_ablation.py` |
| e2e150 suite, production | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_loopback.jsonl --grammar-on --gate-threshold 0.85` |
| e2e150 suite, grammar off | add `--no-grammar-on` |
| e2e150 suite, gate off | `--gate-threshold 0.0` |
| e2e150 report | `python3 ml/safenav_ml/e2e_report.py --production data/runs/e2e150_loopback.jsonl --grammar-off data/runs/e2e150_grammar_off.jsonl --gate-off data/runs/e2e150_gate_off.jsonl --out docs/results/e2e150_report.md` |
| colcon tests | `colcon test --packages-select semantic_waypoint_planner --event-handlers console_direct+` |

## Results summary

See `docs/results/RESULTS.md` for the full set. Headline: resolver raw top-1 0.732 on the
corrected 500 benchmark (no gate, D45; derived ceiling about 0.81), gated end-to-end accuracy
0.72 (provisional, D53) against a literature-anchored target of 0.75, calibrated ECE 0.073
(<= 0.08, met), resolver latency p90 3497-4272 ms cold (target < 3000 ms, the one outstanding
gate miss).

## Limitations

- Loopback simulation only; Gazebo does not run in the container (D11, D30).
- Calibration trained on simulated Mistral-generated persona logs, not human sessions (D7).
- Top-3 ranking is a heuristic (inverse edit distance over the remaining probability mass), not
  a model score (D12).
- The deployed calibration feature vector has two of five features carrying no independent
  signal (D53); gated-accuracy and false-rejection numbers are provisional until PLAN.md section
  16A's fix lands.

See `docs/results/RESULTS.md` section 7 for the full discussion.
