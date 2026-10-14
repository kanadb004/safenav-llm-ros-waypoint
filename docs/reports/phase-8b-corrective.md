# Phase 8B: corrective pass

> **Amended 2026-10-14 (Phase 8C, `docs/reports/phase-8c-spatial-anchor-fix.md`, D64).** A
> review of this pass found findings 1, 3, 4, 5, 7 and 8 below (PLAN.md 11B.0) rest on an
> uncorrected cause or an uncorrected citation: finding 1 (section 1.6's calibrator diagnostic
> and its "evidence for 16A O1" reading) is a resolver double hop, not a calibrator separability
> problem; finding 3 (`offline_gate_comparison.py`'s gate-off wrong-room figures) undercounted
> `none` answers as acted-on; finding 4 (`t_nav_start`) cites the wrong file; finding 5 cites D58
> where the result is D62; finding 7's isolated latency gap and finding 8's Phi-3.5 McNemar/
> `multi_hop` concentration were measured but not fully written up here. Body text below is
> unchanged; see Phase 8C's report and `docs/results/RESULTS.md`/`docs/PLAN.md` section 1 for
> the corrected numbers.

This phase rescores what could be rescored without inference, reruns what could not on a clean
and isolated setup, and corrects the documents named in PLAN.md section 11A. It changes no
resolver, grammar, prompt, cue list, calibrator or threshold.

## 1. What this phase found and fixed

### 1.1 e2e150 spatial relabel (11A.1)

`scripts/run_trials.py`'s `SPATIAL_ANCHORS` import-time check called
`AnnotationGraph.related_rooms(anchor, relation)` directly, which is the wrong direction for
"the room to the right/left of X" queries (an edge `A right_of B` means A is right of B, not
that something right of B is A). The resolver's own `relations.resolve_relation()` already
queries the correct, inverted direction; it was just never used to check the suite's hardcoded
labels. The frozen rule (`CORRECTED_SPATIAL_LABELS`) now derives each spatial command's
intended room from `resolve_relation()`, with an independent hand-read test against the raw
graph edges (not calling either function) as a second check. Six of ten room keys change
label; the four `near` phrasings are symmetric and unaffected.

Commands are byte-identical to Phase 8 (verified: `build_commands()` still returns the same 50
rows); only the intended room used for scoring changed. Rescoring the committed production
file (`e2e150_loopback.jsonl`) against the corrected rule, with no inference re-run, reproduces
the review's numbers exactly:

| | corrected labels | original labels |
|---|---|---|
| spatial rows correct (of 30) | 2 | 1 |
| gate-passed wrong-room actions (of 140) | 26 (25 spatial, 1 negation) | — |

### 1.2 Metric definitions (11A.2)

`e2e_report.py` conflated navigation failure with a wrong resolution under one "false start"
number. It now reports, each with its own numerator and denominator: acted rate, wrong-room
action rate (of n and of acted), correct abstention rate, resolver correct rate, reach given a
correct resolution (navigation-invalid rows excluded, reported as a simulator health figure),
navigation-invalid count, and out-of-graph rate, plus a per-category wrong-room action
breakdown.

### 1.3 Harness fixes (11A.3)

- **Off-map guard.** `_map_bounds()` reads the map YAML's origin/resolution and the referenced
  PGM's width/height (not hardcoded); a row is `nav_invalid` if its final pose is outside those
  bounds or null, and the suite stops after three consecutive invalid rows, printing a
  `--start-row` to resume from. Neither 8B rerun tripped it (0 invalid rows in either 150-row
  suite).
- **`t_nav_start` null investigation.** 90 of 91 null rows in the Phase 8 production file have
  a pose identical to the previous row: the robot was already at the target and never needed
  to move, which is a legitimate null case, not a capture bug. `TrialRunner._drain()` still
  improves capture during an actual move (`rclpy.spin_once` services at most one of five
  competing subscriptions per call, which can still starve `/cmd_vel` against busy `/odom`
  traffic), but it is not the dominant cause Phase 8's 79/150 null count suggested.
  `e2e_report.py` reports n and the null count beside every latency percentile.
- **One fresh stack per suite**, verified by checking "Managed nodes are active" appears twice
  in the launch log (once per lifecycle manager) before starting a suite, after one launch
  attempt during this pass left a lifecycle manager stuck (see 1.6 below).

### 1.4 Clean reruns (11A.4)

Gate-off (threshold 0.0, grammar on) and grammar-off (grammar off, gate at 0.85) each reran at
the full 150, sequentially, on a fresh stack and a fresh, isolated host `llama-server`
(production model, Metal), nothing else on the GPU for the duration. Both suites finished
clean: 0 navigation-invalid rows, 0 out-of-graph, no off-map guard trips.

**Condition B versus C, corrected:** the gate makes no measurable difference on this command
set. Wrong-room action rate is 0.173 (gate on, rescored production) versus 0.187 (gate off,
8B rerun); 148 of 150 rows resolve to the same room whether the grammar is on or off. Full
per-category table: `docs/results/e2e150_report.md`.

This supersedes Phase 8's withdrawn 0.772 vs. 0.080 reached-intended headline, which measured
a diverging loopback simulator (45 of 50 gate-off rows ended off the map while `nav_result`
read `succeeded`), not a gate effect.

### 1.5 Offline Condition B versus C, where the gate has something to catch (11A.5)

No inference: `phase5a_full500.jsonl` (features reconstructed through the deployed calibrator,
the same way `train_calibrator.py`'s `gated_benchmark_500` does) and
`calibration_session2_trials.jsonl` (recalibrated the same way; it was collected with
`calibrator_loaded=False`, so its stored `calibrated_confidence` column is raw confidence
passed through the identity fallback, not the deployed calibrator's output), re-gated at 0.85
versus 0.0.

| set | gate on, wrong-room action rate | gate off, wrong-room action rate |
|---|---|---|
| Corrected 500 benchmark | 0.056 (28/500) | 0.268 (134/500) |
| Session 2 calibration trials | 0.020 (2/100) | 0.290 (29/100) |

Session 2's false pass rate (2 of 47 acted commands, 0.043) reproduces Phase 7's reported
0.0426 almost exactly, confirming the reconstruction is correct. Both sets show the gate
reducing wrong-room actions by roughly a factor of five; e2e150 does not, because its wrong
spatial passes already clear the 0.85 threshold (finding below). Full tables:
`docs/results/offline_gate_comparison.md`.

### 1.6 Calibrator diagnostic (11A.6)

For e2e150 production, wrong passes (n=26) have lower mean `raw_confidence` (0.904 vs. 0.955),
higher mean `token_entropy` (0.313 vs. 0.182) and `edit_distance` (3.0 vs. 0.8) than correct
passes (n=114), but every feature's range overlaps substantially (`raw_confidence` wrong max
0.95 equals correct min 0.90). The wrong spatial passes are not cleanly separable on any single
feature without retraining, which was not done. This is evidence against relaxing the 16A O2
false-pass bound to 0.15: on this command set the problem is not an over-strict threshold, it
is that wrong answers already carry threshold-clearing confidence. Full table:
`docs/results/calibrator_diagnostic_e2e150.txt`.

### 1.7 Model ablation (11A.7)

No inference re-run for accuracy: a corrected-label top-1 column, computed from the cached
`data/runs/model_ablation/*.jsonl` joined against `synthetic_500_v2.jsonl`.

| model | top-1 (original) | top-1 (corrected) | top-3 |
|---|---|---|---|
| phi3-mini-4k-instruct (production) | 0.650 | 0.726 | 0.763 |
| tinyllama-1.1b-chat-v1.0 | 0.402 | 0.530 | 0.686 |
| phi3.5-mini-instruct | 0.654 | 0.764 | 0.763 |

Top-3 denominator: 455 (resolvable rows under the original labels the `top_k_rooms` ranking
was computed against, 45 adversarial excluded; this was previously unstated). Under corrected
labels, phi3.5-mini leads by 3.8 points, which clears D36's 2-point promotion bar. **This is
reported as a finding, not acted on**: this pass measures only, and a model swap is a separate
decision a future phase should make after also re-running session 2 calibration on the
candidate.

Latency was remeasured in isolation for all three models (held-out 100 slice, one fresh
`llama-server` per model, nothing else on the GPU, `cold_latency_remeasure.py`'s protocol,
first-call outlier reported not dropped):

| model | v1 p50/p90/p99 ms | v2 p50/p90/p99 ms | traffic-weighted p90 | gate (< 3000 ms) |
|---|---|---|---|---|
| phi3-mini-4k-instruct | 3579/4087/10287 | 4857/5399/5698 | 4494 ms | FAIL |
| tinyllama-1.1b-chat-v1.0 | 1054/1137/2695 | 1387/1507/1530 | 1252 ms | PASS |
| phi3.5-mini-instruct | 3777/4367/12742 | 4720/5385/5984 | 4683 ms | FAIL |

Production's isolated figure (4494 ms) is a second, GPU-isolated confirmation of 5A's own cold
measurement (3737 ms); both miss the gate, and the 757 ms gap is session variance (thermal
state, background load), not a methodology difference.

### 1.8 Tests (11A.8)

`colcon test` with no launch stack up and an isolated `ROS_DOMAIN_ID` passes 5 of 5, confirming
Phase 8's `test_test_annotation_map_node_launch.py` failure was environmental: a stray
`annotation_map_node` process from an earlier test run was still answering `/list_rooms` on the
shared default domain. Killing it and isolating the domain fixed it.

One new, unrelated flake surfaced during verification and was not fixed (out of scope):
`test_test_resolver_only_launch.py` failed once (an in-process CPU-backend call for "somewhere
I can charge the robot" returned an empty `matched_room_name`) and passed on an immediate
retry with no code change in between. Consistent with D16/D18's documented CPU-backend latency
variance under `temperature=0.3` sampling, not a deterministic defect; recorded as D61.

### 1.9 A second flake found while rerunning (D61)

One of the two fresh-stack launches for the grammar-off rerun left
`lifecycle_manager_semantic_nav` stuck configuring `map_server`, which never activated. The
resolver and annotation nodes came up regardless (they are not lifecycle-managed the same way),
so the suite accepted commands while the robot drove with no map and went out of bounds
("Robot is out of bounds of the costmap!", "Can't update static costmap layer, no map
received", both persisting for the full 25 minutes the suite was stuck). Killing the stack and
relaunching fixed it on the next attempt, which this time showed "Managed nodes are active"
twice in the log and no out-of-bounds warnings before the suite started. The protocol note in
11A.3 above is this finding's fix.

### 1.10 Data freeze (11A.9)

`data/frozen/` now holds the three original Phase 8 e2e150 files, the two 8B reruns, the
rescored production file, the three model ablation files, `phase5a_full500.jsonl`, and the two
calibration trial files, each with sha256, row count, producing commit and command in
`data/frozen/MANIFEST.md` (2.5 MB total). Bags stay uncommitted; the one that exists
(production, 112 MB) is recorded by path, size and `metadata.yaml` hash. The two 8B reruns used
`--no-bag`, consistent with Phase 8's own D56 practice: the wrong-room action rate comparison
does not depend on the bag, and recording one per suite would have roughly doubled this
already multi-hour pass's unattended time.

### 1.11 Documents (11A.10)

- `docs/reports/phase-8-e2e-validation-results.md` and
  `docs/reports/phase-6-bt-plugin-e2e.md`: dated amendment banners naming each withdrawn claim;
  body text unchanged.
- `docs/results/RESULTS.md`: amendment banner, then sections 1, 3, 4, 5, 6 and 7 corrected in
  place, with every superseded figure kept visible and marked rather than deleted. Fixes the
  D41/D44 mis-citation, the Phase 4 top-3 omission, the 96-of-500/99-of-130 conflation, the
  missing model-ablation top-3 denominator and corrected-label column, and adds the 8B e2e150
  results, the offline gate comparison, the calibrator diagnostic, and the isolated latency
  table.
- PLAN.md section 1: the two "pending 8B" rows in Current metric status replaced with measured
  values; a top-3 provenance row added (D58: 0.97 in Review 2/v1, 0.88 in the v2 redraft, 0.85
  in the 5A plan, no deviation recorded for either change); stale wording corrected in place
  with "Corrected by D57" notes at D45's last sentence, section 13, and 16A O1's seam-contract
  citation (it is section 8.2 and D28, not D23); `docs/archive/superseded-decisions.md` S6 gets
  a correction note.
- `README.md`: results summary gets the 8B findings (spatial relabel, gate result, isolated
  latency confirmation).

## 2. What stands unchanged

0/150 out-of-graph with the grammar on; the model ablation's accuracy columns (phi3-mini's
0.650 original-label top-1 still cross-checks 5A's 0.646); the full-graph trial runner's
engineering; the D55 telemetry extension; the production suite's navigation data, which has no
off-map row either before or after this pass (row 138's null pose is the only invalid one, and
is excluded consistently by this pass's `nav_invalid` definition).

## 3. Verification

```
docker exec safenav-dev bash -lc "cd /ws/ros2_ws && colcon build --symlink-install --packages-select semantic_waypoint_planner"
# Finished <<< semantic_waypoint_planner, clean

docker exec -e ROS_DOMAIN_ID=79 safenav-dev bash -lc "cd /ws/ros2_ws && colcon test --packages-select semantic_waypoint_planner"
# 100% tests passed, 0 tests failed out of 5 (no stack up, isolated domain)

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest src/semantic_waypoint_planner/test/python/test_run_trials_suite.py -v
# 4 passed: the two new 11A.1 relabel tests (resolve_relation-derived and the independent
# hand-read edge table) alongside the two pre-existing suite-shape tests
```

Gate-off and grammar-off reruns: 150/150 rows each, 0 navigation-invalid, 0 out-of-graph, no
guard trips, verified against `wrote ... rows this invocation ...; guard_tripped=False` in each
run's log.

## 4. Deviations

D58 through D61, recorded in PLAN.md section 14: the undocumented top-3 target history (D58),
the relabel and capture-rate harness fixes (D59), the metric split (D60), and the two unrelated
flakes found during verification, neither fixed (D61).

## 5. Open risks for Phase 9

- `TrialRunner._drain()` reduces but does not eliminate the single-callback-per-`spin_once`
  starvation risk across five competing subscriptions; a future phase driving more goals per
  session should consider a multi-threaded executor instead.
- `test_test_resolver_only_launch.py`'s one-time empty-`matched_room_name` failure (D61) is
  unexplained beyond "consistent with known CPU-backend latency variance"; worth its own issue
  if it recurs.
- The corrected-label model ablation finding (phi3.5-mini 3.8 points ahead of production
  phi3-mini, 1.7) is a measurement this pass deliberately did not act on; a future phase
  deciding whether to promote it should re-run session 2 calibration on the candidate first.
- 16A O1 (real room-level token entropy) and O2 (false-pass bound literature check) remain the
  more promising levers for the gated-accuracy gap and the e2e150 spatial miss; this pass's
  11A.6 finding (wrong spatial passes not separable on any current feature) is evidence for O1
  specifically, and against relaxing O2's bound.
