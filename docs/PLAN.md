# SafeNav-LLM master build plan (v2)

Source of truth for building SafeNav-LLM from an empty repository to the simulation-complete
system described in `docs/reference/Review_2_Phase_2.docx` (specification) and
`docs/reference/SafeNav_Complete_Architectural_Analysis.pdf` (rationale). One phase per Claude
Code session. Each phase has a scope, the concrete deliverables, a definition of done (DoD)
that is verified by running commands, and a gate that must hold before the next phase starts.

**Plan version 2, 2026-10-13.** Phases 0 to 4 were built against plan v1, archived verbatim at
`docs/archive/PLAN-v1.md`. The back half was redrafted after Phase 4 closed below its accuracy
gate. Read `docs/archive/superseded-decisions.md` before Phase 5 if anything here contradicts
a phase 0 to 4 report. Section numbers 12 (interfaces), 13 (latency) and 14 (deviations) are
unchanged from v1 so that existing reports' cross-references still resolve.

Status legend: `[ ]` not started, `[~]` in progress, `[x]` merged to main.

| Phase | Name | Status | Issue | PR |
|-------|------|--------|-------|----|
| 0 | Scaffolding, environment, downloads | [x] | #1 | #2 |
| 1 | Interfaces and annotation map node | [x] | #3 | #4 |
| 2 | Simulation world, map, Nav2 bringup | [x] | #5 | #6 |
| 3 | LLM resolver prototype (Python, GBNF) | [x] | #9 | #10 |
| 4 | Synthetic benchmark and prompt sensitivity study | [x] | #14 | #15 |
| 5 | Relational decomposition and resolver backend | [ ] | | |
| 6 | BT plugin, semantic goal node, end to end in sim | [ ] | | |
| 7 | Confidence calibration pipeline | [ ] | | |
| 8 | E2E validation, ablations, final results | [ ] | | |
| 9 | Hardware readiness (no robot required) | [ ] | | |
| 10 | Hardware bring-up (deferred until hardware is present) | [ ] | | |

## Budget

Five phases remain, scoped to about **4.75 working days** of human time. Roughly four hours of
that is unattended background compute that overlaps with other work.

| Phase | Human time | Background compute |
|-------|-----------|--------------------|
| 5 Relational decomposition and backend | 1.5 d | ~1 h (benchmark reruns) |
| 6 BT plugin and E2E | 1.25 d | none |
| 7 Calibration | 0.75 d | ~20 min |
| 8 E2E validation and results | 0.75 d | ~3.5 h (300 loopback runs) |
| 9 Hardware readiness | 0.5 d | none |

Phase 9 is documentation and configuration only. If the week runs tight it can slip to a later
session without blocking anything, which puts the critical path at 4.25 days.

## 0. Ground rules that apply to every phase

- Target: software simulation, plus a hardware path that is proven feasible rather than
  assumed. Anything requiring the physical robot (Create3 topics, OAK-D, RPLiDAR, human
  participant sessions) is Phase 10.
- Everything ROS runs inside the Docker image `safenav-llm:humble` (see `docker/`). Host side
  Python tooling in `ml/` runs in the conda env `tf_env` on macOS with Metal acceleration.
- Follow `CLAUDE.md` for git workflow and commit conventions. One issue, one branch, one PR per phase.
- Every phase ends with `docs/reports/phase-N-<slug>.md` containing: what was built, how it was
  verified (commands and outputs), measured numbers, deviations, open risks for the next phase.
- Never modify Nav2 source. The package must install with `colcon build` on a stock Humble system.
- Interfaces (section 12) are frozen after Phase 1. Extending with new fields is allowed only by
  appending and recording the change in section 14. The GBNF grammar (12.6) is generated, not an
  interface, and may change with a recorded deviation; `ResolveWaypoint.srv` (12.2) may not.
- Do not tick a DoD item you did not run.

## 1. System summary (what the finished simulation delivers)

Operator command (text) -> `/semantic_goal_node` (lifecycle node, validates, renders the BT XML
with the command and sends a Nav2 `NavigateToPose` goal) -> Nav2 `bt_navigator` ticks
`SemanticNavigateToPose` (C++ BT plugin) -> plugin calls `/list_rooms` then `/resolve_waypoint`
-> `/llm_resolver_node_py` (Phi-3 mini Q4_K_M, GBNF grammar built from the annotation graph,
fast path for exact alias matches, **relational decomposition against the graph**, calibrator
producing `calibrated_confidence`) -> `/annotation_map_node` gives the `PoseStamped` for the
chosen canonical name -> plugin writes `resolved_pose` to the blackboard and returns SUCCESS
(or FAILURE on timeout or below threshold, triggering the clarification fallback subtree with
TTS) -> `ComputePathToPose` and `FollowPath` drive the simulated TurtleBot4 to the room
-> every run is logged to a ros2 bag and a JSONL run record.

Inference reaches the model through a `backend` parameter: `inprocess` (llama-cpp-python) for
host development and unit tests, `http` (llama.cpp `llama-server`, same GGUF, same GBNF) for
batch runs and for hardware. See section 13.

### Targets

Accuracy is stated at two levels, because abstention on adversarial commands is the
calibrator's job and not the resolver's (see `docs/archive/superseded-decisions.md` S6).

| Metric | Target | Phase |
|--------|--------|-------|
| Resolver raw top-1, 500 pair benchmark, gate disabled | >= 0.80 | 5 |
| Resolver top-3, 500 pair benchmark | >= 0.88 | 5 |
| Gated end-to-end accuracy, 500 pair benchmark (correct abstention counts as correct) | >= 0.85 | 7 |
| Out of graph output rate, grammar on | 0% (structural) | 5, 8 |
| Out of graph output rate, grammar off | report as measured (D24: 1.0% at Phase 4) | 8 |
| ECE, calibrated confidence (sim eval set) | <= 0.08 (CV gate <= 0.10) | 7 |
| False pass rate (sim eval set) | <= 5% | 7 |
| False rejection rate (sim eval set) | <= 15% | 7 |
| Resolver latency p90 | < 3000 ms on the Metal backend (section 13) | 5, 8 |
| 150 run E2E sim validation, grammar on | 0 out of graph outputs | 8 |

## 2. Repository layout (final state)

