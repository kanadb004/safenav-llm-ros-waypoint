# Phase 6: BT plugin, semantic goal node, end to end in simulation

> **Amended 2026-10-14 (D57/D58, Phase 8B).** Section 3.3's example, `say.py "the room to the
> left of the kitchen"` resolving to `kitchen`, is not a correct resolution: "the room to the
> left of the kitchen" is `reception` (edge `kitchen right_of reception` in
> `room_annotations.json`), not `kitchen`. The model parsed the command's anchor as
> `meeting_room_a` rather than `kitchen`, and the hop from that (wrong) anchor landed on
> `kitchen`, which happens to be a real room, masking the error. What the example actually
> demonstrates, and still correctly demonstrates, is the relational hop executing end to end
> through the full stack (`anchor_room`, `relation`, `n_relation_targets`, `grammar_version`
> all populated and the BT completing); it does not demonstrate a correct resolution. See
> `docs/reports/phase-8b-corrective.md` and PLAN.md section 11A. Body below is unchanged.

## 1. What this phase built

- `include/semantic_waypoint_planner/bt_semantic_plugin.hpp`, `src/bt_semantic_plugin.cpp`:
  `semantic_waypoint_planner::SemanticNavigateToPose : public BT::ActionNodeBase`. Calls
  `/list_rooms` (200 ms budget) then `/resolve_waypoint` on a private, not-spun-by-default
  callback group, blocking on `callback_group_executor_.spin_until_future_complete(...,
  timeout_ms)`. `tick()` never returns `RUNNING`, as planned. At or above
  `confidence_threshold` with `success`: sets `resolved_pose`, `resolved_room`,
  `calibrated_confidence`, publishes a side-channel `/semantic_resolution_result` message
  (see section 3), returns `SUCCESS`. Otherwise publishes `/clarification_request`
  (`reason`: `low_confidence` | `unresolved` | `timeout` | `empty_command`) and returns
  `FAILURE`. `halt()` cancels the pending request via `remove_pending_request`; `tick()`
  catches the resulting broken-promise exception from a racing `halt()` and treats it as a
  timeout.
- `include/semantic_waypoint_planner/bt_speak_text.hpp`, `src/bt_speak_text.cpp`: `SpeakText :
  public BT::SyncActionNode`, publishes its `text` input port on `/tts_text`. The `espeak-ng`
  subprocess and `/cmd_lightring` pattern named in the plan as optional were not built; this
  phase did not run ahead of schedule enough to reach them (recorded below).
- Both node types are registered in one shared library, `semantic_waypoint_planner_bt_node`
  (`BT_REGISTER_NODES`, `BT_PLUGIN_EXPORT`), loaded by `bt_navigator` through
  `plugin_lib_names` the same way every stock Nav2 BT node is loaded: BehaviorTree.CPP v3's own
  `dlopen`, not pluginlib. `plugin_description.xml` is documentation only (noted in the file);
  nothing in the build reads it.
- `behavior_trees/semantic_navigate_to_pose.xml`: a template, not run directly. Top level
  `Fallback` of `Sequence(SemanticNavigateToPose, <stock navigate-with-replanning-and-recovery
  subtree reading {resolved_pose} instead of {goal}>)` and `SpeakText` with a static generic
  clarification line. `command`, `confidence_threshold`, `timeout_ms` are `__COMMAND__`,
  `__CONFIDENCE_THRESHOLD__`, `__TIMEOUT_MS__` tokens, substituted per goal.
- `include/semantic_waypoint_planner/semantic_goal_node.hpp`, `src/semantic_goal_node.cpp`,
  `src/semantic_goal_node_main.cpp`: `rclcpp_lifecycle::LifecycleNode`. Subscribes
  `/semantic_goal`, XML-escapes the command and renders it into the template (D6: this is how
  the command string reaches the BT, since `NavigateToPose` carries no string field), writes
  the result to `<runs_dir>/<now_ns>.xml`, sends `NavigateToPose` with `behavior_tree` set to
  that path. Subscribes `/clarification_request` and republishes a room-listing human readable
  string on `/tts_text`. Subscribes the new `/semantic_resolution_result` side channel (section
  3) and publishes `/semantic_goal_result` (JSON: `command`, `resolved_room`, `raw_confidence`,
  `calibrated_confidence`, `nav_result`, `e2e_ms`) once the action completes.
- `safenav_sim/config/nav2_params.yaml`: appended `semantic_waypoint_planner_bt_node` to
  `bt_navigator.plugin_lib_names`.
