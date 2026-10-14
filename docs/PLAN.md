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
| 5 | Relational decomposition and resolver backend | [x] | #16 | #17 |
| 5A | Corrective: cue gating, benchmark re-audit, latency re-measure | [x] | #18 | #19 |
| 6 | BT plugin, semantic goal node, end to end in sim | [x] | #20 | #21 |
| 7 | Confidence calibration pipeline | [x] | #22 | #23 |
| 8 | E2E validation, ablations, final results | [x] | #24 | #25 |
| 8B | Corrective: e2e150 rescoring, clean reruns, claim corrections (section 11A) | [x] | #26 | #27 |
| 8C | Spatial anchor fix and 8B corrections (section 11B) | [x] | #28 | #29 |
| 9 | Hardware readiness (no robot required) | [ ] | | |
| 10 | Hardware bring-up (deferred until hardware is present) | [ ] | | |

## Budget

Phase 5 is spent. Four phases plus one corrective pass remain, scoped to about **4.25 working
days** of human time. Roughly four hours of that is unattended background compute that overlaps
with other work.

| Phase | Human time | Background compute | Status |
|-------|-----------|--------------------|--------|
| 5 Relational decomposition and backend | 1.5 d | ~1 h | spent, merged #17 |
| 5A Corrective pass | 1.0 d | ~1 h (benchmark reruns) | next |
| 6 BT plugin and E2E | 1.25 d | none | |
| 7 Calibration | 0.75 d | ~20 min | |
| 8 E2E validation and results | 0.75 d | ~3.5 h (300 loopback runs) | merged #25, claims under correction (D57) |
| 8B Corrective pass (section 11A) | 0.75 d | ~3.5 h (450 loopback runs, isolated latency) | merged #27, wall clock 3 h 51 min |
| 8C Spatial anchor fix (section 11B) | 0.5 d | ~1 h (150 loopback runs; held-out sets replayed offline) | merged #29 |
| 9 Hardware readiness | 0.5 d | none | |

Phase 5 merged having met every engineering DoD item and missed both its accuracy gate (top-1
0.560 against 0.80) and its latency gate (p90 7220 ms against 3000 ms). Section 8A is the
corrective response. It is scoped to run **in the same Sonnet session that ran Phase 5**, so it
is written as a continuation rather than a cold briefing.

Phase 9 is documentation and configuration only. If the week runs tight it can slip to a later
session without blocking anything, which puts the critical path at 3.75 days.

Section 16A holds optional scope that is budgeted at zero. It is attempted only if Phase 8 and
Phase 9 are merged and time is left over, and it never displaces either. Phase 8B (section 11A,
D57) counts as part of Phase 8 for this rule: 16A waits for 8B as well. Phase 8C (section 11B,
D63) counts the same way.

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