```
CLAUDE.md
README.md
docs/
  PLAN.md                          this file (v2)
  archive/                         PLAN-v1.md, superseded-decisions.md, README.md
  reference/                       original project documents
  reports/phase-N-<slug>.md        one per phase
  results/                         final figures and tables (Phase 8)
  hardware/                        Jetson build recipe and bring-up checklist (Phase 9)
docker/
  Dockerfile  docker-compose.yml  build.sh  requirements.txt  ros_entrypoint.sh
  Dockerfile.jetson                written and reviewed in Phase 9, built in Phase 10
ros2_ws/src/
  semantic_waypoint_planner/
    CMakeLists.txt  package.xml  plugin_description.xml
    msg/SemanticGoal.msg  msg/ClarificationRequest.msg
    srv/ResolveWaypoint.srv  srv/AddRoom.srv  srv/ListRooms.srv  srv/GetRoomPose.srv
    include/semantic_waypoint_planner/*.hpp
    src/annotation_map_node.cpp   src/annotation_graph.cpp
    src/bt_semantic_plugin.cpp    src/bt_speak_text.cpp     src/semantic_goal_node.cpp
    semantic_waypoint_planner/    ROS free Python core:
                                    graph.py  prompt.py  grammar.py  resolver_core.py
                                    relations.py  backends.py  calibrator.py
    scripts/annotate_map.py  scripts/llm_resolver.py  scripts/semantic_cli.py
    scripts/run_trials.py    scripts/parity_check.py  scripts/say.py
    behavior_trees/semantic_navigate_to_pose.xml
    config/planner_params.yaml  config/calibrator.json  config/prompts/*.txt
    maps/room_annotations.json
    launch/semantic_nav.launch.py  launch/resolver_only.launch.py
    test/
  safenav_sim/
    worlds/safenav_lab.sdf  worlds/layout.yaml  scripts/gen_world.py
    maps/safenav_lab.yaml  maps/safenav_lab.pgm
    config/nav2_params.yaml
    launch/sim.launch.py  launch/loopback_sim.launch.py  launch/nav.launch.py
    src/loopback_sim_node.cpp
ml/
  requirements-host.txt
  safenav_ml/  (dataset generation, prompt study, calibration training, metrics, plots)
  tests/
data/
  benchmark/synthetic_500.jsonl  benchmark/adversarial_50.jsonl  benchmark/personas/
  calibration/session1_sim.jsonl  calibration/session2_sim.jsonl
  runs/ (ignored)  bags/ (ignored)
models/  *.gguf (ignored)
third_party/llama.cpp (ignored)
```

Note what is absent relative to v1: `src/llm_resolver_node.cpp`, `src/calibrator.cpp`,
`src/grammar_builder.cpp`, `src/fast_path.cpp`. The resolver stays in Python (D27). The C++ in
the package is the annotation map node, the BT plugin, and the semantic goal node.

## 3. Phase 0: scaffolding, environment, downloads