- `config/planner_params.yaml`: new `semantic_goal_node.default_timeout_ms` (300000, matching
  the sim profile's existing resolver timeout for the same D18 reason).
- `launch/semantic_nav.launch.py`: loopback sim, map server, Nav2 (`navigation_launch.py`),
  annotation map node, Python resolver, `semantic_goal_node`, and a `lifecycle_manager` with
  `bond_timeout: 0.0` (see section 5, deviation).
- `scripts/say.py`: publishes `SemanticGoal` on `/semantic_goal`, waits for the matching
  `/semantic_goal_result` by command text, prints it as JSON.
- `test/test_semantic_nav_launch.py`, `test/fixtures/stub_resolver.py`,
  `test/bt/test_minimal_template.xml`: the Phase 6 launch test (section 4).

## 2. Design decisions and deviations from the plan's prose

- **D46: `/semantic_resolution_result` side channel (new, not a section 12 interface).**
  `NavigateToPose`'s result is `std_msgs/Empty`, so `semantic_goal_node` has no path back to
  the resolved room or confidence through the action itself. `SemanticNavigateToPose` publishes
  a small JSON `std_msgs/String` on success (`command`, `resolved_room`, `raw_confidence`,
  `calibrated_confidence`); `semantic_goal_node` caches it keyed by command text and merges it
  into `/semantic_goal_result` when the action's result callback fires. This is explicitly not
  safe for two concurrent goals sharing the same command text; out of scope for this phase
  (single operator, one goal at a time). Recorded here rather than silently added because it
  is a new topic outside section 12, per CLAUDE.md's deviation rule.
- **SpeakText's clarification text is static, not the room list ("choose one and document" in
  the plan's section 9 prose).** The room-listing text that the Phase 6 DoD actually checks for
  comes from `semantic_goal_node` republishing `/clarification_request` (which carries
  `known_rooms`), not from the BT's `SpeakText` branch, because only the long-lived goal node
  conveniently holds the full room list; a BT port literal would need a dedicated
  `ListRoomsToText` helper node this phase did not build. Both messages land on `/tts_text`;
  manual verification (section 5) shows the goal node's room-listing message always arrives
  alongside the BT's generic one.
- **`bond_timeout: 0.0` on the `semantic_nav` lifecycle manager.** `semantic_goal_node` extends
  `rclcpp_lifecycle::LifecycleNode` directly, not `nav2_util::LifecycleNode`, so it does not
  implement the bond protocol. Nav2's own nodes (`map_server`, `bt_navigator`) do; disabling the
  bond watchdog for the whole manager rather than mixing bonded and unbonded nodes under one
  `bond_timeout` is the documented trade-off. Discovered the hard way: the first launch attempt
  failed lifecycle bring-up after 4 s with "Server semantic_goal_node was unable to be reached
  ... by bond."
- **`espeak-ng` and `/cmd_lightring` not built.** Named optional in the plan ("wire the topic
  first and only add them if the phase is running ahead"); this phase was not ahead. `/tts_text`
  alone satisfies every Phase 6 DoD item.
- Everything else matches the plan's section 9 prose as written (ports, blocking tick,
  `halt()`, the per-goal rendered BT XML, the goal node's responsibilities).

## 3. Verification

### 3.1 Build

`colcon build --symlink-install` for `semantic_waypoint_planner` and `safenav_sim` succeeds
clean, no warnings, inside `safenav-llm:humble`.

### 3.2 Launch test (`colcon test`)

All 5 tests pass (`test_annotation_graph`, `test_test_annotation_map_node_launch.py`,
`test_python_core`, `test_test_resolver_only_launch.py`, `test_test_semantic_nav_launch.py`).

The new `test_semantic_nav_launch.py` stands up a real `bt_navigator` (loading
`semantic_waypoint_planner_bt_node` through `plugin_lib_names`, exactly as production does) and
a deterministic `stub_resolver.py` fixture in place of the real GGUF-backed resolver and the
full planner/controller/costmap stack, which are not practical to bring up in a unit-level
launch test (model load alone is tens of seconds). The BT template used in the test swaps the
stock navigate subtree for `AlwaysSuccess` (a BT.CPP built-in) so no map server, costmaps,
planner or controller are needed; `SemanticNavigateToPose`, `SpeakText`, and `semantic_goal_node`
are exercised for real. Covers the three DoD paths:

1. success: `calibrated_confidence` 0.95 >= 0.72, `resolved_room` = `"kitchen"`.
2. low confidence / unresolved: `resolved_room` empty, `/clarification_request` fires,
   `/tts_text` lists `"kitchen"`.
3. timeout: `default_timeout_ms` set to 300 via `/semantic_goal_node/set_parameters`, stub
   resolver sleeps 2 s; result arrives within the 5 s test budget with `resolved_room` empty.

`nav_result` is `"succeeded"` in all three cases: the top level `Fallback`'s `SpeakText` branch
catches `SemanticNavigateToPose`'s `FAILURE` and completes the tree, which is correct BT
semantics (a spoken clarification is a completed goal) and not a bug; `resolved_room` emptiness,
not `nav_result`, is what the test and `say.py`'s own output distinguish on.

One flakiness source found and fixed during this phase: the test originally created a fresh
rclpy client node per test method. `/semantic_goal_result` is reliable/volatile, not transient
local, and destroying and recreating a same-named node between tests left the publisher's
matched-subscriber count referring to the just-torn-down reader long enough that the next
test's single message was lost outright rather than merely delayed, regardless of wait timeout.
Fixed by using one persistent client node for the whole test class.

### 3.3 Manual DoD checks (loopback stack, `semantic_nav.launch.py`, real GGUF model)

- `ros2 param get /bt_navigator plugin_lib_names` includes `semantic_waypoint_planner_bt_node`;
  no plugin load error in the log.
- `say.py "go to the kitchen"`: `/semantic_goal_result` shows `nav_result: succeeded`,
  `resolved_room: kitchen`, `calibrated_confidence: 0.99`. Final `/odom` position (6.04, 5.77)
  against the kitchen pose (6.0, 6.0): distance ~= 0.24 m < 0.5 m.
- `say.py "the room to the left of the kitchen"`: resolves through the Phase 5 hop
  (`semantic_cli` reasoning: `anchor_room: meeting_room_a`, `relation: left_of`,
  `n_relation_targets: 1`, `grammar_version: v2`) to `kitchen` (the graph's `kitchen left_of
  meeting_room_a` edge), `nav_result: succeeded`. Confirms the hop is exercised end to end
  through the full stack, not just the resolver in isolation.
- Unresolved command ("take me to the zebra enclosure", chosen after `"go to the cafeteria"`
  turned out to resolve validly to `kitchen` via its `"canteen area"` alias in this annotation
  graph): `resolved_room` empty, `/clarification_request` fires, `/tts_text` carries both the
  BT's generic line and the goal node's room-listing line ("... I know: reception, kitchen,
  meeting_room_a, ..."), `/cmd_vel` published nothing for the duration of the check.
- Timeout path: `default_timeout_ms` lowered to 5000 via `ros2 param set`, resolver process
  killed, `say.py "go to the lab"` returned with `e2e_ms: 5075.8` (within `timeout_ms + 500 ms`),
  `/tts_text` reason line reads "I timed out trying to understand that command. ...", `/cmd_vel`
  published nothing.
- `grep -c bt_loop_duration` on the launch log: 0 (the Nav2 BT engine logs loop overruns as
  `"Behavior Tree tick rate ... was exceeded!"`, not the literal parameter name). 10 such
  warnings appear across the whole session, all co-located with the five blocking
  `SemanticNavigateToPose` resolution ticks above (roughly two per call, consistent with a
  multi-second blocking tick spanning more than one 10 ms loop boundary); none appear during
  idle navigation or path following. This matches the plan's "no warnings beyond the resolution
  tick."

## 4. Deviations recorded in `docs/PLAN.md`

- D46: `/semantic_resolution_result` internal side channel, not a section 12 interface (section
  2 above).
- D47: `espeak-ng` and `/cmd_lightring` not built; `/tts_text` alone satisfies the DoD.
- D48: lifecycle manager for `semantic_goal_node` runs with `bond_timeout: 0.0` because the
  node does not implement the bond protocol.

## 5. Open risks for Phase 7

- The `/semantic_resolution_result` correlation-by-command-text assumption holds for Phase 7's
  `run_trials.py` replay (one command at a time) but would need a goal ID or UUID key if a
  later phase ever sends concurrent goals.
- `semantic_goal_node`'s `default_timeout_ms` (300000 ms, matching D18's sim profile) means a
  stalled resolver blocks a trial for five minutes before falling back to clarification;
  Phase 7/8's batch runners should watch for this if the `http` backend misbehaves.
- No hardware-profile timeout value exists yet; Phase 9 should set one alongside the rest of
  the hardware parameter profile.