**The raw top-1 gate was withdrawn after Phase 5A (D45).** Phase 5's measurement established that
96 of the 500 benchmark rows are structurally unanswerable: the graph offers two or more
equally valid targets and the command text contains no cue that distinguishes them (D32). The
benchmark's own ceiling is therefore about 0.81, and only if every other row is answered
perfectly. The original >= 0.80 raw gate was never achievable and should not have been set, and
the >= 0.76 that D37 substituted for it was set by judgment, as ceiling minus a margin, rather
than derived from the specification, a baseline, or a power calculation. It is withdrawn too.
Raw top-1 is reported as measured against the derived ceiling, with no pass or fail threshold
attached; the accuracy gate the specification actually asks for is the gated end-to-end 0.85 in
Phase 7. **Corrected by D57.** There is no "specification" with authority here (D54): the
Review 2 metrics table was drafted inside this project and never approved, and the gate is
re-anchored at >= 0.75 (literature-anchored on KnowNo's multi-step setting), with 0.824 reported
alongside as the stricter category-weighted reading. See the provenance table below.

| Metric | Target | Phase |
|--------|--------|-------|
| Resolver raw top-1, corrected 500 benchmark (`synthetic_500_v2.jsonl`) | report as measured, no threshold (D45); 0.732 at 5A, derived ceiling about 0.81 | 5A |
| Resolver raw top-1, original labels, reported alongside for continuity | report as measured | 5A |
| Resolver top-3, corrected 500 benchmark | >= 0.85 (D58: re-anchored from Review 2's unapproved 0.97; 0.868 measured, reported against both), with the D12 ranking caveat stated | 5A |
| Gated end-to-end accuracy, 500 pair benchmark (correct abstention counts as correct) | >= 0.75, anchored on KnowNo's multi-step target (D54); 0.72 at 7, provisional (D53) | 7, 16A |
| Out of graph output rate, grammar on | 0% (structural) | 5, 8 |
| Out of graph output rate, grammar off | report as measured (D24: 1.0% at Phase 4) | 8 |
| ECE, calibrated confidence (sim eval set) | <= 0.08 (CV gate <= 0.10), internally set, no literature standard exists (D54) | 7 |
| False pass rate (sim eval set) | <= 5% internally set and stricter than KnowNo's eps = 0.15 (D54) | 7 |
| Human help rate (fraction of commands deferred) | report; KnowNo's comparable band is 0.58 to 0.92 (D54) | 7 |
| False rejection rate (sim eval set) | report as measured; no literature sets this gate (D54) | 7 |
| Resolver latency p90 | < 3000 ms on the Metal backend, measured cold (section 13). Internally set and **looser** than the HRI literature's 2000 ms (D54). **Measured 3737 ms: the one outstanding miss**; mitigation in 16A O3 | 5A, 8, 16A |
| 150 run E2E sim validation, grammar on | 0 out of graph outputs | 8 |

### Target provenance (added 2026-10-14, D54)

Every numeric gate above was originally set inside this project, including the ones that came
through `docs/reference/Review_2_Phase_2.docx`: that document's metrics table was drafted here
and **was not approved at Review 2**, so it carries no external authority. Treating it as a
specification was a mistake that D45 and D53 both repeated. The table below records what each
number actually rests on, so that a reader can tell a derived target from a chosen one. Numbers
marked *internally set* are chosen, defensible as engineering judgment, and not evidence of
anything; they are kept rather than deleted, because deleting only the gates the project missed
would be selection, not correction.

| Gate | Provenance | Source |
|------|-----------|--------|
| Gated end-to-end >= 0.75 | literature-anchored | Ren et al. 2023 (KnowNo), CoRL, arXiv 2307.01928: `1 - eps = 0.75` for the multi-step hardware setting, `0.85` for single-step |
| Help rate, 0.58 to 0.92 band | literature-anchored | KnowNo Table 2: step-wise help 0.58 (multi-step), 0.67 (mobile manipulator), 0.92 (bimanual) |
| False pass <= 5% | internally set | stricter than KnowNo's `eps = 0.15`; see O2 before treating it as required |
| False rejection <= 15% | **withdrawn** | no cited work sets such a gate; KnowNo reports help rate instead |
| Latency p90 < 3000 ms | internally set | HRI work is stricter: Shiwa et al. 2008/2009 find impressions unchanged to 1000 ms and recommend reacting within 2000 ms. Their filler remedy is 16A O3 |
| Time to first utterance | literature-anchored, **not yet implemented** | Shiwa et al.: 1000 ms unchanged, react within 2000 ms. Added only if 16A O3 runs |
| ECE <= 0.08, CV <= 0.10 | internally set | no peer-reviewed cutoff exists; Guo et al. 2017 fixes the 10-equal-width-bin method only |
| Out of graph 0% | structural | guaranteed by GBNF at the sampler, not a measured target |
| Raw top-1 | no gate | withdrawn in D45; benchmark ceiling about 0.81 (D32) |
| Resolver top-3 >= 0.85 | internally set (D58) | 0.97 in the Review 2 table and plan v1, 0.88 in the v2 redraft, 0.85 in the 5A plan; none of these changes had a recorded deviation. 0.868 measured (5A) is reported against both 0.85 and 0.97, the way this table reports gated accuracy against both 0.75 and 0.824 |

**On the 0.75.** KnowNo sets its failure level per setting, not once per system: `eps = 0.15`
(target 0.85) for single-step tasks and `eps = 0.25` (target 0.75) for multi-step tabletop
rearrangement. This benchmark is mixed, with 130 of 500 rows in `spatial` and `multi_hop`.
**The 0.75 is therefore usable but not airtight, and this is the honest statement of why.**
Mapping a two-hop graph traversal expressed in one utterance onto KnowNo's multi-*action*
trials is an interpretation, not an identity. The stricter reading is a category-weighted
transfer, `0.85 x 370/500 + 0.75 x 130/500 = 0.824`, under which the measured 0.72 is still a
clear miss at about 5.2 standard errors. Both readings are reported in Phase 7 and Phase 8 and
neither is presented alone. Under the flat 0.75, 0.72 sits 1.5 standard errors low with a 95
percent interval of about [0.681, 0.759] that contains the target, so the two are not
distinguishable at n = 500; under 0.824 they are. A reader who rejects the multi-step mapping
should use 0.824 and read the result as a miss.

**Neither reading licenses calling the result a pass.** The 0.72 is provisional on D53's
feature defect regardless of which target it is set against.

### Current metric status (audited 2026-10-14, after D54)

Every live metric as measured, against the provenance-corrected targets above. Phases 0 to 7 are
merged; Phase 4's and Phase 5's own gate results are historical and superseded by Phase 5A.

| Metric | Target | Measured | Phase | Status |
|--------|--------|----------|-------|--------|
| Resolver raw top-1, corrected 500 | no gate (D45) | 0.732 | 5A | reported, about 90% of the 0.81 ceiling |
| Resolver top-3, corrected 500 | >= 0.85 (D58: also 0.97, Review 2/v1) | 0.868 | 5A | met against 0.85, misses 0.97 |
| Out of graph rate, grammar on | 0% | 0% | 5A, 6 | met, structural |
| Gated end-to-end, corrected 500 | >= 0.75 (0.824 strict) | 0.72 | 7 | within noise of 0.75, misses 0.824, provisional (D53) |
| CV ECE, out of fold | <= 0.10 | 0.0698 | 7 | met |
| Calibrated ECE, session 2 | <= 0.08 | 0.0730 | 7 | met |
| False pass rate, session 2 | <= 5% | 0.0426 | 7 | met |
| Help rate, session 2 | KnowNo band 0.58 to 0.92 | 0.53 | 7 | favourable, below every KnowNo setting |
| Precision on acted-upon commands | none set | 0.957 | 7 | reported |
| False rejection, session 2 | gate withdrawn (D54) | 0.3662 | 7 | reported, provable optimum for this feature vector |
| **Resolver latency p90, cold** | **< 3000 ms** | **3737 ms** | **5A** | **miss, the only outstanding one** |
| 150 run E2E, grammar on | 0 out of graph | 0/150 | 8 | met, structural |
| e2e150 wrong-room action rate, gate on vs. gate off | none set; Condition B versus C | 0.173 (gate on, rescored production) vs. 0.187 (gate off, 8B rerun); essentially unchanged | 8, 8B | measured (D62); Phase 8's withdrawn 0.772 vs. 0.080 was a navigation artifact, not this |
| e2e150 wrong-room actions with the gate on | none set; session 2 false pass bound is <= 5% | 26 of 140 acted-on commands (rescored), 25 of them `spatial` | 8, 8B | measured (D62) |
| e2e150 wrong-room action rate, gate on vs. gate off, `text_anchor` on (8C, diagnostic only, default ships off) | none set; Condition B versus C | 0.000 (gate on) vs. 0.000 (gate off, re-gated offline); both eliminated | 8C | measured (D64), `docs/results/e2e150_report_8c.md` |
| e2e150 wrong-room actions with the gate on, `text_anchor` on (8C, diagnostic only) | none set | 0 of 140 acted-on commands, spatial resolver correct 30/30 (up from 2/30) | 8C | measured (D64) |

**Amended 2026-10-14 (D57), re-measured 2026-10-14 (D58, Phase 8B).** The two e2e150 rows above
were added after the Phase 8 review and re-measured in `docs/reports/phase-8b-corrective.md`.
Phase 8's gate-on versus gate-off figure was a navigation artifact, not a gate effect; the
corrected comparison (wrong-room action rate, not reached-intended) shows the gate making
essentially no measurable difference on this command set, consistent with the gate passing
25 of 30 spatial commands at calibrated confidence 0.90 to 0.95 regardless of threshold.

**Corrected by D63 (2026-10-14).** The two e2e150 rows cited D58; the result is D62 (fixed
above). The last sentence above locates the cause in the gate. A review of 8B found most of
the wrong spatial passes come from the resolver applying the relational hop twice (the model
puts the answer in the anchor field), so they are confident because the model's first answer
is correct. Section 11B (Phase 8C) fixes and re-measures it; these rows stay as 8B measured
them, now joined above by the 8C diagnostic rerun.

**Corrected by D64 (2026-10-14).** Phase 8C (section 11B) fixed the double hop
(`relations.apply_relational_hop`/`extract_text_anchor`) and confirmed this reading from
committed data (the two new rows above): with the fix forced on, e2e150's spatial resolver
correct rate goes from 2/30 to 30/30 and wrong-room gate-passed actions from 26/140 to 0/140.
The fix ships with its default **off** in `planner_params.yaml`, because the held-out replay
(`docs/results/text_anchor_replay.md`, PLAN.md 11B.5) shows the corrected 500 benchmark's top-1
falling by one row net (6 gained, 7 lost, all 7 losses in `multi_hop` compound sentences where
the "first cue, nearest room" rule picks up the wrong clause's room). Session 2 false pass is
unaffected either way (0.043 before and after).

**One metric is currently a miss: latency.** Everything else is met, favourable against its
literature anchor, reported without a gate, or not yet measured. The gated accuracy row is the
only ambiguous one and it is ambiguous by construction, because D54 reports two defensible
targets and D53 marks the measurement provisional; it is not counted as met. The two e2e150 rows
above are reported as measured, with no pass/fail gate attached (11A.4: "whatever the gate
comparison shows is the result").

**16A O3 does not change the latency row.** A conversational filler addresses perceived
responsiveness, which is what Shiwa et al. actually measured, and would add a separate
time-to-first-utterance metric. The 3737 ms stands either way, and any report that shows the new
metric without this one is misrepresenting the system.

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

**Outcome: merged (#17), engineering DoD met in full, accuracy and latency gates missed**
(top-1 0.560, p90 7220 ms). Section 8 above is left exactly as it was written before the phase
ran, so that the plan's prediction and the measured result can be compared. The corrective
response is section 8A. Report:
`docs/reports/phase-5-relational-decomposition-resolver-backend.md`.

## 8A. Phase 5A: corrective pass

**You are the same session that just ran Phase 5.** You already have the codebase, the report,
and the error analysis in context. This section is a continuation, not a briefing: it does not
re-describe `relations.py`, `backends.py`, the grammar builder or the benchmark runner, because
you wrote them. Do not re-read your own Phase 5 report to "get up to speed"; you have it.
Do not re-run `git checkout main && git pull` as if starting cold, though you do need a fresh
branch (see 8A.5).

Goal: recover the regression your error analysis identified, correct a benchmark labelling
error that your ceiling check uncovered, re-measure latency without the thermal confound, and
restate the gates against what is actually achievable. One working day. Timeboxed.

**Two things changed in the diagnosis since section 8 was written**, and they are why this is a
corrective pass rather than a retry:

1. Section 8 assumed `relation: "none"` would be free on commands that do not need a hop. Your
   section 5.1 measured 68 of 500 rows where the anchor was already correct and a spurious
   non-`none` relation overwrote it, 39 of them in the four categories section 8 predicted
   would be untouched. The plan's own `within` worked example is the most likely teacher of
   that over-generalization. This is a plan defect, not an implementation defect.
2. Section 8 assumed the model was the binding constraint on `spatial`/`multi_hop`. Your
   section 5.2 and D32 measured that only 26 percent of those rows are answerable *at all*
   given the graph. 96 of 500 benchmark rows have no unique correct answer. The benchmark, not
   the model, is the binding constraint, and the >= 0.80 gate in section 8 was unreachable from
   the moment it was written.

### 8A.1 Cue gating, with a go/no-go pre-check first

The hypothesis is that the hop should only ever fire when the command actually asks for one,
and that "asks for one" is detectable lexically.

**Do the pre-check before writing any of it.** It is cheap and it can kill the whole idea:

- Assemble a closed list of relational cue phrases by reading the *command text* of the
  `spatial` and `multi_hop` rows in `synthetic_500.jsonl`. Derive the list from the generator's
  actual phrasings, do not invent it from intuition. Expect forms like "next to", "beside",
  "left of", "right of", "across from", "opposite", "near", "adjacent to", "behind", "in front
  of", "past", "beyond", "down from", "with the", "that has", "containing".
- **Freeze the list in a file before running anything against it.**
- Measure two coverage numbers and put both in the report:
  - **recall**: fraction of `spatial` + `multi_hop` rows that contain at least one cue. If this
    is below 0.85, cue gating is the wrong mechanism, because forcing `relation=none` on a
    genuinely relational command destroys it. Stop and say so rather than proceeding.
  - **false positive rate**: fraction of `direct` + `alias` + `negation` + `abbreviation` rows
    that contain a cue. This should be near zero. Every such row is one cue gating cannot save.

If the pre-check passes:

- `relations.py` gains `has_relational_cue(command) -> bool` against the frozen list.
- No cue: force `relation = "none"`, suppress the hop, and issue the call against the **v1
  single-field grammar** (`{"room", "confidence"}`), not v2. This is the common path.
- Cue present: v2 grammar and the hop exactly as Phase 5 built it.
- Both grammars are built once per graph version and cached; selection is per request.
- The v1 grammar builder still exists behind the flag you added in Phase 5; if it does not,
  regenerating it is a few lines, not a rewrite.

Using v1's smaller grammar on the common path is also the latency fix: your section 6 pinned
the regression on per-token decode cost under the larger v2 alternation (~228 ms/token vs ~40
ms/token), and most traffic will now avoid it.

Do **not** tune the cue list after seeing accuracy results. If it needs changing, that is a
finding to report, not an iteration to run.

### 8A.2 Benchmark re-audit, graph-blind and mechanical

Your D32 ceiling check already computes exactly the quantity this needs. Reuse that code
rather than writing a second implementation that could disagree with it.

The rule, which must be written and frozen **before** it is run:

- For every `spatial` and `multi_hop` row, compute from the graph alone whether a unique target
  exists: enumerate plausible anchors, apply the row's relation, and apply the section 8.1
  disambiguation policy (alias and tag overlap with the command text).
- Exactly one surviving target: `structurally_answerable: true`, label unchanged.
- Zero or more than one surviving target: `structurally_answerable: false`, and
  `expected` becomes `"none"` in the corrected set.
- The rule sees the graph and the command text. **It never sees a model prediction.** This is
  what makes it a labelling correction rather than fitting the test set to the system.
- It runs over all 130 rows and its output is whatever it is. No hand-picking, no exceptions,
  no post-hoc adjustment.

Outputs:

- `data/benchmark/synthetic_500_v2.jsonl`, carrying both `expected` (corrected) and
  `expected_original`, plus the `structurally_answerable` flag and the rule's reasoning per row.
  **`synthetic_500.jsonl` is not modified.**
- `data/benchmark/RELABEL.md`: the frozen rule verbatim, counts by category, and ten worked
  examples showing the graph reasoning behind the relabel.
- Every accuracy table from here to Phase 8 reports **both** label sets.

The justification to state plainly in the report: a command that the facility graph cannot
answer uniquely has exactly one correct response, which is to abstain and ask for
clarification. That is the system's safety claim, so `"none"` is the correct label and the
original label was wrong. This is correcting mislabeled ground truth, not moving a goalpost.

**Say the uncomfortable part out loud too**, in its own short paragraph: this relabel was
designed after seeing Phase 5's results, by the same session that produced them, which is the
same self-adjudication exposure D25 recorded for the Phase 4 dataset. The defences are that the
rule is graph-derived and model-blind, that it was frozen before running, that both label sets
are reported, and that the original file is untouched and in git. State those and let a reader
judge. A Review 2 panel will reach for the uncharitable reading first, and the report should
have already met it.

### 8A.3 Cold latency re-measure

Your section 6 disclosed that the 7220 ms p90 followed roughly 45 minutes of sustained Metal
inference, and that an isolated mid-session spot check measured about 950 to 1000 ms. That
confound has to be removed before a failed latency gate goes into the record.

- Fresh `llama-server`, cold start, nothing else contending for the GPU, machine otherwise idle.
- 100 calls over the held-out slice.
- Report the v1-grammar path and the v2-grammar path **separately**, with
  `predicted_per_token_ms` for each, which either confirms or refutes the grammar-size
  hypothesis in your section 6.
- Report a traffic-weighted p90 using the measured cue rate from 8A.1, since that is the number
  the deployed system actually experiences.
- If the cold numbers clear 3000 ms, say explicitly that Phase 5's section 6 figure was a
  thermal artifact and should not be cited.

### 8A.4 What not to do

Scope discipline matters more here than anywhere else in the plan, because the temptation after
a failed phase is to reopen everything.

- No fourth prompt-template iteration. Phases 4 and 5 have now produced four data points on
  this and the trend is not favourable.
- No new model downloads. Phi-3.5 was checked and is 7 points worse (D36).
- Do not touch the backend seam, grammar correctness, or traversal correctness. All three were
  verified independently in Phase 5 and backend parity is 100 percent. They are not suspects.
- Do not revisit Gazebo (D11, D30).
- If 8A.1's pre-check fails, do not substitute a different mechanism on the fly. Report and stop.

### DoD

- [ ] Cue list frozen in a committed file before any measurement; recall on `spatial` +
      `multi_hop` >= 0.85 and false positive rate on the four easy categories reported.
- [ ] Two-path grammar selection implemented; unit test proves a cue-free command takes the v1
      grammar and a cued command takes v2.
- [ ] Regression check: of the 68 rows your section 5.1 identified as correct-anchor-overwritten,
      the number now answered correctly is reported. This is the single number that says whether
      8A.1 worked.
- [ ] Relabel rule frozen and committed before running; `synthetic_500_v2.jsonl` and
      `RELABEL.md` produced; `synthetic_500.jsonl` unmodified (verify with `git diff`).
- [ ] Full 500 on corrected labels: top-1 reported as measured against the derived ceiling, no
      threshold (D45); top-3 >= 0.85; out of graph 0.0.
- [ ] Full 500 on original labels reported in the same table for continuity with Phase 4 and 5.
- [ ] Per-category table against both label sets, with the Phase 4 and Phase 5 columns alongside
      so the three-way comparison is visible in one place.
- [ ] Cold latency re-measure: v1 path, v2 path, and traffic-weighted p90, each with
      per-token decode cost. Verdict on whether Phase 5's 7220 ms was thermal.
- [ ] Self-adjudication exposure paragraph present in the report (8A.2).
- [ ] Report `docs/reports/phase-5a-corrective.md` written, PR merged.

### Stop rule

If top-1 on the corrected labels lands below **0.70**, stop. Do not iterate further. Record the
result, leave the resolver in whichever configuration measured best, and move to Phase 6 with
the measured figure carried into Phase 8's results. The remaining phases do not depend on any
particular raw top-1 value: the BT plugin, the calibration gate and the end-to-end validation
are all meaningful at 0.70, and Phase 7's gated metric is the headline the specification
actually asks for. 0.70 is a judgment-set abort trigger for downstream work, not a success
target, and after D45 it is the only number attached to raw top-1 anywhere in this plan.

Budget discipline: this is one day. The schedule has no slack left for a second corrective pass.

### 8A.5 Git flow

Same session, new branch, normal conventions. Phase 5's branch is merged and deleted.

```
git checkout main && git pull
gh issue create --title "Phase 5A: corrective pass" --body-file <file> --label phase
git checkout -b phase-5a/corrective
```

PR title `Phase 5A: corrective pass`, body with the DoD checklist and `Closes #<issue>`.

**Deviation numbering: this phase's deviations start at D40.** D32 to D36 were recorded by
Phase 5 and D37 to D39 by this corrective replan, so anything starting lower collides. Append
them to section 14 and to the phase report as usual.

**Preserve, do not replace.** Everything this phase supersedes stays on disk, the way plan v1
was kept when v2 replaced it (`docs/archive/`) and the way section 8 was kept when 8A was added:

- `data/benchmark/synthetic_500.jsonl` stays byte-identical; corrected labels live in
  `synthetic_500_v2.jsonl`. Confirm with `git diff` before committing.
- `docs/reports/phase-5-relational-decomposition-resolver-backend.md` is not edited; the new
  report is `docs/reports/phase-5a-corrective.md`.
- Both grammar paths are kept. This phase selects between v1 and v2, it does not retire either.
- A revised prompt or grammar artifact is added alongside its predecessor with a version
  suffix, as Phase 4 did with `system_template_v2.txt`, never overwritten in place.
- `docs/PLAN.md` is amended only: tick the 5A status row, fill in the issue and PR numbers,
  append deviations. Section 8 and this section's scope text stay as written, so that what was
  planned and what was measured can still be compared afterwards.

Gate: none on raw top-1 (D45). Report the measured figure against the derived ceiling, or a
documented stop if it falls below the 0.70 abort floor.

**Outcome: merged (#19), top-1 0.732 on corrected labels: about 90 percent of the benchmark's
derived 0.81 ceiling and well clear of the 0.70 abort floor.**
Cue gating recovered 49/68 of Phase 5's section 5.1 regression and restored
`direct`/`alias`/`negation`/`abbreviation` above the 0.85 no-regression floor. Cold latency
(3737 ms traffic-weighted p90) is roughly half of Phase 5's sustained-session figure but still
misses the 3000 ms gate; the grammar-size hypothesis behind that gate miss is refuted by the
cold per-token measurement. Per the stop rule, not iterated further. Report:
`docs/reports/phase-5a-corrective.md`.

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

- [x] `ros2 param get /bt_navigator plugin_lib_names` includes `semantic_waypoint_planner`,
      no plugin load error in the log. (Actual library name is `semantic_waypoint_planner_bt_node`.)
- [x] `say "go to the kitchen"` reaches the kitchen pose (distance < 0.5 m),
      `/semantic_goal_result` shows `nav_result: succeeded`.
- [x] A relational command (`say "the room to the left of the kitchen"`) navigates to the
      correct room end to end, exercising the Phase 5 hop through the full stack.
- [x] An unresolved command yields FAILURE, a `ClarificationRequest`, a `/tts_text`
      message listing rooms, and `/cmd_vel` stays zero. ("go to the cafeteria" turned out to
      resolve validly via an alias in this annotation graph; "take me to the zebra enclosure"
      used instead, see report section 3.3.)
- [x] Timeout path: resolver stopped, `say` returns within `timeout_ms + 500 ms` with
      `reason: timeout`, robot does not move.
- [x] No `bt_loop_duration` warnings beyond the resolution tick.
- [x] Launch test covering success, low confidence, and timeout paths.
- [x] Report written, PR merged.

Gate: end to end command to navigation works in loopback with fallback behaviours.

**Outcome: merged (#21), all DoD items met.** Report: `docs/reports/phase-6-bt-plugin-e2e.md`.
Deviations D46 to D48.

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
  correct abstention on an adversarial row counts as correct. This is the section 1 target,
  re-anchored to >= 0.75 by D54 with the category-weighted 0.824 reported alongside. Report it
  beside the Phase 5 raw top-1 so the contribution of the gate is visible.
- Keep the feature vector at the five of section 12.8. `n_relation_targets` from Phase 5 is an
  obvious sixth feature; try it only as a reported variant, and do not change 12.8.

### DoD

- [ ] Session 1 and 2 files exist with 200 and 100 rows, disjoint from each other and the benchmark.
- [ ] `train_calibrator.py` writes `config/calibrator.json`; CV ECE <= 0.10 recorded.
- [ ] Session 2: false pass <= 5%, false rejection and help rate reported (the <= 15% false
      rejection gate is withdrawn by D54), calibrated ECE reported (target <= 0.08;
      if not met, report and analyze, do not tune on session 2).
- [ ] Gated end-to-end accuracy on the 500 benchmark reported; target >= 0.75 (D54), with the
      category-weighted 0.824 reading reported beside it.
- [ ] `semantic_cli` shows `calibrated_confidence != raw_confidence` and `calibrator_loaded: true`.
- [ ] Python calibrator versus sklearn parity test passes.
- [ ] Reliability diagram and metrics table committed. Report written, PR merged.

Gate: calibrator deployed in the resolver; threshold fixed in `planner_params.yaml`.

**Outcome: merged (#23), calibrator deployed, every engineering DoD item met.** Session 1 (200)
and session 2 (100) are disjoint from each other and the 500 benchmark. CV ECE 0.0698 (<= 0.10,
met) and session 2 calibrated ECE 0.0730 (<= 0.08, met), false pass 0.0426 (<= 5%, met).
`semantic_cli` and the Python-versus-sklearn parity test both pass.

Session 2 false rejection measured 0.3662 and gated end-to-end accuracy on the 500 benchmark
measured 0.72. **Both are recorded as provisional rather than as results against their targets,
because the section 12.8 feature vector they were computed from is not implemented as
specified** (D53): `n_candidates` is constant at 30.0 across all 300 trial rows and carries a
trained weight of exactly 0.0, and `token_entropy` is the binary entropy of `raw_confidence`
rather than an entropy over the room-level distribution 12.8 asks for, so it adds no
information (correlation -0.984, one entropy value per confidence level, exact to 12 decimal
places). Three of the five features carry independent signal, and 0.3662 is the provable
optimum at the <= 5% false-pass bound for that reduced vector, so no threshold choice improves
it. **D54 revises the target**: the >= 0.85 was internally set, not specification-derived, and
is re-anchored to >= 0.75 on KnowNo's multi-step figure, with the stricter category-weighted
0.824 reported alongside. Against 0.75 the measured 0.72 is within noise; against 0.824 it is a
clear miss. Either way the comparison is deferred until section 16A's fix lands, not dissolved.
Not retuned on session 2 per this section's own instruction.
Report: `docs/reports/phase-7-calibration.md`. Deviations D49 to D54.

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

- [x] 150 loopback runs completed, `data/runs/e2e150_loopback.jsonl` has 150 rows, bag path recorded.
- [x] Grammar on: 0 out of graph outputs across all runs.
- [x] Grammar off: out of graph rate reported as measured (0/50, D56: too small a sample to
      independently confirm D24's 1.0%/500 figure, reported alongside it rather than replacing it).
- [x] Gate on versus gate off task success and false start rates reported, on 50 of the same
      150 commands rather than all 150 (D56, budget reduction): reached-intended 0.772 (gate on)
      vs. 0.080 (gate off), false start 0.243 vs. 0.917.
- [x] Resolver p90 reported for the Metal backend and the container CPU backend (section 13).
- [x] Model ablation table with three models, latency and memory columns.
- [x] `docs/results/RESULTS.md` complete; every number traceable to a JSONL or CSV in `data/`.
- [x] README quick start verified literally from a clean container.
- [x] Report written, PR opened (not yet merged at time of writing).

Gate: core safety claim demonstrated in simulation; results document complete.

**Outcome: engineering DoD met, with two documented reductions (D56)** rather than silent scope
cuts: the grammar-off and gate-off ablations ran at 50 commands/1 trial instead of the full
150/3 trials, and all latency numbers collected while suites ran concurrently on one Mac are
reported with that confound stated rather than presented as clean measurements. The core safety
claim is demonstrated cleanly regardless: the gated-production suite hit 0/150 out-of-graph with
grammar on, and the gate-on vs. gate-off comparison (77.2% vs. 8.0% reached-intended) is exactly
the result the specification's Condition B vs. Condition C comparison asks for. A genuine
loopback-simulator limitation (Nav2 recovery-behaviour loops under 250 sequential real goals in
one un-reset session) was found and reported rather than averaged away; it inflates the
ablation suites' absolute latency tails but does not touch the reached-intended comparison.
Report: `docs/reports/phase-8-e2e-validation-results.md`. Deviations D55, D56.

**Corrected by D57 (2026-10-14, after merge).** The paragraph above is kept as Phase 8 wrote it.
Two of its claims do not hold against Phase 8's own run files. First, the gate-on versus gate-off
comparison is not a gate effect: on the 50 shared commands the resolver acted on 48 with 10
wrong in both conditions, and the 0.080 reached-intended comes from the loopback robot leaving
the map (pose near x = -124 m from the sixth gate-off row onward) while Nav2 still reported
`succeeded`. Second, "the core safety claim is demonstrated" holds only for the grammar half
(0/150 out of graph); the gate passed 26 wrong rooms out of 140 acted-on commands. The 0/150
result, the model ablation's accuracy columns, and the engineering stand. Section 11A is the
corrective pass.

## 11A. Phase 8B: corrective pass

Named 8B rather than 8A because "8A" is already the section that holds Phase 5A, and a
"Phase 8A" would be confused with it in every cross-reference. The section is numbered 11A
after the 8A and 16A precedent, because merged reports cite section numbers.

**You are a new session and you did not run Phase 8.** Read these, in this order, and nothing
else in this file unless a step below sends you there: this section; section 1 (Targets,
Target provenance, Current metric status); D53 to D57 in section 14;
`docs/reports/phase-8-e2e-validation-results.md`; `docs/results/RESULTS.md`. The plan is about
1500 lines and the rest of it is not needed for this pass.

Goal: Phase 8 merged (#25) with its engineering intact and two headline claims that its own
run files contradict. This pass rescores what can be rescored without inference, reruns what
cannot on a clean and isolated setup, and corrects the documents. It changes **no** resolver,
grammar, prompt, cue list, calibrator or threshold. Timeboxed at 0.75 day of human time plus
about 3.5 h of unattended runs.

### 11A.0 What the review found

Every number here comes from files already on disk under `data/runs/` (gitignored, so they
exist only on this machine until 11A.6 freezes them). Re-derive each one yourself before
relying on it, and say in the report if any differs.

1. **The gate-on versus gate-off headline is a navigation artifact.** Production trial 0 (the
   first 50 rows of `e2e150_loopback.jsonl`, `run_id` prefix `e2e150-0-`) and
   `e2e150_gate_off.jsonl` are the same 50 commands, and the resolver's chosen room agrees on 48
   of them. With the gate on, 47 acted on and 8 wrong; with it off, 48 acted on and 10 wrong.
   Over all 150 production rows the gate rejected a real room twice (both `negation`, both
   wrong). Meanwhile 45 of 50 gate-off rows record a final pose outside the map (room poses span
   x 0.2 to 19.5, y -6.0 to 6.5; from the sixth row onward the robot sits near x = -124 m) while
   `nav_result` is `succeeded` on all 50. `e2e_report.py` counts `gate_passed and not
   reached_intended` as a false start, so 34 correct resolutions the robot never reached became
   "false starts". The 0.772 versus 0.080 measures the loopback simulator diverging, not the
   gate.
2. **The gate passes wrong rooms at high confidence on relational commands.** 26 of the 140
   production commands that passed the gate went to a room other than the intended one, 25 of
   them `spatial`, at calibrated confidence 0.90 to 0.95. Phase 7's session 2 false pass rate is
   0.0426. Phase 8 reported no e2e150 false pass figure.
3. **The e2e150 spatial labels are inverted for left and right.** `SPATIAL_ANCHORS` in
   `scripts/run_trials.py` derives each label from `AnnotationGraph.related_rooms(anchor,
   relation)`, the raw edge direction D34 established is wrong for this query. The resolver's
   `relations.resolve_relation` correctly queries the inverse relation. Edge `kitchen right_of
   reception` means reception is to the **left** of the kitchen, so "the room to the right of
   the kitchen" is `meeting_room_a` (edge `kitchen left_of meeting_room_a`), not `reception` as
   labelled. Six of the ten spatial phrasings are affected; the four `near` phrasings are
   symmetric and correct. "The room to the right of the office" has **no** target in the graph,
   so the correct outcome is abstention, and the resolver did abstain, but it was scored as a
   failure. The import-time assertion checks agreement with the same wrong function, so it
   could not catch this.
4. **Spatial resolution nearly fails on unambiguous commands.** Rescored against corrected
   labels, 2 of 30 production spatial rows are correct (1 of 30 under the inverted labels), and
   all 25 wrong spatial passes stay wrong. Phase 5A's 0.615 `spatial` figure came mostly from
   correct abstention on rows relabelled to `none`; its original-label figure was 0.215.
5. **Every Phase 8 latency number is contaminated, and D56's reason for the 50-row ablations is
   factually wrong.** The model ablation's `llama-server` ran from 04:13 to 07:27 IST, across
   the production suite (04:24 to 05:24), grammar-off (05:25 to 05:45) and most of gate-off
   (05:47 to 08:16). D56 cites a production suite of "about 3 hours"; its timestamps span one
   hour, and the 50-row grammar-off run took 20 minutes.
6. **The traceability item was ticked but nothing under `data/` was committed.** `data/runs/`
   and `data/bags/` are gitignored, and the report cites an uncommitted `/tmp/launch2.log`.
   Phase 7 had already flagged this.
7. **`colcon test` passed 4 of 5.** CLAUDE.md requires a full pass before a PR. Phase 7 recorded
   5 of 5 on the same code, so "pre-existing on main" conflicts with the record. Unverified
   hypothesis: the running `semantic_nav.launch.py` stack on the same `ROS_DOMAIN_ID` answered
   `/list_rooms` during the test; the Phase 8 report already records one such collision.
8. **Smaller defects.** D55 and D56 were never appended to section 14 (done in this replan).
   `t_nav_start` is null on 79 of 150 production rows, so time to navigation start rests on 71
   rows. Three rows have `e2e_ms < resolver_ms`, which implies two clocks. `success_rate` counts
   a spoken clarification as success (Phase 6 section 3.2) and is not a task metric. The model
   ablation reports original labels only, and its top-3 denominator is 455 (adversarial rows
   excluded) without saying so. RESULTS.md cites D41 where it means D44, gives "96 of 500"
   where the relabel is 99 of 130 (D42), shows Phase 4 top-3 as n/a although 0.780 to 0.789 was
   measured, and omits top-3 from the specification metrics table.

What stands, and should be said so plainly: 0/150 out of graph with the grammar on; the model
ablation's accuracy columns (Phi-3 mini 0.650 cross-checks 5A's 0.646; Phi-3.5 mini 0.654 is a
tie, which reverses D36's "7 points worse" from the 100-row slice); the full-graph trial runner;
the D55 telemetry; the production suite's navigation, which has no off-map row (row 138 has a
null pose and is the only invalid one).

### 11A.1 Freeze the relabel rule, then rescore without inference

Same discipline as 8A.2: write the rule, commit it, then run it.

- **The rule:** for each spatial command, the intended room is whatever
  `relations.resolve_relation(graph, anchor, relation, command)` returns for the command's own
  `(anchor, relation)` pair from `SPATIAL_ANCHORS`, or `"none"` when it abstains. This is the
  resolver's own traversal, whose direction D34 tested against natural-language meaning. It
  never sees a model output.
- **Commands stay byte-identical.** Do not rewrite or replace any spatial phrasing to give
  `meeting_room_b` a spatial target again; choosing commands after seeing results is the thing
  this phase exists to avoid. The "right of the office" row becomes an abstention row, and the
  report says so.
- Add a test that would have caught the inversion independently of both functions: a
  hand-written table of the six left/right phrasings with the answer read off the edge
  direction in `room_annotations.json` (for example, "right of the kitchen" is
  `meeting_room_a`), asserted against the corrected labels.
- Rescore `e2e150_loopback.jsonl` against the corrected labels. `reached_intended` for spatial
  rows is recomputed from the stored `pose_x`, `pose_y` against the corrected room's pose with
  the same 0.5 m tolerance. Keep the original-label numbers alongside, as 5A did.

### 11A.2 Metric definitions, fixed before any rerun

Change `ml/safenav_ml/e2e_report.py` so these are separate quantities, each reported with its
own numerator and denominator:

| metric | definition |
|--------|-----------|
| acted rate | `gate_passed` / n |
| wrong-room action rate (the specification's "false start") | `gate_passed and attempted_room != intended` / n, and also / acted |
| correct abstention | intended `none` and not acted / rows with intended `none` |
| resolver correct | `attempted_room == intended` (with `none` for abstention) / n |
| navigation reach, given a correct acted resolution | `reached_intended` / correct acted rows; a simulator health figure, not a task metric |
| navigation-invalid rows | final pose outside the map bounds, or null; excluded from reach and counted |
| nav_result succeeded | kept, relabelled as BT completion, with the Phase 6 section 3.2 note |

Loopback navigation is deterministic given the resolved room (D49), so the Condition B versus C
comparison is the wrong-room action rate, not reach. Reach is reported only for valid rows.

### 11A.3 Harness fixes

- `SPATIAL_ANCHORS` labels corrected per 11A.1, and its import-time check switched from
  `related_rooms` to `resolve_relation`. The 11A.1 table test stays as the independent check.
- **Off-map guard.** After each goal, if the final pose is outside the map bounds (read from the
  map YAML, not hardcoded) the row is marked `nav_invalid`, and after three consecutive invalid
  rows the suite stops, so a diverged simulator cannot quietly fill a suite. On a stop: relaunch
  the stack, resume from the stopped row, and record the restart in the report.
- **One fresh `semantic_nav.launch.py` per suite.** No suite starts on a stack that served an
  earlier suite.
- `t_nav_start`: find out why it is null on 79 of 150 rows (likely no `/cmd_vel` inside the
  capture window when the robot is already at the goal, or a capture race), fix it if it is a
  capture bug, otherwise define the null case, and report n beside every percentile.
- Record which clock each timestamp comes from; if `resolver_ms` and `e2e_ms` come from
  different clocks, say so rather than mixing them.

### 11A.4 Clean reruns: gate off and grammar off, 150 each

Run sequentially, never concurrently with each other or with any other GPU work:

1. Fresh host `llama-server` (production model, Metal), `ps aux` checked clean of other
   inference, nothing else running on the GPU for the duration.
2. Fresh stack, then **gate off** (`--gate-threshold 0.0`, grammar on) at the full 150 (3
   trials). Grammar and model are identical to production, so its `resolver_ms` is also the
   clean production-configuration resolver latency for this phase.
3. Fresh stack, then **grammar off** (gate at 0.85) at the full 150.
4. Production is not rerun: its resolver outputs and its navigation are valid (11A.0, last
   paragraph). Rescore it under 11A.1 and 11A.2.

Compare gate on (production, 150) against gate off (rerun, 150) on the wrong-room action rate,
with a per-category breakdown. Grammar off: report the out of graph count at n = 150 alongside
D24's 5/500.

**Whatever the gate comparison shows is the result.** If the gate makes no measurable
difference on e2e150, that is the finding, and it is consistent with finding 2: this command set
contains almost no low-confidence wrong answers for the gate to catch. Do not add, remove or
rephrase commands to change it.

### 11A.5 Condition B versus C where the gate has something to catch, offline

No inference: use the cached `data/runs/phase5a_full500.jsonl` with the Phase 7 feature
reconstruction, and `data/runs/calibration/session2_trials.jsonl`. For each, report the
wrong-room action rate and the acted rate at threshold 0.85 versus 0.0, per category. This
places the e2e150 result beside the two sets where the gate was designed to act, so the report
can say where the gate helps and where it does not.

### 11A.6 Calibrator diagnostic, no retraining

For e2e150 production, tabulate the five section 12.8 features for wrong passes against correct
passes (mean and range of `raw_confidence`, `edit_distance`, `command_length`, `token_entropy`;
`n_candidates` is constant, D53). State plainly whether the wrong spatial passes are separable
on any feature. Do not retrain, re-threshold, or add features. This feeds 16A O1 and O2, and the
report notes that a 26 of 140 wrong-pass rate on relational commands is evidence against
relaxing the false pass bound to 0.15 in O2.

**Corrected by D63 (2026-10-14, after 8B merged).** 8B ran this as written and concluded the
wrong spatial passes are not separable and are evidence for O1. The cause is a resolver double
hop (section 11B.0 finding 1), which no calibrator feature can see, so that conclusion does not
bear on O1. The argument against relaxing O2's bound still holds.

### 11A.7 Model ablation: clean latency and corrected labels

- Accuracy is not rerun. Add a corrected-label (`synthetic_500_v2.jsonl`) top-1 column computed
  from the existing `data/runs/model_ablation/*.jsonl`, and state the top-3 denominator.
- Latency is re-measured in isolation for all three models: held-out 100 slice, one fresh
  `llama-server` per model, nothing else on the GPU, the `cold_latency_remeasure.py` protocol
  (server-reported timings, first-call outlier reported rather than dropped). Report p50, p90,
  p99 and `predicted_per_token_ms`. Phase 8's contended latency columns stay in RESULTS.md,
  marked superseded.

### 11A.8 Tests

Run `colcon test` with no launch stack up, and with `ROS_DOMAIN_ID` set to a value no running
stack uses. If `test_annotation_map_node_launch.py` passes, record that the Phase 8 failure was
environmental. If it still fails, diagnose it; fix the test only where the defect is in the
test or its fixture loading, and record it as a deviation. 5 of 5 before the PR.

### 11A.9 Freeze the data so the results are traceable

Commit small run files to a tracked location, `data/frozen/`, with a `MANIFEST.md` giving the
sha256, row count, producing commit and command for each file: the three Phase 8 e2e150 files
as they were (prefix `phase8_`), the two 8B reruns, the corrected spatial labels,
`data/runs/model_ablation/*.jsonl`, `phase5a_full500.jsonl`, and the two calibration trial
files. Together they are about 2.5 MB. Bags (112 MB) stay uncommitted: record their path,
size and `metadata.yaml` sha256 in the manifest. Every table in RESULTS.md cites a file in
`data/frozen/` from now on.

### 11A.10 Documents: amend, never rewrite

- `docs/reports/phase-8-e2e-validation-results.md`: a dated amendment banner at the top naming
  each withdrawn claim and the 8B report that replaces it. Body untouched.
- `docs/reports/phase-6-bt-plugin-e2e.md`: a banner noting that the section 3.3 example "the
  room to the left of the kitchen" resolved to `kitchen`, which is wrong (`reception` is left of
  the kitchen), so it shows the hop path executing, not resolving correctly.
- `docs/results/RESULTS.md`: amendment banner, then correct sections 1, 3, 4, 5, 6 and 7 in place,
  keeping each superseded figure visible with a "superseded by 8B" note rather than deleting it.
  Fix the defects in 11A.0 item 8. Add top-3 to the specification table with its full history
  (0.97 in the Review 2 table and plan v1; 0.88 in the v2 redraft; 0.85 in the 5A plan; no
  deviation recorded for either change), reporting 0.868 against both 0.85 and 0.97, the way
  section 1 reports gated accuracy against both 0.75 and 0.824. Record that as this phase's
  first deviation and add a top-3 row to section 1's provenance table.
- Section 1 of this plan: replace the two "pending 8B" rows in Current metric status with
  measured values, and revise the "one metric is a miss" sentence to match.
- `README.md` results summary: add the spatial finding and the gate result as measured.
- Stale wording found in the same review, each corrected in place with a "Corrected by D57"
  note, nothing deleted: D45's last sentence ("a 3000 ms gate taken from the specification, not
  set by judgment"; it is internally set per D54); section 1 Targets prose ("the accuracy gate
  the specification actually asks for is the gated end-to-end 0.85"; it is >= 0.75 per D54);
  section 13 ("the hardware profile uses the specification's 3000"); 16A O1's "D23's seam
  contract" (the seam is section 8.2 and D28); `docs/archive/superseded-decisions.md` S6 (0.85
  "still required" and "the specification's own metrics table"), as a note at the end of S6.

### 11A.11 What not to do

- No change to the resolver, grammar, prompt, cue list, calibrator, threshold or annotation
  graph. 16A O1 and O2 stay deferred; this pass only measures.
- No rewriting of e2e150 commands, and no labels derived from model outputs.
- Nothing runs concurrently on the GPU while a latency figure is being collected, and
  `colcon test` never runs while a launch stack is up on the same domain.
- No re-tuning in response to the gate result or the spatial result. Both are findings.
- Do not delete Phase 8's files, tables or report text; supersede them visibly.

### DoD

- [ ] Relabel rule committed before running; the 11A.1 table test passes; production rescored
      against corrected and original labels, both reported.
- [ ] `e2e_report.py` reports the 11A.2 metrics separately, with numerators and denominators.
- [ ] Off-map guard, per-suite fresh stack, and the `t_nav_start` finding implemented or
      documented; any guard stop recorded.
- [ ] Gate-off rerun at 150 and grammar-off rerun at 150, sequential, GPU isolated, zero
      navigation-invalid rows or every one accounted for.
- [ ] Condition B versus C wrong-room action rate on e2e150 (150 versus 150), with per-category
      breakdown, reported as measured.
- [ ] Offline B versus C on the corrected 500 benchmark and session 2 (11A.5).
- [ ] e2e150 wrong-pass count and rate, and the 11A.6 feature table.
- [ ] Clean resolver p90 from the gate-off rerun, and the isolated three-model latency table.
- [ ] Model ablation corrected-label top-1 column and stated top-3 denominator.
- [ ] `colcon test` 5 of 5 with no stack up, or a recorded fix.
- [ ] `data/frozen/` with `MANIFEST.md`; every RESULTS.md table cites it.
- [ ] Amendments in 11A.10 made; no Phase 8 text deleted.
- [ ] Report `docs/reports/phase-8b-corrective.md` written, PR merged.

Gate: every claim in RESULTS.md and README.md is supported by a frozen file. The Condition B
versus C result is reported as measured, whatever it is.

### 11A.12 Git flow and numbering

```
git checkout main && git pull
gh issue create --title "Phase 8B: corrective pass" --body-file <file> --label phase
git checkout -b phase-8b/corrective
```

PR title `Phase 8B: corrective pass`, body as CLAUDE.md specifies, `Closes #<issue>`. Tick the
8B status row and fill in issue and PR numbers before merging. **This phase's deviations start
at D58**: D55 and D56 were Phase 8's, D57 is this replan. Section 11 and this section's scope
text stay as written.

## 11B. Phase 8C: spatial anchor fix

Added 2026-10-14 after a review of Phase 8B (#27). Numbered 11B after the 11A precedent.

**You are a new session and you did not run Phase 8 or 8B.** Read these, in this order, and
nothing else in this file unless a step below sends you there: this section; section 1 (Current
metric status); section 8.1 and section 12.6 (the two field contract this phase amends); D57 to
D63 in section 14; `docs/reports/phase-8b-corrective.md`. Then read the code you will change:
`_resolve_llm` in `semantic_waypoint_planner/resolver_core.py`, `relations.py`,
`scripts/llm_resolver.py` (`_encode_reasoning`) and `scripts/run_trials.py`.

Goal: fix the post decode step that applies the relational hop a second time, measure the fix on
held-out data without new inference, confirm it once end to end, and correct the 8B claims the
review found wrong. Timeboxed at **0.5 day of human time plus about 1 h of unattended runs**
(one e2e150 suite). The prompt, grammar, cue list, calibrator, threshold, model and annotation
graph do not change.

### 11B.0 What the review of 8B found

1. **The e2e150 spatial failures are a double hop, not a calibrator problem.** For "the room to
   the left/right of X", Phi-3 mini fills the v2 grammar's `room` field with the **answer**, not
   the anchor X, against the template's instruction ("set room to the location it is relative to
   (not the answer)"). `_resolve_llm` then applies `resolve_relation` to that answer, so the final
   room lands two hops along the chain. A local probe (production resolver, in process, Metal,
   temperature 0.3, three runs per command, not committed) reproduced the stored e2e150 outputs:

   | command | model's `room` (3 of 3) | correct answer | final after the second hop |
   |---|---|---|---|
   | right of the kitchen | meeting_room_a | meeting_room_a | meeting_room_b |
   | right of meeting room a | meeting_room_b | meeting_room_b | office |
   | right of meeting room b | office | office | none |
   | right of the charging dock | storage_room | storage_room | lab |
   | left of the lab | storage_room | storage_room | charging_dock |
   | near meeting room a | storage_room | storage_room | meeting_room_a |

   The model was right on 18 of 18 calls before the second hop. The pattern does not depend on
   the left/right convention: every final answer is exactly two hops from X. The other `near`
   misses ("near the kitchen" and "near meeting room b" both give `storage_room`; "near the
   workshop" varies) are ordinary model errors. A likely trigger is the adjacency block's
   wording ("storage_room is ... left of lab"), which matches "left of the lab" word for word.
   The 500 benchmark could not show this: most of its `spatial` rows are "beside / next to"
   phrasings labelled `none`, and its model outputs mostly do follow the anchor contract.
   Consequences: 11A.6's conclusion that the wrong spatial passes are "not separable on any
   feature" and are evidence for 16A O1 rests on the wrong cause. They carry 0.90 to 0.95
   confidence because the model's own answer is correct, so no calibrator feature can separate
   them. Section 1's note "consistent with the gate passing 25 of 30 spatial commands ...
   regardless of threshold" also points at the gate when the defect is in the resolver.
2. **The e2e150 rows do not record the anchor.** `anchor_room`, `relation` and
   `n_relation_targets` already reach `/semantic_goal_result` inside the `reasoning` JSON string
   (`_encode_reasoning`, and `semantic_goal_node.cpp` forwards `reasoning`), but
   `run_trials.py` never stores `reasoning`. This is a harness gap only, with no interface change.
3. **`offline_gate_comparison.py` counts a `none` answer as an action.** Line 112 defines acted
   as `calibrated_confidence >= threshold`, so at threshold 0.0 every abstention is "acted" and a
   `none` on a resolvable row is scored as a wrong-room action. Gate-on figures are unaffected.
   With acted defined as e2e150 defines it (a real room that passes the gate):

   | set | 8B gate-off wrong-room | corrected gate-off wrong-room | gate on (unchanged) |
   |---|---|---|---|
   | corrected 500 | 0.268 (134/500) | 0.248 (124/500) | 0.056 (28/500) |
   | session 2 | 0.290 (29/100) | 0.190 (19/100) | 0.020 (2/100) |

   The 8B report also omits the gate's cost in correct actions: on the 500 it avoids 96 wrong
   rooms and gives up 71 correct ones (297 to 226); on session 2 it avoids 17 and gives up 26
   (71 to 45). "Roughly a factor of five" holds only for the 500.
4. **`t_nav_start` is cited against the wrong file.** "90 of 91 null rows in the production
   file" describes the two 8B rerun files; the production file has 79 nulls, 77 of them at the
   previous row's pose. The reruns have more nulls than production, so the claim that
   `_drain()` "improves capture" is not supported. D59's heading calls it a capture bug "fixed"
   while its body says it is not a bug.
5. **Deviation cross-references.** Section 1's two e2e150 rows cite "measured (D58)"; D58 is the
   top-3 history and the result is D62. The 8B report's section 4 lists D58 to D61 and omits D62.
6. **The clean production latency was never written up.** Through the full ROS path with the GPU
   isolated (8B gate-off rerun, grammar on, production model, n = 150), resolver p50 is 3797 ms
   and p90 is 5160 ms. It appears only inside `docs/results/e2e150_report.md`, although the 8B
   DoD box for it is ticked. It matters to Phase 9: the p90 exceeds the 5 s BT tick timeout
   default in the Review 2 table.
7. **The isolated latency gap is attributed without evidence.** 8B's isolated Phi-3 mini
   traffic weighted p90 is 4494 ms against 5A's 3737 ms, with decode at 164 ms per token
   against about 138 ms earlier, put down to "session variance (thermal state, background load)".
   Nothing measured supports that. It stays an open item, not a closed one.
8. **The Phi-3.5 finding is real but narrow.** 0.764 against 0.726 corrected top-1 is
   significant on a paired exact McNemar test (45 rows only Phi-3.5 gets right, 26 only Phi-3
   mini, p = 0.032), but 12 of the net 19 come from `multi_hop` (18 against 6), single run, and
   run to run variation of the same model is about 0.6 points (0.726 against 5A's 0.732). Its
   top-3 column is still on original labels while top-1 is corrected. Whether Phi-3.5 follows
   the anchor contract better is untested.

What 8B got right stands: the relabel, the metric split, the reruns, the frozen data, 5 of 5
tests, and 0.173 against 0.187 on e2e150 (re-gating the 8B gate-off rerun at 0.85 rejects
exactly 2 rows, both wrong `negation`, giving 26/150, the same as production).

### 11B.1 Telemetry first, before any fix

- `run_trials.py` stores `reasoning` verbatim and parses its JSON into `model_room`,
  `anchor_room`, `anchor_source`, `relation`, `n_relation_targets` and `grammar_version` columns
  (empty when absent). No message, service or C++ change.
- `_encode_reasoning` adds `model_room` (the raw `room` field the model emitted) and
  `anchor_source` (`text` or `model`, from 11B.2), so a row shows what the model said and which
  anchor the hop used.
- A unit test round-trips one hop result through `_encode_reasoning` and the harness parser.

### 11B.2 The fix: anchor from the command text, one hop in code

Freeze the rule as code and tests, commit it, then run anything. The rule:

1. Applies only when the command is cued (8A.1), the grammar is on, the model's `relation` is
   one of `left_of`, `right_of`, `adjacent`, `near`, and the model's `room` is a canonical name
   (not `none`). Everything else keeps current behaviour: `within` legitimately anchors on a sub
   location, `relation == "none"` means the model's `room` is the answer, and a `none` room is
   the model abstaining, which this rule never overrides.
2. **Text anchor.** Normalize the command (lowercase, punctuation to spaces, collapsed
   whitespace), find the end of the first cue phrase from `relational_cues.json`, and search the
   remainder for canonical names (underscores as spaces) and aliases, longest match first, on
   word boundaries (so "dock" does not match inside "docking bay"). Keep only rooms that appear
   in at least one `edges` entry; sub locations have no edges and cannot anchor a left, right,
   adjacent or near hop.
3. If exactly one distinct room is found, it is the anchor (`anchor_source = "text"`) and the
   hop is `resolve_relation(graph, text_anchor, relation, command)`, applied once. The model's
   `room` is ignored for the hop but kept as `model_room`.
4. If zero or more than one distinct room is found, fall back to the model's `room` as anchor
   (`anchor_source = "model"`), which is today's behaviour.
5. The relation is always the model's. Changing it is a separate decision.
6. A resolver parameter `text_anchor` (default `true`, overridable in `planner_params.yaml` and
   the node) switches the rule off, so the old path stays reproducible.

Put the extraction in `relations.py` as a pure function and call the same function from the
resolver and from 11B.3's replay. Never reimplement it in the replay.

Tests before measuring:
- Extraction truth table: each of the 10 e2e150 spatial phrasings gives its anchor room (for
  example "Go to the room to the right of the meeting room a." gives `meeting_room_a`); "beside
  the docking bay" gives `storage_room`, not `charging_dock`; a command naming two edge-bearing
  rooms after the cue gives none; a sub location after the cue gives none; "the room with the
  coffee machine" is not routed through this rule.
- Resolver level, with the stub backend in `test_resolver_core_offline.py`: model output
  `{"room": "meeting_room_a", "relation": "right_of"}` for "Go to the room to the right of the
  kitchen." resolves to `meeting_room_a` with `anchor_source == "text"`; with
  `text_anchor=False` it resolves to `meeting_room_b` (the current behaviour, kept as a
  regression record).

### 11B.3 Measure on held-out data by exact replay, no inference

The prompt and grammar are unchanged and the fix acts after decoding, so the model's output on
every cached row is what it would emit again (up to temperature 0.3 sampling). Replaying the
stored `room` (the cached `anchor_room` when `relation != "none"`, else `resolved_room`) and
`relation` through the new post-decode step gives the exact paired effect of the fix with no
sampling noise. Write `ml/safenav_ml/replay_text_anchor.py` to do this for:

- `data/frozen/phase5a_full500.jsonl` against `synthetic_500_v2.jsonl`: top-1 corrected and
  original, per category, before and after, plus the list of every row whose final room changes,
  with its category and whether it moved to or from correct.
- `calibration_session1_trials.jsonl` and `calibration_session2_trials.jsonl`: final room
  before and after, and `edit_distance` recomputed against the new final room (section 12.8
  computes it on the final room). Recompute calibrated confidence through the deployed
  calibrator, the same way 8B's `offline_gate_comparison.py` reconstructs it.
- Report session 2 false pass and false rejection at 0.85, and the gated 500 accuracy (the
  `gated_benchmark_500` path in `train_calibrator.py`), before and after.

**e2e150 is the development set.** The rule was designed from the e2e150 evidence in 11B.0, so
its e2e150 improvement shows the fix works as intended but does not count toward 11B.5's
decision. The 500 and the two calibration sessions are the held-out evidence.

### 11B.4 One live confirmation: e2e150 production at 150

Fresh host `llama-server` (production model, Metal), nothing else on the GPU, fresh
`semantic_nav.launch.py`, and the 8B launch health check: "Managed nodes are active" twice in
the launch log and no persisting "out of bounds" or "no map received" warning before the suite
starts. Then production configuration (grammar on, gate 0.85, `text_anchor` on) at the full
150, with `--no-bag` per D56 practice.

- Score against the corrected labels with the 8B `e2e_report.py` metrics.
- Re-gate the same rows at 0.0 offline for Condition B versus C (the gate never changes the
  resolved room, and every row stores `calibrated_confidence`). No separate gate-off run.
- From the new columns, report for every left/right row whether `model_room` equals the
  corrected answer. This confirms 11B.0 finding 1 from committed data, replacing the uncommitted
  probe.
- Report resolver p50/p90/p99 from this run beside 8B's 3797/5160 ms; the fix adds no tokens,
  so a large shift means contention and the run is suspect.

Expected from the probe: about 18 spatial rows move to correct (2/30 to about 20/30) and
wrong-room actions fall from 26 to about 11. If the live run differs materially, report the
difference; do not adjust the rule.

### 11B.5 Decision rule, frozen now

`text_anchor` ships default **on** only if both hold on the held-out replay:

- session 2 false pass at 0.85 stays at or below 0.05 with the recomputed features; and
- the corrected 500 top-1 does not fall (paired: rows gained minus rows lost is at least zero).

Otherwise the default is **off**, both sets of numbers are reported, and the reason goes to the
next phase. Either way, do not retrain the calibrator, move the threshold, or edit the prompt in
this phase; recalibration on the fixed resolver belongs with 16A O1, which retrains anyway.

### 11B.6 8B corrections

- `offline_gate_comparison.py`: acted means a real room (not `none`) passing the threshold.
  Regenerate `docs/results/offline_gate_comparison.md` for the old resolver output, add the
  gate's cost in correct actions as a column, and add an after-fix table from 11B.3.
- `docs/reports/phase-8b-corrective.md`: dated amendment banner naming 11B.0 findings 1, 3, 4,
  5, 7 and 8 and pointing to the 8C report. Body untouched.
- `docs/results/RESULTS.md`: correct the offline gate table and the factor-of-five sentence in
  place (superseded figures kept visible), add the 3797/5160 ms ROS path latency row as its own
  measurement beside 5A's 3737 ms (not replacing it), mark 11A.6's interpretation as superseded
  by the double-hop finding, add the McNemar result and the `multi_hop` concentration to the
  Phi-3.5 note, and add the 8C before-and-after tables.
- Section 1 of this plan: fix the two e2e150 rows' citation (D62, not D58), update them with the
  8C numbers in a new row rather than overwriting 8B's, and add a "Corrected by D63" note to
  the amended paragraph's last sentence.
- D59: append a "Corrected by D63" note on the file citation and the "fixed" heading.
- Section 12.6 semantics paragraph: append a dated note recording the text anchor rule and its
  deviation number. The grammar itself does not change.
- `README.md` results summary: the double-hop finding and the 8C result as measured.

### 11B.7 What not to do

- No change to the prompt, few-shot file, grammar, cue list, calibrator, threshold, model or
  annotation graph. No new relation inference from text.
- Do not tune the extraction rule on the 500 or the calibration sessions. If a held-out row
  exposes an extraction bug, record it as a deviation with the row, fix only that defect, and
  report results both before and after the fix.
- No change to e2e150 commands or labels.
- No live rerun of the 500 or the calibration sessions; the replay is the measurement.
- Nothing else on the GPU during 11B.4.
- Phase 9 and 16A items stay out (11B.0 finding 7 is recorded, not investigated).

### DoD

- [ ] Telemetry (11B.1) committed with its test before the fix.
- [ ] Extraction rule and both test tables committed before any replay or run; unit tests pass.
- [ ] Replay on the 500 and both calibration sessions: before and after tables, every changed row
      listed, session 2 false pass and false rejection, gated 500 accuracy.
- [ ] 11B.5 decision applied and stated, with the numbers it rests on.
- [ ] e2e150 production at 150 with `text_anchor` on: 8B metrics, offline Condition B versus C,
      `model_room` check on every left/right row, resolver latency beside 8B's.
- [ ] 8B corrections in 11B.6 made; nothing deleted.
- [ ] New run and replay files in `data/frozen/` with `MANIFEST.md` entries.
- [ ] `colcon test` 5 of 5 with no stack up on an isolated `ROS_DOMAIN_ID` (a D61 flake is
      retried once and recorded if it recurs).
- [ ] Report `docs/reports/phase-8c-spatial-anchor-fix.md` written, PR merged.

Gate: the double-hop finding is confirmed from committed data, the fix's effect is reported on
held-out data with every changed row listed, and the default follows the frozen rule whatever
the numbers are.

### 11B.8 Git flow and numbering

```
git checkout main && git pull
gh issue create --title "Phase 8C: spatial anchor fix" --body-file <file> --label phase
git checkout -b phase-8c/spatial-anchor-fix
```

PR title `Phase 8C: spatial anchor fix`, body as CLAUDE.md specifies, `Closes #<issue>`. Tick the
8C status row and fill in issue and PR numbers before merging. **This phase's deviations start
at D64**: D58 to D62 were 8B's, D63 is this replan. The text anchor rule is this phase's first
deviation (it amends the section 8.1 and 12.6 contract).

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

**Amended 2026-10-14 (D64, Phase 8C).** For `left_of`/`right_of`/`adjacent`/`near`, the hop's
anchor is no longer always `room` as the model emitted it: `relations.apply_relational_hop`
prefers the single edge bearing room named in the command text after the first relational cue
(`extract_text_anchor`), falling back to the model's `room` on zero or more than one match.
`within` is unchanged (it still anchors on the model's `room`, a sub location by design). The
grammar itself (the GBNF form above) does not change; this amends only what `resolver_core.py`
does with the decoded `room`/`relation` pair. Ships with its default off (11B.5); see D64.

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
  specification's `3000`. Phase 9 writes the hardware profile. **Corrected by D57:** `3000` is
  internally set (D54), not taken from a specification with external authority.
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

D32 to D36 were recorded during Phase 5; see
`docs/reports/phase-5-relational-decomposition-resolver-backend.md` section 9. D37 to D39 are
the Phase 5A corrective replan.

- **D37: the Phase 5 raw top-1 gate of 0.80 was unachievable and is restated.** D32 established
  that 96 of the 500 benchmark rows have no unique correct answer given the graph's topology,
  putting the benchmark's own ceiling at about 0.81 even with a perfect resolver. The gate was
  set in plan v2 without checking the benchmark's answerability, which is a planning defect, not
  a measurement failure by Phase 5. Section 8A restated it as >= 0.76 against corrected labels
  with a 0.70 stop floor; that 0.76 was itself judgment-set and has since been withdrawn (D45).
  Section 1 carries the correction. Phase 4's 0.80 gate (D26) was
  unachievable for the same reason, which revises that deviation's "capability ceiling"
  conclusion: part of what both phases measured was a benchmark ceiling, not a model ceiling.
- **D38: the v2 relational grammar is applied conditionally, not unconditionally.** Commands
  carrying no lexical relational cue are resolved against the v1 single-field grammar with the
  hop suppressed; only cued commands take the v2 grammar. Reason: Phase 5 section 5.1 measured
  68 of 500 rows where a correct anchor was overwritten by a spurious non-`none` relation,
  concentrated in the categories D29 assumed would be unaffected. This supersedes D29's
  unconditional application while keeping its traversal mechanism intact for the cued case. It
  is also the latency remedy, since the v2 grammar's larger alternation is what Phase 5 section
  6 identified as the decode cost. Contingent on section 8A.1's pre-check: if cue recall on
  `spatial` and `multi_hop` is below 0.85, this deviation is withdrawn and the phase stops.
- **D39: the benchmark's structurally unanswerable rows are relabelled to `"none"`** in a new
  `data/benchmark/synthetic_500_v2.jsonl`, by a rule computed from the graph and command text
  alone with no visibility of any model prediction, frozen before execution.
  `synthetic_500.jsonl` is unmodified and both label sets are reported in every table from
  Phase 5A onward. Rationale: a command the facility graph cannot answer uniquely should
  produce a clarification request, so `"none"` is the correct label and the original was wrong.
  Exposure, stated plainly because it is real: the rule was designed after seeing Phase 5's
  results by the session that produced them, the same self-adjudication pattern as D25.
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

D40 to D44 were recorded during Phase 5A; see `docs/reports/phase-5a-corrective.md` section 8.

- **D40: cue gating recovers 49 of the 68 section 5.1 regression rows (72 percent), not all
  of them.** The remaining 19 contain a frozen cue phrase (8A.1) used non-relationally by the
  generator and still take the v2 grammar. Not retuned in response; reported as the honest
  residual.
- **D41: `audit_edges.detect_anchors` gained a label-blind mode** (`expected=None`) so the
  8A.2 relabel rule could reuse it instead of a second implementation; the Phase 5 ceiling
  check's call site is unaffected.
- **D42: the 8A.2 relabel produces 99/130 relabelled rows, not D32's 96/500.** Both are
  legitimate; they measure different properties (label recall vs. target uniqueness). Neither
  was adjusted to match the other.
- **D43: a first version of the 8A.3 latency script used a text-length proxy for token count**
  and produced a result backwards from both Phase 5's hypothesis and the corrected
  measurement. Caught before being written into the report; fixed to read the server's own
  `timings.predicted_per_token_ms` and rerun from a fresh server start.
- **D44: Phase 5's section 6 grammar-size latency hypothesis is not confirmed and is
  superseded.** Cold per-token decode cost is statistically indistinguishable between the v1
  and v2 grammars (137.7 vs 139.7 ms/token). The latency gate miss persists (3737 ms
  traffic-weighted p90 cold vs the 3000 ms gate) but is attributed to v2 generating more
  output tokens, not to a more expensive per-token grammar, and Phase 5's 7220 ms figure is
  attributed roughly half to a real thermal/sustained-load confound and half to this
  non-thermal baseline.
- **D45: the raw top-1 gate is withdrawn; Phase 5A's 0.732 is a result, not a shortfall.** The
  0.76 that D37 substituted for the unachievable 0.80 was set by judgment, as the derived 0.81
  ceiling minus a margin, and was not derived from the specification, a baseline, or a power
  calculation. It is also inside the measurement's own error: at n = 500 a proportion of 0.732
  carries a standard error of 0.020 and a 95 percent interval of about [0.693, 0.771], which
  contains 0.76, so this benchmark cannot distinguish the two at this sample size. The gap is 14
  rows. Phase 5A's 0.732 is therefore recorded as the measured resolver capability on the
  corrected labels, about 90 percent of the derived ceiling, and not as a gate miss. The
  threshold is removed from section 1 and section 8A rather than lowered to fit the result:
  lowering a gate to match a measurement is the self-adjudication pattern D25 and D39 warn
  about, whereas removing an arbitrary threshold outright leaves nothing to adjudicate. 0.70 is
  retained only as an abort trigger for downstream work. **Corrected by D54:** this deviation
  originally closed by saying the one remaining pass or fail accuracy gate was Phase 7's gated
  >= 0.85, "which is what the specification asks for." The Review 2 metrics table was drafted
  inside this project and was never approved, so the 0.85 was also internally set and that
  sentence was wrong to treat it as external. The gated target is re-anchored at >= 0.75 on
  KnowNo. The rest of D45 stands: it never depended on 0.85's provenance, only on 0.76's.
  Recorded after Phase 5A merged (#19); the report carries an amendment note to the same effect.
  The latency finding is unaffected and remains a real miss: 3737 ms traffic-weighted p90 cold
  against a 3000 ms gate taken from the specification, not set by judgment. **Corrected by
  D57:** the 3000 ms gate is internally set, not taken from any specification (D54); it is
  looser than the HRI literature's 2000 ms recommendation, not stricter than nothing.
- **D46: `/semantic_resolution_result`, a new `std_msgs/String` JSON topic, not a section 12
  interface.** `NavigateToPose`'s result carries only `std_msgs/Empty`, so `semantic_goal_node`
  has no path back to the resolved room or confidence through the action itself.
  `SemanticNavigateToPose` publishes this side channel on success; `semantic_goal_node` caches
  it keyed by command text and merges it into `/semantic_goal_result`. Not safe for two
  concurrent goals sharing identical command text; out of scope for Phase 6 (one goal at a
  time). Phase 6 report section 2.
- **D47: `espeak-ng` subprocess and `/cmd_lightring` pattern not built.** Named optional in the
  plan's section 9 scope ("only add them if the phase is running ahead"); this phase was not
  ahead. `/tts_text` alone satisfies every Phase 6 DoD item.
- **D48: the `semantic_nav` lifecycle manager runs with `bond_timeout: 0.0`.**
  `semantic_goal_node` extends `rclcpp_lifecycle::LifecycleNode` directly, not
  `nav2_util::LifecycleNode`, so it does not implement the bond protocol that `map_server` and
  `bt_navigator` do; the first launch attempt failed lifecycle bring-up after a 4 s bond
  timeout before this was set. Disables the bond watchdog for the whole manager rather than
  mixing bonded and unbonded nodes under one `bond_timeout`.

D49 to D52 were recorded during Phase 7; see `docs/reports/phase-7-calibration.md` section 4.
D53 was added after Phase 7 merged, when the feature vector was audited.

- **D49: `run_trials.py` calls `ResolverCore` directly rather than driving the full
  `/semantic_goal` to Nav2 ROS graph**, following the Phase 5 `backend=http` host-script
  precedent (D28). The plan's text itself notes loopback navigation outcome is deterministic
  given the resolved room, so the full stack adds runtime without changing the calibration
  label. The `/semantic_goal`-driven suite is left to Phase 8's `e2e150`, which extends this
  script rather than replacing it.
- **D50: trial outputs live under `data/runs/calibration/` (gitignored), not
  `data/calibration/`.** `data/calibration/` is reserved for the committed source files
  (`session1_sim.jsonl`, `session2_sim.jsonl`); the trial JSONL is reproducible from those plus
  `run_trials.py`, matching the repository's existing `data/runs/` convention for run output.
- **D51: the default `confidence_threshold` is raised from 0.72 to 0.85** (the trained value) at
  every call site except `msg/SemanticGoal.msg`'s own comment, which documents a convention, not
  an enforced default, and was left untouched to avoid any edit inside a frozen interface file.
- **D52: gated end-to-end accuracy measured 0.72 and session 2 false rejection measured 0.3662,
  against targets of >= 0.85 and <= 15%, and this was not corrected by tuning on session 2.**
  Superseded in part by D53, which establishes that the feature vector these were computed from
  is not the one section 12.8 specifies and records both numbers as provisional. The root cause
  analysis below stands and was confirmed independently:
  the model's raw confidence barely separates correct from incorrect resolutions (session 1:
  0.925 mean correct versus 0.896 mean incorrect, both inside 0.75-0.99), so the <= 5%
  false-pass safety bound forces a threshold high enough to also reject about a third of correct
  resolutions. The two numbers share one cause rather than being independent; see the phase
  report for the per-category breakdown and the Phase 8 implication (the model ablation, not a
  calibration retune, is the plausible next lever).
- **D53: two of the five section 12.8 calibration features carry no information, so Phase 7's
  0.72 and 0.3662 are recorded as provisional and the gated accuracy comparison is deferred,
  not dissolved.** Measured directly on the 300 committed trial rows:
  `n_candidates` is 30.0 on every row (constant, trained weight exactly 0.0), and
  `token_entropy` is the binary entropy of `raw_confidence`, not an entropy over the room-level
  distribution that 12.8 specifies (Pearson -0.984; each of the six attainable
  `raw_confidence` values maps to exactly one entropy value, reproduced by
  `-p ln p - (1-p) ln(1-p)` to 12 decimal places). `raw_confidence` itself takes only six
  distinct values, since the grammar's `confidence-value` alternation restricts it. The
  calibrator therefore has three independent features, not five. Holding the specification's
  <= 5% false-pass bound, 0.3662 is the *provable optimum* false rejection rate for that vector
  (best achievable on the ROC at that bound, equal to the deployed value to four decimal
  places), which confirms D52's claim that no threshold retune helps and rules out a
  calibration-fitting explanation. Consequence for reporting: 0.72 is not a measurement of the
  system's gated accuracy against the specification, because the instrument it was taken with
  is incomplete, in the same way that Phase 5's raw top-1 was not a measurement of resolver
  capability while 96 benchmark rows were mislabelled (D32, D39). It is recorded as measured,
  marked provisional, and re-measured after section 16A.
  **Corrected by D54 on one point.** This deviation originally said the >= 0.85 "is taken from
  the specification's own metrics table, not set by judgment." That was wrong: the Review 2
  metrics table was drafted inside this project and was never approved, so 0.85 had no more
  external authority than the 0.76 that D45 withdrew. The target is re-anchored at >= 0.75 in
  D54. What survives unchanged is this deviation's actual content, which never depended on the
  threshold's provenance: the feature vector is defective, so 0.72 is provisional whatever it
  is compared against.
  If section 16A does not run, the honest reading is that the gap is unmeasured, not met.
- **D54: every numeric gate in this plan was internally set, including those routed through the
  Review 2 document, and the unmet ones are re-checked against the cited literature rather than
  withdrawn.** The Review 2 metrics table was drafted inside this project and was not approved,
  so D45's and D53's appeals to "what the specification asks for" were both unfounded; those
  sentences are corrected in place above. The gates are re-anchored on the primary sources, read
  from the papers themselves rather than from `docs/phase-4-brief.md`'s summary of them, which
  turned out to contain an error (below). Section 1 carries the provenance table. Findings:
  - **Gated accuracy: >= 0.85 replaced by >= 0.75.** KnowNo (Ren et al. 2023, CoRL,
    arXiv 2307.01928) sets `eps = 0.15` (target 0.85) for single-step settings and `eps = 0.25`
    (target 0.75) for multi-step tabletop rearrangement, achieving plan success 0.76 and task
    success 0.74 there against 0.87 and 0.76 on the single-step mobile manipulator. The 0.75 is
    usable, with the caveat recorded in section 1 that the mapping is an interpretation and the
    category-weighted alternative is 0.824.
  - **False rejection <= 15% is withdrawn as unfounded.** No cited work sets a false rejection
    gate. KnowNo reports *help rate* instead: 0.58 step-wise on multi-step, 0.67 on the mobile
    manipulator, 0.92 bimanual. The comparable measurement here is a help rate of **0.53** on
    session 2 (53 of 100 commands deferred), below every KnowNo setting, with precision on
    acted-upon commands of 0.957. False rejection stays as a reported diagnostic. The two
    quantities are not interchangeable and the report says so: help rate is over all commands,
    false rejection only over correct ones.
  - **Latency: re-anchoring makes this worse, not better.** Shiwa et al. (HRI 2008; IJSR 2009)
    find user impressions unchanged only up to 1000 ms and recommend reacting within 2000 ms,
    with conversational fillers effective beyond that; other HRI work puts degradation above
    about 4000 ms. The internal 3000 ms gate was already looser than that recommendation, and
    the measured 3737 ms cold p90 misses both. This stays a genuine, unmitigated miss. The
    citable remedy is Shiwa's filler result, which maps onto the existing `/tts_text` channel:
    acknowledge the command immediately, then speak the resolution. For scale, BTGenBot
    (Izzo et al. 2024, arXiv 2403.12761) needs 73 to 234 s per free-form behaviour-tree
    generation, so the grammar-constrained 3.7 s is 20 to 60 times faster than that comparator.
  - **ECE <= 0.08 is internally set and stays.** No peer-reviewed cutoff exists; Guo et al. 2017
    fixes only the 10-equal-width-bin method. Recorded for symmetry: this gate is as unanchored
    as the withdrawn one, and the measured 0.0730 compares favourably with the 0.09 to 0.73
    range Spiess et al. (ICSE 2025) report for LLM code-correctness confidence.
  - **False pass <= 5% is internally set and is stricter than the literature.** KnowNo's own
    failure level is `eps = 0.15`. This matters because the <= 5% bound is what forces the
    threshold to 0.85 and therefore causes the high false rejection. Indicative recomputation
    (session 2, threshold re-picked on session 1): at a 0.15 bound the threshold falls to 0.815,
    false rejection falls from 0.507 to 0.324, help rate from 0.650 to 0.500, and gated accuracy
    rises from 0.640 to 0.750. These are session 2 figures and are **not** comparable to the 0.72
    headline, which is measured on the 500 benchmark, and the reproduction of the deployed
    threshold is approximate (0.892 against the deployed 0.85), so this is a lead, not a result.
    Section 16A O2 carries it. **Relaxing a false pass bound is a safety decision, not a metrics
    choice**, and is left to the project owner: 15 percent means acting on a wrong room without
    asking in roughly one command in seven.
  - **Error found in an internal document.** `docs/phase-4-brief.md` section 6 attributes
    BTGenBot's inference timings to a Jetson AGX Orin. The paper states they were measured on an
    NVIDIA RTX Quadro 6000, a desktop GPU. A correction note is added there. This is why the
    gates were re-checked against the papers and not against that table.

D55 and D56 were recorded by Phase 8 in its report and PR but not appended here; they are
appended now, unchanged in substance. D57 is the Phase 8B corrective replan.

- **D55: `/semantic_resolution_result` publishes on every resolver response, not only on gate
  pass.** It carries `resolver_mode`, `out_of_graph`, `token_entropy`, `reasoning`, `success`,
  `gate_passed`, `threshold_used` and a new `attempted_room`; `resolved_room` keeps its meaning
  (empty unless the gate passed). `semantic_goal_node` merges the same fields into
  `/semantic_goal_result`. Extends the D46 side channel, not a section 12 interface. Phase 8
  report section 1.
- **D56: Phase 8 measurement reductions.** The grammar-off and gate-off ablations ran at 50
  rows (1 trial) instead of 150; all three e2e150 suites and the model ablation ran
  concurrently on one Mac, so every Phase 8 latency figure includes GPU contention; the three
  suites shared one un-reset launch session; a first production attempt corrupted by a
  concurrent `colcon test` was discarded and rerun. Phase 8 report section 2.
  **Corrected by D57 on one point:** D56 justifies the 50-row ablations by a production suite of
  "about 3 hours". The suite's own timestamps span one hour (04:24 to 05:24 IST) and the 50-row
  grammar-off run took 20 minutes, so a full 150 for both ablations was roughly two more hours,
  not a multi-hour addition with no budget.
- **D57: Phase 8's gate-on versus gate-off headline is withdrawn as a simulator artifact, and a
  corrective pass, Phase 8B (section 11A), is added.** Found in a review of Phase 8's run files
  after merge (#25). On the same 50 commands the resolver acted on 47 with 8 wrong (gate on,
  production trial 0) and 48 with 10 wrong (gate off); the gate rejected a real room twice in
  all 150 production rows. The reported 0.080 reached-intended comes from 45 of 50 gate-off
  rows ending off the map while Nav2 reported `succeeded`, counted as false starts by a metric
  that conflated navigation failure with a wrong resolution. The review also found the gate
  passing 26 wrong rooms of 140 acted-on commands (25 `spatial`, calibrated confidence 0.90 to
  0.95) against Phase 7's 0.0426 session 2 false pass rate; the e2e150 left and right spatial
  labels inverted by the D34 direction error, in the suite rather than the resolver; spatial
  correctness of 2 of 30 under corrected labels; contaminated latency; uncommitted run data;
  and a 4 of 5 `colcon test` result. What stands: 0/150 out of graph with the grammar on, the
  model ablation's accuracy columns, and the engineering. Section 11A lists each finding with
  its evidence and the work that corrects it. Phase 8 is marked merged and its section 11
  outcome paragraph carries a "Corrected by D57" note; nothing Phase 8 wrote is deleted.
- **D58: the resolver top-3 target was re-anchored three times across plan revisions with no
  deviation recorded for either change, and section 1's provenance table now carries it.** The
  gate was 0.97 in `docs/reference/Review_2_Phase_2.docx`'s table and plan v1, 0.88 in the v2
  redraft, and 0.85 in the 5A plan, none of which cited a reason. Treated the same way D54
  treats every other gate: internally set, kept rather than deleted, and the measured 0.868
  (5A) is now reported against both 0.85 and 0.97 in section 1.
- **D59: the e2e150 spatial relabel (PLAN.md 11A.1) and the null `t_nav_start` capture bug
  (11A.3) are fixed in `scripts/run_trials.py`, both verified against the review's findings.**
  `SPATIAL_ANCHORS`'s import-time check called `AnnotationGraph.related_rooms(anchor,
  relation)` directly, the inverse of the direction the query needs; `CORRECTED_SPATIAL_LABELS`
  now derives each intended room from `relations.resolve_relation()`, the resolver's own
  traversal, with an independent hand-read test against the graph edges that does not call
  either function. Rescoring the committed production file against it reproduces the review's
  numbers exactly (2/30 spatial rows correct, 1/30 under the original inverted labels; 26 of
  140 wrong passes, 25 spatial). Separately, 90 of 91 null `t_nav_start` rows in the production
  file have an identical pose to the previous row: the robot was already at the target, not a
  capture failure. `TrialRunner._drain()` still improves capture (a single `rclpy.spin_once`
  per poll services at most one of five competing subscriptions, which can still starve
  `/cmd_vel` against busy `/odom` traffic during an actual move) but is not the main cause of
  the nulls Phase 8 reported. `e2e_report.py` reports n and the null count beside every
  percentile, per 11A.3, rather than silently dropping them.

  **Corrected by D63/D64 (2026-10-14).** The "90 of 91 null rows" claim cites the two 8B rerun
  files; the production file (the one Phase 8 and this heading's "fixed" claim describe) has 79
  nulls, 77 of them at the previous row's pose. The reruns have more nulls than production, so
  `_drain()` "improves capture" is not supported by this file; `_drain()`'s capture-ordering
  argument above stands on its own merits, independent of this count. The heading's "fixed"
  refers to the spatial relabel only; the null count was always a measurement, not a bug, per
  the paragraph's own text.
- **D60: `e2e_report.py`'s metrics are split per PLAN.md 11A.2, each with its own numerator and
  denominator, replacing Phase 8's single "false start" figure that conflated navigation
  failure with a wrong resolution (D57 finding 1).** Acted rate, wrong-room action rate,
  correct abstention, resolver correct, and reach given a correct resolution (valid rows only)
  are now separate columns, plus a per-category breakdown.
- **D61: two previously unknown flakes surfaced while rerunning e2e150 and `colcon test` for
  this phase, neither caused by this phase's changes, neither fixed (out of scope).** (1) A
  fresh `semantic_nav.launch.py` launch once left `lifecycle_manager_semantic_nav` stuck
  configuring `map_server`, which never activated; the resolver and annotation nodes came up
  regardless (not lifecycle-managed the same way), so commands were accepted while the robot
  drove with no map and went out of bounds. Killing the stack and relaunching fixed it; the
  8B rerun protocol now checks that "Managed nodes are active" appears twice in the launch log
  and that no "out of bounds"/"no map received" warnings persist before starting a suite.
  (2) `test_test_resolver_only_launch.py` failed once and passed on retry with no code change
  in between, on an in-process CPU-backend call for "somewhere I can charge the robot"
  returning an empty `matched_room_name`; consistent with D16/D18's documented CPU-backend
  latency variance under `temperature=0.3` sampling, not a deterministic defect. Both are
  recorded here rather than investigated further, since fixing either is outside this phase's
  scope (no resolver, launch-graph, or lifecycle-management changes).
- **D62: the e2e150 Condition B versus C result (11A.4) is that the gate makes no measurable
  difference on this command set.** Wrong-room action rate is 0.173 with the gate on
  (production, rescored) versus 0.187 with it off (8B rerun, 150 rows, fresh stack, isolated
  GPU); 148 of 150 rows resolve to the same room whether the grammar is on or off. Reported as
  measured, per 11A.4's instruction, with no threshold attached either way.
- **D63: a review of Phase 8B (#27) found the e2e150 spatial failures are a resolver double hop,
  and Phase 8C (section 11B) is added to fix it and correct 8B's claims.** For left/right
  commands Phi-3 mini emits the answer in the v2 `room` field instead of the anchor, and
  `_resolve_llm` hops again from it; a local probe reproduced the stored e2e150 outputs, with the
  model right on 18 of 18 calls before the second hop. This withdraws 11A.6's reading that the
  wrong passes are a calibrator separability problem and evidence for 16A O1. The review also
  found `offline_gate_comparison.py` counting `none` answers as actions (gate-off wrong-room
  0.268 and 0.290 should be 0.248 and 0.190), D59's `t_nav_start` claim citing the wrong file,
  section 1 citing D58 for the e2e150 result instead of D62, the 3797/5160 ms ROS path latency
  left out of RESULTS.md, the 4494 against 3737 ms isolated latency gap attributed without
  evidence, and the Phi-3.5 lead (p = 0.032, paired) concentrated in `multi_hop`. 8C fixes the
  resolver post-decode step only (anchor read from the command text, one hop in code, behind a
  `text_anchor` parameter), measures it by exact replay on the held-out sets with no new
  inference, confirms it with one e2e150 run, and amends the 8B documents. Nothing 8B wrote is
  deleted.
- **D64: the text anchor rule (section 11B.2) amends the section 8.1/12.6 contract and ships
  with its default off, per 11B.5's frozen decision rule.** For `left_of`/`right_of`/`adjacent`/
  `near`, the hop now anchors on the single edge bearing room named in the command text after
  the first relational cue, falling back to the model's own `room` field on zero or more than
  one match (`relations.extract_text_anchor`/`apply_relational_hop`); `within` is unchanged. On
  e2e150 (the rule's own development set, forced on for one diagnostic run,
  `docs/results/e2e150_report_8c.md`), spatial resolver correct goes from 2/30 to 30/30 and
  wrong-room gate-passed actions from 26/140 to 0/140, confirming D63's reading from committed
  data. On the held-out replay (`docs/results/text_anchor_replay.md`, 11B.3), session 2 false
  pass is unchanged (0.043) but the corrected 500's top-1 falls by one row net (6 gained, 7
  lost), every loss in a `multi_hop` compound sentence where the "first cue, nearest room"
  heuristic picks up the wrong clause's room (not tuned against, per 11B.7). `text_anchor`
  therefore ships `false` in `planner_params.yaml`, overridable per row by any future caller
  that wants the e2e150-style improvement on single-clause spatial commands at the cost of this
  `multi_hop` regression; a `multi_hop`-aware rule or a 16A O1 retrain are better next steps
  than tuning this one further. Also fixes `offline_gate_comparison.py` counting a `none`
  answer as an acted-on row (D63 finding 3): gate-off wrong-room action rate corrects from 0.268
  to 0.248 (500) and 0.290 to 0.190 (session 2); gate-on figures are unaffected.

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

## 16A. Optional scope: deferred improvements (only if time remains)

**Nothing in this section is committed work.** It is taken on only if Phase 8 and Phase 9 are
merged and time is genuinely left over. If the week runs to its budget, this section is not
started and the plan ends at Phase 9; that is the expected outcome, not a failure. Do not let
any item here displace, descope, or delay Phase 8 or Phase 9. Numbered 16A rather than 18 to
avoid renumbering section 17, following the 8A precedent.

### O1. Implement `token_entropy` against the real room-level logits

**Why.** D53 measured that `token_entropy` is currently the binary entropy of
`raw_confidence`, a value the model self-reports inside its JSON output. It therefore carries no
information the calibrator does not already have from `raw_confidence`, which leaves the gate
with three independent features instead of five and no genuine per-instance uncertainty signal
at all. Section 12.8 already specifies the correct quantity ("token_entropy (nats, room level
distribution)"), so this is an implementation fix, not an interface change: **12.8 is frozen and
stays exactly as written.**

**What.** Read the sampler's logit distribution over the first room-name token (or the
normalized distribution over the grammar's permitted room alternation at that position) from
llama.cpp, and compute the entropy of that distribution in nats. `llama-server`'s `/completion`
accepts `n_probs` and returns `completion_probabilities` per token, which is the cheapest route
and needs no change to the backend seam; the `llama-cpp-python` path would use `logits_all` or
the equivalent sampler hook. Keep both backends in agreement, since D23's seam contract requires
it, and add a unit test asserting entropy is 0 on a one-hot distribution and `ln(k)` on a
uniform distribution over `k` rooms. **Corrected by D57:** the backend seam contract is section
8.2 and D28, not D23.

**Then, and this is the part that makes it worth doing.** Retrain the calibrator on the existing
committed session files (no new Mistral calls, no new personas), re-pick the threshold under the
same <= 5% false-pass rule, and re-measure session 2 false rejection and the gated 500 accuracy.
Report all four numbers beside Phase 7's as a before-and-after. Write the new artifact as
`config/calibrator.json` version 2 with regenerated `calibrator_parity_vectors.json`; keep the
Phase 7 artifact alongside it rather than overwriting, per the 8A.5 preserve rule.

**Cost.** About half a day, of which the retrain and re-measure is under an hour of compute
because the resolver runs are cached and only the feature column changes. The 300 trial rows do
need re-running to obtain the new feature, which is roughly 20 minutes of background inference.

**Honest expectation.** This may not move the numbers. A real room-level entropy is the signal
the feature set currently lacks entirely, which is why it is the first thing to try, but the
underlying model may simply be poorly separated, in which case the result is a negative finding
worth recording rather than an improvement. Either way it closes D53 and makes the gated
accuracy comparison meaningful for the first time. Do not retune anything else while doing it,
and do not touch the benchmark labels.

**Not in scope here.** `n_candidates`, the other dead feature, stays as it is. It is constant at
30.0 because the annotation graph always offers the same 30 rooms, and redefining it would
require editing frozen section 12.8. Leave it documented as dead in D53 and do not change it.

### O2. Re-pick the confidence threshold under a literature-anchored false-pass bound

Cheaper than O1 and higher value, so do this one first if only one is possible. **About an hour,
no new inference**: the five features for all 300 trial rows and the cached 500 benchmark run
are already on disk, so only the threshold choice and the metric recomputation change.

**Why.** D54 established that the <= 5% false pass bound is internally set and stricter than
KnowNo's `eps = 0.15`, and that this bound is what forces the threshold to 0.85 and so causes
the 0.3662 false rejection. The indicative session 2 recomputation in D54 suggests a 0.15 bound
lifts gated accuracy to about 0.75 and cuts false rejection to about 0.32.

**What.** Re-pick the threshold under bounds of 0.05, 0.10 and 0.15 using the existing
out-of-fold protocol, and report false rejection, help rate, false pass and gated accuracy on
the 500 benchmark for each, as one table. Do not pick a winner by whichever row looks best.
Report all three and let the safety argument decide.

**The decision this surfaces is not a metrics decision.** A 0.15 false pass bound means the
robot drives to a wrong room without asking in about one command in seven. That may be fine for
an indoor waypoint task where the failure is recoverable and a human is present, and it is what
the closest published system accepts, but it is the project owner's call and must be stated as
such in the report rather than absorbed into a threshold. If the answer is no, the <= 5% bound
stays and the high false rejection is its documented, accepted cost: that is a legitimate
outcome of this item, not a failure of it.

### O3. Conversational filler for the latency gate (Shiwa et al.)

**Read what this does and does not do before starting.** It does **not** reduce resolver
latency. The 3737 ms cold p90 stays 3737 ms, and the internal 3000 ms gate stays missed. What it
does is address the thing that gate was a proxy for, with the remedy the cited paper itself
tested, and it adds a literature-anchored metric that this system can actually be held to.

**Why.** Shiwa et al. (HRI 2008; IJSR 2009) measured *system response time*, the delay before the
robot responds at all, and found user impressions unchanged up to 1000 ms with a recommendation
to react within 2000 ms. They then tested exactly this case, a robot that cannot answer that
fast, and found a conversational filler (a short utterance signalling that a reply is coming)
moderated the user's impression of a long delay. Our resolver cannot answer in 2000 ms, so the
paper's own mitigation is the applicable result, not its headline number.

**What.** On receiving a command, `semantic_goal_node` publishes a short acknowledgement to the
existing `/tts_text` channel immediately, before the resolver is called, then publishes the
resolution or the clarification request when it arrives. No new interface: `/tts_text` is
already in section 12 and already carries the clarification text, so this is a publish ordering
change plus a string, not new plumbing. Keep it a node parameter, default on, so the latency
measurement can be run with it off.

**Then measure and report both numbers, never one.**

| metric | what it is | anchor |
|--------|-----------|--------|
| time to first utterance | command received to first `/tts_text` publish | Shiwa 1000 ms unchanged, 2000 ms react |
| resolver p90 | command received to resolution, as Phase 5A measured it | internal 3000 ms, still missed |

Reporting the first number alone would be the dishonest version of this item and is explicitly
not what it is for. The report must state that the resolution still takes about 3.7 s and that
the filler changes perceived responsiveness, which is what the paper measured, not throughput.

**Cost.** Two to three hours including the launch test, most of it the test.

**Not this item.** Genuinely reducing the 3737 ms is a different lever: fewer output tokens, a
smaller model, or speculative decoding. Phase 8's model ablation already touches the second of
those and should be read for it. Do not conflate the two in the report.

## 17. Session checklist

1. `git checkout main && git pull`, read the previous phase report in `docs/reports/`. If the
   phase is 5 or later, also read `docs/archive/superseded-decisions.md` once.
   **Exception for Phase 5A**: it is a continuation of the Phase 5 session and assumes that
   session's context. Skip the report re-read, keep the branch and issue steps (8A.5).
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