Status: `[x]`, merged (#2). Report: `docs/reports/phase-0-scaffolding-environment.md`.
Full original scope text: `docs/archive/PLAN-v1.md` section 3.

Built the two stage Docker image (`safenav-llm:core` and `safenav-llm:humble` with the
TurtleBot4 simulation overlay at `/opt/sim_ws` vendored from source for arm64), downloaded the
three GGUF models, extended the host conda env, and established the repo layout and conventions.

## 4. Phase 1: interfaces and annotation map node

Status: `[x]`, merged (#4). Report: `docs/reports/phase-1-interfaces-annotation-map.md`.
Full original scope text: `docs/archive/PLAN-v1.md` section 4.

Froze the section 12 interfaces, built `annotation_map_node` (rclcpp) with `/get_room_pose`,
`/add_room`, `/list_rooms`, `/semantic_markers` and `/annotation_graph_updated`, authored
`room_annotations.json` with 30 named locations and their aliases, tags, parents and edges, and
the ROS free `graph.py` core.

**Carried into Phase 5:** the `edges` list in `room_annotations.json` was authored for prompt
rendering, not for programmatic traversal. Phase 5 audits it. See section 8.

## 5. Phase 2: simulation world, map, Nav2 bringup

Status: `[x]`, merged (#6). Report: `docs/reports/phase-2-sim-world-nav2-bringup.md`.
Full original scope text: `docs/archive/PLAN-v1.md` section 5.

Built `safenav_sim`: the 20 x 14 m ten room world generated from `layout.yaml`, the rasterized
map, Nav2 params for the TB4, and the loopback simulator (unicycle integrator, ray cast
`/scan`, identity `map -> odom`). The ten room tour passes 10 of 10 in loopback.

**Gazebo does not work in the container (D11)** and is not pursued further: robot spawn
segfaults the Ignition server in its software renderer. Loopback is the only simulation mode
for the rest of the plan (D30). The packaging bug found in `turtlebot4_ignition_bringup` along
the way is documented in the phase 2 report.

## 6. Phase 3: LLM resolver prototype (Python, GBNF grammar)

Status: `[x]`, merged (#10). Report: `docs/reports/phase-3-llm-resolver-prototype.md`.
Full original scope text: `docs/archive/PLAN-v1.md` section 6.

Built the ROS free resolver core (`prompt.py`, `grammar.py`, `resolver_core.py`) and the rclpy
node serving `/resolve_waypoint` with the fast path, grammar constrained decoding, prefix KV
caching, the five calibration features, and inference off the executor thread. Metal p50/p90
2874 / 3678 ms; container CPU tens of seconds to minutes (D16, D18).

**Carried into Phase 5:** D12 (ranking and entropy are heuristic, not model scores), D14
(`n_gpu_layers`), D18 (the 300 s sim timeout).

## 7. Phase 4: synthetic benchmark and prompt sensitivity study

Status: `[x]`, merged (#15). Report: `docs/reports/phase-4-prompt-study.md`.
Full original scope text: `docs/archive/PLAN-v1.md` section 7. Brief: `docs/phase-4-brief.md`.

Built the 500 pair benchmark and the 50 adversarial set, ran the 24 condition grid (screened on
a stratified 64 pair subsample, D19), added baselines B0 to B4b, and selected the production
configuration: `fewshot_count=0`, `temperature=0.3`, grammar on.

**Closed below its gate at top-1 0.662 (D26).** The shortfall is almost entirely in three
categories, and this is what Phase 5 exists to fix:

| category | n | top-1 | correct |
|----------|---|-------|---------|
| negation | 65 | 0.969 | 63 |
| alias | 65 | 0.954 | 62 |
| direct | 65 | 0.923 | 60 |
| abbreviation | 65 | 0.862 | 56 |
| functional | 65 | 0.692 | 45 |
| **adversarial** | 45 | **0.400** | 18 |
| **spatial** | 65 | **0.262** | 17 |
| **multi_hop** | 65 | **0.154** | 10 |
| total | 500 | 0.662 | 331 |

Error analysis (phase 4 report section 4.2) found the model answering a fixed room regardless
of the referent on spatial commands: it was not traversing the adjacency block in the prompt.
Two prompt iterations were tried; the more elaborate one made it worse.

## 8. Phase 5: relational decomposition and resolver backend

Status: `[x]`, merged (#17).
Report: `docs/reports/phase-5-relational-decomposition-resolver-backend.md`.

Goal: recover resolver accuracy to the 0.80 gate by moving graph traversal out of the model and
into code, and put inference behind a backend seam that deploys unchanged to the Jetson.

**Closed below its own stop threshold at top-1 0.560 (D32), well under the 0.74-0.80 band.**
The backend seam, grammar, and relations.py are all verified correct; the shortfall is the
model's handling of the two-field contract itself (see the report's error analysis), carried
into Phase 8 as an open risk rather than fixed by a fourth prompt iteration.

Replaces v1's C++ resolver phase entirely (D27, and `superseded-decisions.md` S1).

### 8.1 Relational decomposition

The model stops being asked to traverse. It names the location the command refers to and the
spatial relation the command uses. Traversal is a deterministic lookup over `edges`.

- `grammar.py`: extend the generated GBNF to section 12.6's v2 form, adding a `relation` field
  over the closed set `none | left_of | right_of | adjacent | near | within`. `none` means the
  current behaviour: `room` is the answer. Anything else means `room` is the **anchor** and the
  answer is the hop target. The output stays closed set and structurally guaranteed.
- `relations.py` (new): the traversal and its disambiguation policy.
  - `resolve_relation(graph, anchor, relation, command) -> (name | None, n_targets)`.
  - `within` resolves to the anchor's `parent`, which covers "the room with the coffee machine".
  - Exactly one target: that is the answer.
  - Zero targets: abstain, answer `none`. Never guess a sibling.
  - More than one target: disambiguate by alias and tag overlap with the normalized command; if
    still tied, abstain. Return `n_targets` either way so Phase 7 can use it.
- `resolver_core.py`: apply the hop after decoding, before the pose lookup. `ResolveResult`
  gains `anchor_room`, `relation`, `n_relation_targets` (Python internal, not an interface).
  `matched_room_name` in the service response is still the single final room.
- `prompt.py`: the system template documents the two field contract and the relation vocabulary
  with two or three worked examples. Keep it short. Phase 4 established that elaborate rule
  blocks hurt this model (v2 template, rejected).

**Edge coverage audit, do this first.** `room_annotations.json`'s `edges` were authored in
Phase 1 to render adjacency sentences into a prompt, not to be traversed. Before writing the
decomposition, check and fix:

- every relation used by the benchmark's `spatial` and `multi_hop` rows has edges that support it;
- inverse edges are materialized (`A left_of B` implies `B right_of A`; `adjacent` and `near`
  are symmetric) either in the file or in `graph.py` at load time, with a unit test;
- sub locations have correct `parent` values, since `within` depends on them.

Report the audit as a table: relation, edges before, edges after, benchmark rows it serves. If
the graph turns out to be the limiting factor rather than the model, say so plainly, because
that changes the conclusion of the whole phase.

### 8.2 Backend seam

- `backends.py` (new): `InProcessBackend` (llama-cpp-python, current behaviour) and
  `HttpBackend` (llama.cpp `llama-server`, POST `/completion` with the identical GBNF string in
  the `grammar` field, `temperature`, `n_predict`). One interface:
  `complete(prompt, grammar, **params) -> (text, timing, prompt_eval_tokens)`.
- Resolver parameter `backend` (`inprocess` default) and `backend_url`
  (default `http://host.docker.internal:8080`).
- `docs/hardware/llama-server.md`: how to start the server on the macOS host with Metal, and
  the equivalent Jetson CUDA invocation (the flags only, the Jetson build lands in Phase 9).
- The container's `/etc/hosts` route to the host must be verified from inside the container,
  not assumed.

### 8.3 Model check

Pull the Phi-3.5 mini row of v1's Phase 9 forward. Run the production configuration on the full
500 with `models/phi3.5-mini-instruct.Q4_K_M.gguf`. If it beats Phi-3 mini by more than 2
points, promote it to production and note it; the remaining ablation rows stay in Phase 8.

### 8.4 Measurement honesty

Two prompt iterations have already been run against this same 500 (phase 4 section 4.2). This
phase makes a third change informed by per-category error analysis, which is tuning on the test
set unless handled.

- Develop the decomposition against the `spatial` + `multi_hop` hard subset only.
- Before the full 500 run, freeze the implementation.
- Validate on `data/benchmark/adversarial_50.jsonl` (untouched since Phase 4) and on a
  deterministic held-out 100 row slice of the 500 that is reported separately.
- The report states the exposure in one short paragraph. A Review 2 panel will ask.

### DoD

- [ ] Edge coverage audit table in the report; inverse edge materialization unit tested.
- [ ] GBNF v2 accepts every `(canonical, relation)` pair and rejects everything else
      (extend the existing Phase 3 grammar test).
- [ ] `relations.py` unit tested on the full hop matrix including the zero target and multi
      target abstention paths.
- [ ] Backend parity: 100 benchmark commands, `inprocess` vs `http`, same model, temperature 0,
      agreement >= 99%. Any disagreement explained.
- [ ] Full 500, production configuration, grammar on: **top-1 >= 0.80**, top-3 >= 0.88,
      out of graph rate 0.0.
- [ ] Per category floors that make the total reachable: `spatial` >= 0.80, `multi_hop` >= 0.65,
      `functional` >= 0.75, and no regression below 0.85 on `direct`, `alias`, `negation`,
      `abbreviation`.
- [ ] Held-out 100 row slice and `adversarial_50.jsonl` reported separately from the headline.
- [ ] Latency on the Metal backend: p50, p90, p99 over 100 calls, p90 < 3000 ms. Container CPU
      number reported alongside per section 13.
- [ ] `semantic_cli "the room to the left of the kitchen"` returns the correct room via the hop,
      with `relation` and `anchor_room` visible in the JSON output.
- [ ] Phi-3.5 comparison row recorded; production model stated explicitly.
- [ ] Report written, PR merged.

**If top-1 lands between 0.74 and 0.80**, that is still a large improvement over 0.662. Merge
with a documented analysis of which categories fell short and why, and carry the gap into the
Phase 8 results. **Below 0.74**, the decomposition did not work as designed: stop, report the
error analysis, and do not start a fourth prompt iteration. The arithmetic to watch mid-phase
is in section 7's table, where 400 of 500 is the 0.80 gate.

Gate: resolver raw top-1 >= 0.80, or a documented shortfall with the band above respected.

## 9. Phase 6: BT plugin, semantic goal node, end to end in simulation

Goal: `SemanticNavigateToPose` as a native Nav2 BT node, the operator facing goal node, the
fallback subtree, and the first full command to navigation runs. Loopback only (D30).

Scope is unchanged from v1 section 9 except that Gazebo DoD items are removed and the resolver
behind the service is the Python node. Summarized here; consult `docs/archive/PLAN-v1.md`
section 9 for the full original prose.

- `src/bt_semantic_plugin.cpp`: `semantic_waypoint_planner::SemanticNavigateToPose :
  public BT::ActionNodeBase` (BehaviorTree.CPP v3). Input ports `command`,
  `confidence_threshold` (default 0.72), `timeout_ms`; output ports `resolved_pose`,
  `resolved_room`, `calibrated_confidence`. tick(): read command, empty -> FAILURE; call
  `/list_rooms` (200 ms budget); send `/resolve_waypoint` and wait on the future with
  `timeout_ms` on a private callback group executor; timeout -> `ClarificationRequest`
  (`reason="timeout"`) and FAILURE; at or above threshold with success -> set ports, SUCCESS;
  otherwise `ClarificationRequest` (`low_confidence` or `unresolved`) and FAILURE. `halt()`
  cancels the pending future. `BT_REGISTER_NODES(factory)` plus `plugin_description.xml`.
- `src/bt_speak_text.cpp`: `SpeakText` sync action publishing `std_msgs/String` on `/tts_text`.
  The `espeak-ng` subprocess and the `/cmd_lightring` pattern are optional; wire the topic
  first and only add them if the phase is running ahead.
- `behavior_trees/semantic_navigate_to_pose.xml`: Sequence of `SemanticNavigateToPose` then the
  stock Nav2 navigate subtree on `{resolved_pose}`, wrapped in a Fallback whose second branch
  is `SpeakText` with the clarification text.
- `src/semantic_goal_node.cpp` (`rclcpp_lifecycle::LifecycleNode`): subscribes `/semantic_goal`,
  validates, renders the BT XML with the command as a port literal (XML escaped) to
  `data/runs/bt/<timestamp>.xml`, sends `NavigateToPose` with `behavior_tree` set to that path
  (D6). Subscribes `/clarification_request` and republishes a human readable string on
  `/tts_text`. Publishes `/semantic_goal_result` JSON per goal.
- `safenav_sim/config/nav2_params.yaml`: add `semantic_waypoint_planner` to
  `bt_navigator.plugin_lib_names`.
- `launch/semantic_nav.launch.py`: annotation node, resolver, semantic goal node, loopback sim,
  Nav2. `scripts/say.py` for operator commands.

### DoD

- [ ] `ros2 param get /bt_navigator plugin_lib_names` includes `semantic_waypoint_planner`,
      no plugin load error in the log.
- [ ] `say "go to the kitchen"` reaches the kitchen pose (distance < 0.5 m),
      `/semantic_goal_result` shows `nav_result: succeeded`.
- [ ] A relational command (`say "the room to the left of the kitchen"`) navigates to the
      correct room end to end, exercising the Phase 5 hop through the full stack.
- [ ] `say "go to the cafeteria"` yields FAILURE, a `ClarificationRequest`, a `/tts_text`
      message listing rooms, and `/cmd_vel` stays zero.
- [ ] Timeout path: resolver stopped, `say` returns within `timeout_ms + 500 ms` with
      `reason: timeout`, robot does not move.
- [ ] No `bt_loop_duration` warnings beyond the resolution tick.
- [ ] Launch test covering success, low confidence, and timeout paths.
- [ ] Report written, PR merged.

Gate: end to end command to navigation works in loopback with fallback behaviours.

## 10. Phase 7: confidence calibration pipeline

Goal: the five feature Platt scaled logistic regression trained on simulated deployment logs,
loaded by the resolver, with ECE, the safety threshold, and the gated accuracy headline.

Scope is unchanged from v1 section 10 except as noted. Full prose: `docs/archive/PLAN-v1.md`
section 10.

- `ml/safenav_ml/gen_personas.py`: two disjoint command sets via the Mistral API from five non
  expert personas. Session 1 is 5 x 40 = 200 (training), session 2 is 5 x 20 = 100 (evaluation).
  No overlap with each other or the 500 benchmark, checked by normalized equality and fuzzy
  threshold. Committed to `data/calibration/`.
- `scripts/run_trials.py`: replays a command file through `/semantic_goal` with the gate
  disabled in loopback mode, recording the section 12.9 run record. **Run with `backend:=http`
  against the host Metal server**, which is what makes this phase fit in a morning.
- `calibrator.py` (Python, not the v1 `calibrator.cpp`): loads `config/calibrator.json`,
  computes the five section 12.8 features, outputs `calibrated_confidence`. Identity when the
  file is absent. The v1 C++ versus sklearn parity test is replaced by a Python versus sklearn
  test asserting agreement within 1e-6 on 20 exported vectors (D27).
- `ml/safenav_ml/train_calibrator.py`: `StandardScaler` plus `LogisticRegression`, 5 fold leave
  one persona out CV, ECE (10 equal width bins), Brier, reliability diagram, isotonic variant
  for comparison only. Threshold is the lowest value achieving false pass <= 5% on session 1 out
  of fold predictions. Writes `config/calibrator.json` and `docs/results/calibration_session1.png`.
- Evaluate on session 2 with the calibrator loaded. Do not tune on session 2.
- **New in v2:** compute and report **gated end-to-end accuracy on the 500 benchmark**, where a
  correct abstention on an adversarial row counts as correct. This is the section 1 >= 0.85
  target and the number the specification's metrics table wants. Report it beside the Phase 5
  raw top-1 so the contribution of the gate is visible.
- Keep the feature vector at the five of section 12.8. `n_relation_targets` from Phase 5 is an
  obvious sixth feature; try it only as a reported variant, and do not change 12.8.

### DoD

- [ ] Session 1 and 2 files exist with 200 and 100 rows, disjoint from each other and the benchmark.
- [ ] `train_calibrator.py` writes `config/calibrator.json`; CV ECE <= 0.10 recorded.
- [ ] Session 2: false pass <= 5%, false rejection <= 15%, calibrated ECE reported (target <= 0.08;
      if not met, report and analyze, do not tune on session 2).
- [ ] Gated end-to-end accuracy on the 500 benchmark reported; target >= 0.85.
- [ ] `semantic_cli` shows `calibrated_confidence != raw_confidence` and `calibrator_loaded: true`.
- [ ] Python calibrator versus sklearn parity test passes.
- [ ] Reliability diagram and metrics table committed. Report written, PR merged.

Gate: calibrator deployed in the resolver; threshold fixed in `planner_params.yaml`.

## 11. Phase 8: end to end validation, ablations, final results

Goal: the 150 run validation, the grammar ablation, the model ablation, and the consolidated
results document. Merges v1 Phases 8 and 9 (D31).

- `scripts/run_trials.py --suite e2e150`: 10 rooms x 5 phrasing variants x 3 trials with the
  full system, gate on, loopback. Variants drawn from the benchmark categories, and the set
  must include `spatial` so the Phase 5 hop is exercised end to end. Records an mcap bag per
  batch (`/semantic_goal`, `/clarification_request`, `/cmd_vel`, `/odom`, `/tts_text`; service
  traffic comes from the resolver JSON log) plus the section 12.9 JSONL record per run.
- Grammar ablation: the same 150 commands with `grammar_on:=false`. Record out of graph rate,
  top-1, false pass. D24 applies: the expected rate is about 1%, not the 5% v1 assumed.
- Gate ablation: the same 150 with threshold 0.0, giving the specification's Condition B versus
  Condition C comparison.
- Model ablation: production configuration on the 500 benchmark with Phi-3 mini Q4_K_M,
  TinyLlama 1.1B Q4_K_M and Phi-3.5 mini Q4_K_M (top-1, top-3, out of graph, p50, p90, RSS).
  The Phi-3.5 row may be reused from Phase 5. Optional cloud ceiling row if a key is present.
- `ml/safenav_ml/e2e_report.py`: success rate, false start rate, time to navigation start p50
  and p90, end to end latency p50/p90/p99, resolver latency p50/p90/p99, out of graph counts.
  Tables and plots into `docs/results/`.
- `docs/results/RESULTS.md`: every table from Phases 4, 5, 7, 8 with figures, the specification's
  evaluation metrics table filled in, and an explicit limitations section naming the Gazebo gap
  (D11, D30), the simulated rather than human calibration logs (D7), and the heuristic ranking
  behind top-3 (D12).
- `README.md`: architecture overview, quick start (Docker, build, launch, one `say` command),
  package tour, results summary, limitations, how to run every experiment.

### DoD

- [ ] 150 loopback runs completed, `data/runs/e2e150_loopback.jsonl` has 150 rows, bag path recorded.
- [ ] Grammar on: 0 out of graph outputs across all runs.
- [ ] Grammar off: out of graph rate reported as measured.
- [ ] Gate on versus gate off task success and false start rates reported on the same 150 commands.
- [ ] Resolver p90 reported for the Metal backend and the container CPU backend (section 13).
- [ ] Model ablation table with at least three models, latency and memory columns.
- [ ] `docs/results/RESULTS.md` complete; every number traceable to a JSONL or CSV in `data/`.
- [ ] README quick start verified literally from a clean container.
- [ ] Report written, PR merged.

Gate: core safety claim demonstrated in simulation; results document complete.

## 12. Interface and data contracts (frozen after Phase 1)

### 12.1 SemanticGoal.msg
```
std_msgs/Header header
string command
float32 confidence_threshold   # default 0.72, 0.0 disables the gate
bool allow_approximate         # if true, nearest matching room acceptable
```

### 12.2 ResolveWaypoint.srv
```
# Request
string natural_language_command
string[] candidate_room_names
---
# Response
geometry_msgs/PoseStamped resolved_pose
string matched_room_name
float32 raw_confidence
float32 calibrated_confidence
string reasoning               # LLM chain of thought or error reason, logged to ros2 bag
bool success
# Extension fields (recorded deviation D3)
float32 token_entropy          # nats, room level distribution
float32 inference_ms
string resolver_mode           # fast_path | llm_grammar | llm_free
bool out_of_graph              # true only in llm_free mode when the name is not in the graph
bool calibrator_loaded
string[] top_k_rooms           # ranking, best first, at most 5
float32[] top_k_scores
```
Unchanged in v2. The relational decomposition of Phase 5 is internal to the resolver: this
service still returns one final `matched_room_name`.

### 12.3 AddRoom.srv
```
string name
string[] aliases
geometry_msgs/Pose pose
string[] tags
string parent                  # optional floor or zone
---
bool success
string message
```

### 12.4 ListRooms.srv and GetRoomPose.srv
```
# ListRooms
---
string[] canonical_names
string[] all_aliases           # flat list across all rooms

# GetRoomPose
string name
---
geometry_msgs/PoseStamped pose
bool found
```

### 12.5 ClarificationRequest.msg
```
std_msgs/Header header
string command
string resolved_room
float32 calibrated_confidence
string reason                  # low_confidence | timeout | unresolved | empty_command
string[] known_rooms
```

### 12.6 GBNF grammar (generated from canonical names, sorted)

**v2 form, revised in Phase 5 (D29).** The grammar is generated, not an interface, so this may
change with a recorded deviation; 12.2 may not.

```
root ::= "{" ws "\"room\"" ws ":" ws room-value ","
         ws "\"relation\"" ws ":" ws relation-value ","
         ws "\"confidence\"" ws ":" ws confidence-value ws "}"
room-value     ::= "\"charging_dock\"" | "\"kitchen\"" | "\"server_room\"" | ... [ | "\"none\"" when allow_none ]
relation-value ::= "\"none\"" | "\"left_of\"" | "\"right_of\"" | "\"adjacent\"" | "\"near\"" | "\"within\""
confidence-value ::= [0-9] "." [0-9] [0-9]
ws ::= [ \t\n]*
```

Semantics: `relation == "none"` means `room` is the answer (v1 behaviour). Otherwise `room` is
the anchor and the answer is the hop target computed by `relations.py` against `edges`, with
abstention on zero or ambiguous targets. The output set stays closed either way.

The v1 form is preserved in `docs/archive/PLAN-v1.md` section 12.6 and is what Phases 3 and 4
measured.

### 12.7 room_annotations.json schema
```
{
  "version": 1,
  "facility": "safenav_lab",
  "frame": "map",
  "rooms": [
    {"name": "charging_dock", "aliases": ["charging station", "dock", "charger", "power point"],
     "pose": {"x": 3.2, "y": -1.1, "theta": 1.57, "frame": "map"},
     "tags": ["utility", "maintenance"], "parent": "lab_floor_1"}
  ],
  "edges": [ {"from": "charging_dock", "to": "server_room", "relation": "adjacent"} ]
}
```
Names: lowercase snake case, unique; aliases: lowercase, unique across the file; theta in radians.

Phase 5 may add edges and fix `parent` values during the coverage audit (section 8.1). It may
not rename or remove any canonical name, which has been frozen since Phase 1.

### 12.8 Calibration features and calibrator.json
Feature vector, in this order:
1. `raw_confidence` (float from the JSON output, 0.00 to 0.99)
2. `token_entropy` (nats, room level distribution, 0 on fast path)
3. `n_candidates` (number of canonical names offered)
4. `command_length` (characters after whitespace normalization)
5. `edit_distance` (minimum Levenshtein distance between the resolved canonical name with underscores
   replaced by spaces, or any of its aliases, and any window of the normalized command of the same
   length; 0 when contained verbatim)

```
{"version": 1, "type": "platt_logistic", "trained_on": "session1_sim", "date": "YYYY-MM-DD",
 "feature_names": [...5...], "scaler_mean": [..5..], "scaler_scale": [..5..],
 "weights": [..5..], "bias": 0.0, "threshold": 0.72,
 "metrics": {"cv_ece": 0.0, "brier": 0.0, "false_pass_at_threshold": 0.0}}
```
`p = sigmoid(sum(w_i * (x_i - mean_i) / scale_i) + bias)`.

Unchanged in v2. On a relational resolution, `edit_distance` is computed against the **final**
room, not the anchor.

### 12.9 Run record (JSONL, one per trial)
`run_id, timestamp, suite, sim_mode, command, intended_room, resolved_room, raw_confidence,
calibrated_confidence, token_entropy, n_candidates, command_length, edit_distance, resolver_mode,
grammar_on, gate_threshold, bt_status, clarification_reason, nav_result, t_command, t_resolved,
t_nav_start, t_nav_end, resolver_ms, e2e_ms, pose_x, pose_y, pose_theta, reached_intended,
out_of_graph`

Phase 5 appends `anchor_room, relation, n_relation_targets, backend` (recorded in D29/D27).

## 13. Latency policy (backends, container, hardware)

Measured in Phase 0 with Phi-3 mini Q4_K_M (`llama-bench`, 8 threads), and in Phase 3 with the
real 900 to 1000 token production prompt:

| Where | One resolution, production prompt |
|-------|-----------------------------------|
| Docker container, CPU only, arm64 VM | tens of seconds to minutes (D16, D18) |
| macOS host, Metal (llama-cpp-python or llama-server) | p50 2874 ms, p90 3678 ms (Phase 3) |
| Jetson Orin NX, CUDA (expected, specification) | about 0.7 s |

The container's CPU is 5 to 10 times slower than the deployment target and cannot meet p90 <
3000 ms. v2 resolves this with the backend seam rather than by discounting the number:

- **`backend: http` is the measured and deployed path.** In simulation the ROS node in the
  container talks to a `llama-server` with Metal on the macOS host. On hardware the ROS node on
  the Jetson talks to a `llama-server` with CUDA on localhost. Same code, same grammar, one URL
  of difference. The p90 < 3000 ms gate is judged here.
- **`backend: inprocess` stays the default for host unit tests** and remains a supported
  configuration. The container CPU inprocess number is still reported in every latency table,
  next to the backend number, with the explanation above. It is a property of an arm64 VM
  without GPU passthrough, not of the design.
- Localhost or host-loopback HTTP adds about 1 ms against a 2000 to 3000 ms resolution. Measure
  it once in Phase 5 and report it rather than assuming it.
- Required mitigations regardless of backend: prefix KV caching of the system prompt,
  `n_threads` set to all cores, the fewest few shot examples that keep accuracy within 2 points
  of the best (Phase 4 selected zero), and `max_tokens` bounded by the grammar.
- Profiles in `config/planner_params.yaml`: the **sim** profile keeps `timeout_ms: 300000`
  (D18) so a container CPU fallback cannot wedge a batch run; the **hardware** profile uses the
  specification's `3000`. Phase 9 writes the hardware profile.
- The fast path must resolve in under 5 ms and its hit rate on the benchmark is reported.

## 14. Recorded deviations from the specification

D1 to D26 were recorded during Phases 0 to 4 and are unchanged. D27 to D31 are the v2 replan.

- D1: Gazebo Fortress instead of Gazebo Harmonic. Reason: the official TurtleBot4 simulator pairs
  ROS 2 Humble with Fortress; Harmonic is only paired with Jazzy. Humble matches the Jetson.
- D2: Benchmark and persona datasets are generated with the Mistral API (`ministral-14b-latest`,
  the largest model on the free tier; chosen over the Anthropic API on cost after Phase 3; see
  `docs/phase-4-brief.md`) instead of the GPT-4 API. Reported in the dataset card.
- D3: `ResolveWaypoint.srv` response extended with entropy, timing, mode, ranking, and flags
  (section 12.2) so the calibration features and the ablation metrics come from the service itself.
- D4: A `"none"` abstention value is allowed in the grammar (configurable, default on). The output
  is still closed set; `none` never maps to a pose and always yields FAILURE.
- D5: A loopback simulator complements Gazebo for batch runs; the 150 run validation is executed
  in loopback mode. (Superseded in part by D30: loopback is now the only mode.)
- D6: The command string reaches the BT through a per goal rendered BT XML with the command as a
  port literal, because `NavigateToPose` carries no string field.
- D7: Calibration in this build is trained on simulated persona logs, not human sessions. Human
  sessions and hardware are Phase 10.
- D8: Phi-3.5 mini ablation model is Q4_K_M, not Q8 (disk budget). Cloud ceiling row replaced by
  a Mistral API row (realized in Phase 4 as B4 and B4b).
- D9: `/semantic_markers` publishes one `TEXT_VIEW_FACING` marker per room, not the text plus
  arrow pair described in Phase 1's prose, so the marker count matches the DoD assertion exactly.
- D10: TurtleBot4 Nav2 velocity limits in `safenav_sim/config/nav2_params.yaml` were raised from
  the stock 0.26 m/s to 0.5 m/s so the 10 room loopback tour meets the Phase 2 five minute DoD
  target. Simulation only; the hardware profile uses the real Create 3 limit.
- D11: Gazebo Fortress could not be brought up with a spawned TurtleBot4 in the container: the
  world loads and is stable, but robot spawn (lidar and depth camera sensor creation) segfaults
  the Ignition server in its software (Ogre2 on llvmpipe) renderer. See
  `docs/reports/phase-2-sim-world-nav2-bringup.md`, which also documents a packaging bug found
  and fixed in `turtlebot4_ignition_bringup`'s `ignition.launch.py`.
- D12: the Phase 3 resolver's room level ranking and entropy do not use batched multi sequence
  scoring or a next token grammar masked distribution; both need `logits_all=True` in
  llama-cpp-python, which made one resolution take minutes on the 900 token production prompt.
  `token_entropy` is the binary entropy of the model's reported confidence; `room_ranking`
  splits the remaining mass by inverse Levenshtein distance. Top-3 figures inherit this.
- D13: `llm_resolver_node_py` reads `room_annotations.json` directly instead of reconstructing
  the graph from `/list_rooms` and `/get_room_pose`, because the flat alias list has no per room
  grouping and no edges, both needed for the prompt. No section 12 interface changed.
- D14: `ResolverCore` defaults to `n_gpu_layers=-1`; the ROS node overrides it to `0` for the
  container image. Metal is roughly 17 to 20 times faster than CPU only on the production prompt.
- D15: the Phase 3 grammar off ablation only produced an out of graph response at temperature
  1.0; at 0.0 and 0.7 all 20 adversarial commands stayed in graph even without the grammar,
  because the system prompt lists every valid name explicitly.
- D16: the Phase 3 DoD's 20 call container latency benchmark was reduced to 4 to 5 calls against
  an already warm resolver; the Metal proxy carries the full series the p90 gate is judged on.
- D17: `ResolveResult` (Python internal, not a section 12 interface) gained
  `calibrated_confidence`, `calibrator_loaded`, `prompt_eval_tokens`.
- D18: the sim profile `timeout_ms` is 300000 ms, not the 20000 v1 section 13 named, because the
  real 30 room production prompt is 900 to 1000 tokens and needs one to a few minutes cold on
  the container's CPU only llama.cpp.
- D19: the Phase 4 24 condition prompt grid is screened on a deterministic stratified 64 pair
  subsample (8 per category, seed 42) before the top 2 GBNF conditions run on the full 500.
- D20 to D23: baselines B0 to B4b added beyond the original Phase 4 scope per Review 2 panel
  feedback; the cloud ceiling row (D8) pulled forward; top-3 for LLM rows uses the D12 heuristic
  ranking; study calls capped at `max_tokens=64`.
- D24: the grammar off out of graph rate on the full 500 is 1.0 percent (5/500) at the winning
  temperature, below the 5 percent v1 expected. Reported as measured, not tuned. The grammar's
  value is the structural 0 percent guarantee at essentially no latency cost.
- D25: the Phase 4 dataset's checker flagged rows and stratified human review sample were
  adjudicated by the session itself rather than a separate human reviewer, since the phase ran
  as one continuous automated pipeline. Reasoning recorded in `data/benchmark/DATASET.md`.
- D26: Phase 4's 80 percent baseline top-1 gate was **not met**: best full 500 top-1 is 0.662 to
  0.664 after two documented prompt template iterations. The shortfall is concentrated in
  `spatial`, `multi_hop` and `adversarial`. v1 attributed this to a capability limit of
  Phi-3-mini-4k Q4_K_M on compositional reasoning. **v2 Phase 5 is the response** (see D29).
- **D27: v1's Phase 5 (C++ in-process llama.cpp resolver) is dropped.** The resolver stays in
  Python behind the unchanged `/resolve_waypoint` service; the C++ in the package is the
  annotation map node, the BT plugin and the semantic goal node. Reason: accuracy, not
  implementation language, was the binding constraint on the remaining budget, and the BT plugin
  rather than the resolver carries the "native Nav2 plugin" claim. The v1 C++ versus sklearn
  calibrator parity test becomes a Python versus sklearn test. Full reasoning:
  `docs/archive/superseded-decisions.md` S1.
- **D28: `llama-server` over HTTP becomes the measured and deployed inference path**, with
  in-process llama-cpp-python retained as the default for host unit tests. Reason: it is the
  best supported CUDA path on the Jetson, it makes simulation and hardware the same shape, and
  it takes the Phase 7 and 8 batch runs from 8 to 12 hours of container CPU to under an hour on
  host Metal. Section 13 rewritten accordingly. Full reasoning: S2.
- **D29: the GBNF grammar gains a `relation` field** (section 12.6 v2) so that spatial traversal
  is performed in code against `edges` rather than by the model. Internal to the resolver;
  section 12.2 unchanged. Motivated directly by the Phase 4 error analysis behind D26. Full
  reasoning: S3.
- **D30: the Gazebo DoD items are formally removed** from Phases 6 and 8 rather than carried as
  permanently unmet, per D11. Loopback is the only simulation mode. The gap is named as a
  limitation in `RESULTS.md` and GPU passthrough is listed in Phase 10. Full reasoning: S4.
- **D31: v1 Phase 9 (model ablation and final report) is merged into v2 Phase 8**, and Phase 9
  is reused for hardware readiness. Full reasoning and the renumbering table: S5.
- **D32: Phase 5's raw top-1 gate was not met, and the shortfall is well outside the
  documented band.** Full 500 top-1 is 0.560 (gate >= 0.80, stop-and-report floor 0.74).
  `relations.py`'s disambiguation policy (alias/tag overlap, abstain on a tie), implemented
  exactly as section 8.1 specified, resolves only 26 percent of the `spatial`/`multi_hop` hard
  subset even given a perfect anchor/relation choice: most rooms have 2+ `adjacent`/`near`
  neighbors and most of these commands give no alias/tag cue to disambiguate between them.
  Separately, the model over-applies non-`none` relations to commands that need `none`,
  which corrupted 68/500 otherwise-correct answers, concentrated in the categories (`direct`,
  `alias`, `negation`, `abbreviation`) D29 assumed would be unaffected. Per section 8's own
  instruction for a result this far under 0.74, no further prompt iteration was attempted;
  full error analysis in `docs/reports/phase-5-relational-decomposition-resolver-backend.md`
  section 5. Carried into Phase 8 as an open risk rather than resolved here.
- **D33: the Docker image needed `requests` added** (`docker/requirements.txt`) for
  `HttpBackend` to construct inside the container; a concurrent backend request could also
  crash the whole resolver node (only `TimeoutError` was caught in `_on_resolve`), now fixed
  to catch any backend exception the same way.
- **D34: `left_of`/`right_of` traversal direction was inverted in the first implementation.**
  "A is left_of B" (12.7) means finding "what's left of B" requires B's inverse (`right_of`)
  relation, not its own `left_of` edges. Caught by testing against the natural-language
  meaning directly; see `relations.py` and the phase 5 report section 2.
- **D35: `config/prompts/fewshot.jsonl` was missing the `relation` field** the v2 grammar
  requires, a latent bug with no effect on this phase's numbers since production runs with
  `fewshot_count=0`, but fixed so a future session that raises `fewshot_count` does not
  silently teach the model the wrong schema.
- **D36: the Phase 5 Phi-3.5 model check ran on the held-out 100 slice, not the full 500**,
  since a full-500 run is roughly 100 minutes per model at the v2 grammar's measured decode
  cost and the held-out slice was already shown to track the full-500 number within 1-2
  points. Phi-3.5 mini scored 7 points worse than production, not within the 2-point
  promotion margin, which the 100-row sample is decisive enough to show.

## 15. Phase 9: hardware readiness (no robot required)

Goal: make Jetson Orin NX deployment a verified-feasible path rather than an assumption, using
only what can be checked without the physical robot. This phase writes and reviews; Phase 10
executes.

The guiding question for every item: *when the hardware arrives, what could still surprise us?*
Anything that can be answered now gets answered now.

Scope:

- `docker/Dockerfile.jetson`: ROS 2 Humble on JetPack (`dustynv/ros:humble-*` or an l4t base),
  `llama.cpp` tag b10941 built with `-DGGML_CUDA=ON` producing `llama-server`, the workspace
  built with `colcon`. Written, lint-checked, and reviewed line by line against the known arm64
  and CUDA pitfalls. **Not built in this phase** (no Jetson present); Phase 10 builds it and
  records what had to change.
- `docs/hardware/jetson-build.md`: the build recipe with the exact CUDA architecture flag for
  Orin NX (`sm_87`), expected build time, disk requirements, and the three failure modes most
  likely to appear, each with its remedy.
- `config/planner_params.yaml` hardware profile: `timeout_ms: 3000` (specification value, not
  the sim 300000 of D18), `backend: http`, `backend_url: http://127.0.0.1:8080`, `n_threads`
  for the Orin, the Phase 7 threshold, and the production model path. The sim profile stays as
  is. A unit test asserts both profiles load and validate.
- `safenav_sim/config/nav2_params.yaml` hardware variant: Create 3 velocity limits restored to
  0.26 m/s, reversing D10 for hardware only, with a test asserting the sim and hardware values
  differ as intended.
- `docs/hardware/bringup-checklist.md`: every seam between the simulation build and the robot,
  each with the evidence that it already works and what specifically must be re-verified on
  hardware. At minimum: model load and CUDA offload, grammar identity across backends, the
  `/resolve_waypoint` contract, the BT plugin load path in `bt_navigator`, the annotation graph
  and its poses against a fresh SLAM map, TF frames, the calibrator file, and `/tts_text`.
- `docs/hardware/cannot-verify.md`: an explicit, honest list of what no amount of simulation
  work can de-risk, so Phase 10 budgets for it. Expected entries: real sensor noise into AMCL,
  Create 3 docking behaviour, thermal throttling of the Orin under sustained inference, real
  human phrasing versus persona-generated phrasing (D7), and audio hardware for TTS.
- A short section in `RESULTS.md` recording which hardware claims are verified, which are
  argued, and which are untested.

### DoD

- [ ] `Dockerfile.jetson` committed and reviewed; the review notes in the report say what was
      checked and what remains unknown until it is built.
- [ ] `docs/hardware/jetson-build.md`, `bringup-checklist.md`, `cannot-verify.md` committed.
- [ ] Hardware and sim profiles both present in `config/planner_params.yaml`, both load and
      validate in a unit test, and differ only in the documented fields.
- [ ] Nav2 hardware velocity variant committed with its test.
- [ ] Every entry in the bring-up checklist cites either a simulation result (with the report
      and section) or is listed in `cannot-verify.md`. No entry is left unsourced.
- [ ] Report written, PR merged.

Gate: a competent engineer with the robot in front of them could follow `bringup-checklist.md`
without reading this plan.

## 16. Phase 10: hardware bring-up (deferred until hardware is present)

Not part of the 4 to 5 day budget. Run when the Jetson Orin NX and TurtleBot4 Standard are
available.

Build `Dockerfile.jetson` on the Orin and record the delta from the Phase 9 recipe. TurtleBot4
Standard bringup. Fresh SLAM map of the real space, `annotate_map.py` with RViz clicks to
rebuild `room_annotations.json` against it, including the `edges` the Phase 5 decomposition
depends on. Hardware latency profile with CUDA, compared against the section 13 expectation of
about 0.7 s. Human session 1 and 2 trials (5 participants, 200 and 100 trials), calibrator
retrained on real logs, and the three condition study. Optionally revisit Gazebo with GPU
passthrough to close the D11 and D30 gap. Paper and patent drafts.

Everything above must run unchanged except `model_path`, `n_threads`, `backend_url`, the map,
and the annotation file.

## 17. Session checklist

1. `git checkout main && git pull`, read the previous phase report in `docs/reports/`. If the
   phase is 5 or later, also read `docs/archive/superseded-decisions.md` once.
2. Start the host inference server if the phase needs it:
   `llama-server -m models/phi3-mini-4k-instruct.Q4_K_M.gguf -ngl -1 --port 8080 --host 0.0.0.0`
   (see `docs/hardware/llama-server.md` after Phase 5 writes it).
3. Start Docker: `docker compose -f docker/docker-compose.yml up -d`, then `exec dev bash`.
   Build with `colcon build --symlink-install` from `/ws/ros2_ws`.
4. Create the issue, the branch, then work through the scope in order. Keep a running list of
   DoD items with evidence (command plus output snippet) for the report.
5. Run every DoD command yourself. Do not tick an item you did not run.
6. Write the report, update the status table, commit, push, PR, merge, delete the branch.
7. Summarize for the user: what was built, numbers, deviations, what the next session starts with.
8. Do not start the next phase in the same session unless asked.
