# Superseded decisions: plan v1 to plan v2

Date: 2026-10-13. Written at the start of the v2 replan, after Phase 4 merged (`5dd62da`)
and before any Phase 5 code existed.

Plan v1 is archived verbatim at `docs/archive/PLAN-v1.md`. The live plan is `docs/PLAN.md`.
This document records what was decided differently and why, so a future session can tell a
deliberate reversal from an oversight.

Nothing in Phases 0 to 4 is affected. Their reports in `docs/reports/` reference v1 section
numbers and remain accurate as written.

---

## S1. Phase 5 is no longer the C++ in-process resolver

**v1 Phase 5**: rewrite `llm_resolver_node` in C++ against the llama.cpp C API
(`llama_model_load_from_file`, `llama_state_seq_get_data` KV save and restore,
`llama_sampler_init_grammar`, multi-sequence batched candidate scoring, in-house thread pool),
with a 95 percent parity harness against the Python prototype. Gate: "C++ resolver is the
default implementation."

**v2 Phase 5**: relational decomposition in the existing Python resolver, plus a `backend`
parameter that lets the resolver talk to a `llama-server` process over HTTP.

**Why.**

1. *Accuracy was the binding constraint, not the implementation language.* Phase 4 closed at
   top-1 0.662 against a plan gate of 0.80 and a system target of 0.85 (D26). A C++ port
   changes latency and process architecture; it does not move accuracy by a single point. The
   project had roughly one week of implementation budget left and was going to spend the
   largest single block of it on the one thing that could not improve the headline result.
2. *The resolver sits behind a frozen service either way.* The BT plugin calls
   `/resolve_waypoint` (section 12.2). It cannot observe whether the node behind that service
   is `rclcpp` or `rclpy`. The "native Nav2 BehaviorTree plugin" architectural claim lives in
   Phase 6's `bt_semantic_plugin.cpp`, which is still C++ and still loaded by `bt_navigator`
   through `plugin_lib_names`. Dropping the C++ resolver does not weaken that claim.
3. *v1's own Phase 3 had already found the hard part intractable.* D12 records that batched
   multi-sequence candidate scoring needed `logits_all=True` in llama-cpp-python, which took a
   single resolution from seconds to minutes on the 900 token production prompt. v1 Phase 5
   proposed doing the same thing one abstraction layer lower, in C, with a documented fallback.
   The realistic outcome was spending a day to arrive at the fallback.
4. *`llama-server` is a better hardware path than an in-process C API binding.* See S2.

**What is lost.** The in-process C API path, and with it the v1 section 13 claim that it is
"the reference implementation and the only one used for the reported architecture." Latency
attributable to IPC is now part of the measured number. On localhost this is about 1 ms
against a 2000 to 3000 ms resolution, so it does not threaten any gate, but it must be
reported rather than hidden.

Recorded in v2 as **D27**.

---

## S2. `llama-server` over HTTP replaces in-process inference as the deployment shape

**v1**: in-process llama.cpp inside the ROS node was the default and the only reported
architecture. A host-side `llama-server` was listed in section 13 as an optional Phase 5
stretch, explicitly subordinate ("the in process llama.cpp C API path stays the reference
implementation").

**v2**: `backend` is a first-class resolver parameter. `inprocess` (llama-cpp-python) stays
the default for host development and unit tests. `http` (llama-server, same GGUF, same GBNF
string sent as the `grammar` field) is the backend used for all batch runs and for hardware.

**Why.**

1. *Jetson build risk.* The v1 hardware plan assumed a CUDA build of the resolver's inference
   path on the Orin NX. For llama-cpp-python on aarch64 plus JetPack this means compiling the
   Python binding from source against the system CUDA, with no prebuilt wheel. That is a known
   fragile build. `llama.cpp`'s own server target with `-DGGML_CUDA=ON` is the single
   best-supported CUDA path in the project and produces a standalone binary with no Python or
   ROS coupling at all. Moving the deployment seam to HTTP moves the hardware risk off the
   critical path.
2. *Batch throughput inside the 4 to 5 day budget.* Phases 7 and 8 together are about 600
   resolutions. At the container's CPU-only rate (about 26 s each, D16 and D18) that is 8 to
   12 hours of unattended compute. Pointed at a Metal `llama-server` on the macOS host it is
   under an hour. This is the single change that makes the remaining schedule fit.
3. *Simulation and hardware become the same shape.* Container ROS node to host llama-server
   over HTTP in simulation; Jetson ROS node to localhost llama-server over HTTP on hardware.
   One code path, one config difference (the URL). v1 had simulation and hardware differing in
   how inference was reached, which is exactly where deployment surprises come from.

Recorded in v2 as **D28**.

---

## S3. The GBNF grammar gains a `relation` field

**v1 section 12.6**: the grammar emits `{"room": <canonical>, "confidence": <float>}`. The
model is expected to perform spatial reasoning internally, using an "adjacency sentences"
block rendered into the prompt from `edges`.

**v2 section 12.6**: the grammar emits
`{"room": <canonical>, "relation": <relation>, "confidence": <float>}`. When `relation` is
`none` the behaviour is identical to v1. When it is anything else, `room` is read as the
*anchor* and the answer is computed by traversing `edges` in code.

**Why.** Phase 4 section 4.2 found, by inspecting wrong predictions, that the model "was not
reliably using the spatial relationships block of the prompt to find the referenced landmark's
neighbor" and instead answered a fixed room regardless of the referent. Two prompt iterations
were tried: v2 of the template added an explicit traversal rule and made things *worse*
(0.217 to 0.194 on the hard subset); v3 removed it again and recovered slightly. The Phase 4
report concluded this was a capability ceiling of Phi-3-mini-4k Q4_K_M.

That conclusion is accepted. The v2 response is not to prompt harder but to stop asking the
model to traverse at all. Traversal is a deterministic lookup over a graph the system already
owns. The model is left with anchor extraction, which is a `direct`/`alias`-class task where
it already scores 0.92 to 0.95.

This is an internal change. Section 12.2 `ResolveWaypoint.srv` is untouched: the service still
returns a single `matched_room_name`. Nothing downstream of the resolver observes it.

Recorded in v2 as **D29**.

---

## S4. Gazebo DoD items are formally dropped, not merely unmet

**v1** carried live Gazebo DoD items in Phase 6 ("the same for three rooms, video or
screenshot") and Phase 8 ("30 Gazebo runs completed and recorded, mandatory"), even after D11
recorded that robot spawn segfaults the Ignition server in the container's software renderer.

**v2** removes those items from the DoD lists and states loopback as the only simulation mode,
with the Gazebo gap named as a known limitation in `RESULTS.md`.

**Why.** D11 established that this is a renderer crash (Ogre2 on llvmpipe) during lidar and
depth camera sensor creation, not a configuration error, and v1's own Phase 2 contingency said
not to spend more than one session on it. Leaving the items in the DoD meant every later phase
would open with an item that cannot be ticked and must be re-explained. Honest removal with a
documented limitation is better than a permanently failing checklist.

The work is not abandoned: v1 Phase 2's findings, including the `turtlebot4_ignition_bringup`
packaging bug found and fixed along the way, stay in `docs/reports/phase-2-sim-world-nav2-bringup.md`,
and GPU passthrough is listed in v2 Phase 10 as the way back in.

Recorded in v2 as **D30**.

---

## S5. Phase renumbering

v1 Phase 9 (model ablation plus final report) is merged into v2 Phase 8, because with the HTTP
backend the ablation is about an hour of compute rather than a phase's worth, and because
splitting "run the ablation" from "write up all results" across two phases generated an extra
full session of git and report overhead for no analytical benefit.

The freed number is reused: v2 Phase 9 is **hardware readiness**, a documentation and
configuration phase that produces the Jetson build recipe, the hardware parameter profile, and
a bring-up checklist in which every seam is listed with the simulation evidence that it works.
v2 Phase 10 remains actual hardware bring-up, to be run when the robot is present.

| v1 | v2 |
|----|----|
| 5 C++ resolver | 5 Relational decomposition and resolver backend |
| 6 BT plugin and E2E | 6 BT plugin and E2E (Gazebo items removed) |
| 7 Calibration | 7 Calibration (gated accuracy becomes a headline number) |
| 8 E2E validation and ablation | 8 E2E validation, grammar ablation, model ablation, final results |
| 9 Model ablation and final report | *(merged into 8)* |
| -- | 9 Hardware readiness (new, no robot required) |
| 10 Hardware deployment | 10 Hardware bring-up |

Recorded in v2 as **D31**.

---

## S6. Accuracy targets are now stated at two levels

**v1 section 1** gave a single top-1 target of 0.85 with a Phase 4 baseline gate of 0.80, and
treated the benchmark number and the system number as the same quantity.

**v2** separates them:

| Level | What it measures | Target |
|-------|------------------|--------|
| Resolver raw top-1 | the resolver alone, gate disabled, on the 500 benchmark | >= 0.80 (Phase 5) |
| Gated end-to-end accuracy | resolver plus calibrated confidence gate, counting a correct abstention on an adversarial row as correct | >= 0.85 (Phase 7) |

**Why.** 45 of the 500 benchmark rows are adversarial with `expected: "none"`, and the resolver
scores 0.400 on them with a false accept rate of 0.600 and a false abstain rate of 0.002: the
model essentially never abstains on its own. Abstention is the calibrator's job by design, not
the resolver's. Reporting one blended number made the resolver look worse than it is and hid
the fact that the designed remedy had not been applied yet. Two levels is both more honest and
more informative, and it matches how the specification's own metrics table is structured.

This is a reporting and target change, not a relaxation: both numbers are gates, and the
harder one (0.85) is still required of the finished system.
