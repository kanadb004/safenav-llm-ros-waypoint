# Phase 8D: ship the text anchor fix

A review of Phase 8C (#29) found that its decision rule (PLAN.md 11B.5) measured the wrong
quantity for a shipping decision: the corrected 500 benchmark's raw, uncapped top-1, when
production always runs behind the 0.85 gate. This phase verifies the gated evidence from
committed code, ships `text_anchor` on everywhere, corrects the three other review findings, and
amends the documents. No inference and no simulator run, per the 0.25-day timebox (PLAN.md
11C). The decision to ship on is disclosed as made after the results were seen, not as the
outcome of 11B.5's frozen rule, which it overrides.

## 1. Verifying the gated evidence from committed code (11C.1)

`ml/safenav_ml/replay_text_anchor.py` is extended, not reimplemented: every changed row of the
500 and both calibration sessions now gets `before_calibrated`/`after_calibrated` (reconstructed
through the deployed calibrator, the same feature path `offline_gate_comparison.py` uses), and
new `model_room`/`anchor_used` columns replace the ambiguous `anchor_room` output (11C.0 finding
4: the old column held the model's own input room, not the room the hop actually used). A new
`gated_changed_table` computes, for the rows the fix changes, how many act at 0.85 before and
after and the net wrong/correct actions added and removed. Output: `docs/results/
text_anchor_replay_v2.md`, row-level `data/frozen/text_anchor_replay_{500,session1,session2}_v2
.jsonl`.

| held-out set | rows changed | changed rows acting at 0.85, before | after | net effect on actions |
|---|---|---|---|---|
| corrected 500 | 15 | 1 | 0 | 1 wrong action removed |
| session 1 | 15 | 0 | 0 | none |
| session 2 | 10 | 0 | 0 | none |

This reproduces 11C.0 finding 1 exactly: across all 800 held-out rows, the fix changes the
gated system's behaviour on exactly one row (`p0143`, `meeting_room_a` wrong at 0.949 becomes an
abstention). It adds no wrong action and removes no correct one. Session 2 false pass at 0.85 is
0.043 before and after, at or below the 0.05 bound. **The stop rule clears** (the script's own
`stop_rule_clears` check, printed at the end of its run): no wrong action added, no correct
action removed, session 2 false pass within bound. Proceeding to ship the default per the plan.

## 2. One shipped default, everywhere (11C.2)

`text_anchor: true` in `planner_params.yaml`, matching the `ResolverCore` constructor default
and the node's `declare_parameter` default, which were already `True` (11C.0 finding 2: "off"
previously held only where `semantic_nav.launch.py` loads the YAML; `resolver_only.launch.py`,
its launch test, and every `ml/` script building a `ResolverCore` directly were already running
with the fix on). A new test, `test_text_anchor_default_agrees_in_yaml_core_and_node`
(`test_resolver_core_offline.py`), asserts all three agree: `inspect.signature` on
`ResolverCore.__init__` for the constructor default, an AST walk of `llm_resolver.py` for the
declared default (no rclpy import needed), and `yaml.safe_load` on `planner_params.yaml`.

`text_anchor` is recorded in every new run record: `scripts/run_trials.py` now queries the
resolver node's live parameter value (`ros2 param get /llm_resolver_node_py text_anchor`) and
adds it to each row; `ml/safenav_ml/run_trials.py` and `run_phase5_benchmark.py` add
`core.text_anchor` to theirs. Every run committed before this phase used the pre-fix or
diagnostic-forced behaviour; `MANIFEST.md` notes this per file rather than editing old rows.

## 3. The Condition B versus C figure (11C.3)

`ml/safenav_ml/e2e_report.py` gains `--regate <threshold>`: acted is recomputed as
`attempted_room` not `none` and `calibrated_confidence >= threshold`, rather than trusting the
run's own `gate_passed` field. Regenerating the 8C e2e150 production run's Condition B versus C
at 0.0 and 0.85:

| | acted | wrong-room action rate (of n) |
|---|---|---|
| gate on (0.85) | 140/150 | 0.000 |
| gate off (0.0) | 143/150 | 0.020 (3/150) |

8C reported 0.000 against 0.000 ("the gate has nothing left to catch"); the gate-off figure had
silently reused the gate-on acted count instead of re-gating at 0.0. The corrected figure is
**0.000 against 0.020**: the gate does catch something on this run, 3 `negation` rows resolving
to `meeting_room_b` at calibrated confidence 0.798 (below 0.85) instead of the intended
`meeting_room_a`. Corrected in `docs/results/e2e150_report_8c.md`, `docs/results/RESULTS.md`
(sections 1, 5.3, 6) and `docs/PLAN.md` section 1, with the superseded 0.000 vs. 0.000 kept
visible each place it appeared.

## 4. Documents (11C.4)

- `docs/PLAN.md` section 1: the two 8C e2e150 rows relabelled from "diagnostic only, default
  ships off" to "shipped configuration as of D65", with the corrected Condition B versus C
  figure; two new rows add the shipped resolver's corrected 500 raw (0.730) and gated (0.722)
  top-1 beside 5A's 0.732 and Phase 7's 0.72 (both `text_anchor` off), without overwriting
  either old row. D64 (section 14) and 11B.5 each get a "Superseded by D65" note; the D65
  deviation entry already existed (written when this phase's plan section was added) and its
  gated-evidence numbers are confirmed, not re-derived, by section 1 above. Section 12.6's 8C
  note gets a one-line amendment: the default is on as of D65.
- `docs/reports/phase-8c-spatial-anchor-fix.md`: a dated amendment banner naming 11C.0 findings
  1 to 4 and pointing to this report. Body untouched.
- `docs/results/RESULTS.md`: a new top-of-file amendment banner (Phase 8D, D65); section 5.3
  gets the corrected Condition B versus C figure and a new "D65" subsection with the gated
  changed-rows table and the shipping decision; the "ships off" and "no measurable difference"
  sentences elsewhere in sections 1 and 4 get superseded notes rather than rewrites.
- `README.md`: a new paragraph after the 8C summary records the 8D decision and the Condition B
  versus C correction.
- GitHub issue #31 opened for the D61 flake (no `phase` label), listing its three occurrences
  (8B, 8C, this phase, where it did not recur).

## 5. Tests (DoD)

```
docker exec safenav-dev bash -lc "cd /ws/ros2_ws && colcon build --symlink-install --packages-select semantic_waypoint_planner"
# Finished <<< semantic_waypoint_planner, clean

docker exec -e ROS_DOMAIN_ID=83 safenav-dev bash -lc "cd /ws/ros2_ws && colcon test --packages-select semantic_waypoint_planner"
# 167 tests, 0 errors, 0 failures, 0 skipped (no stack up, isolated domain; +1 test over 8C's
# 166 for the new default-agreement test)
```

No D61 flake this run (`test_test_resolver_only_launch.py` passed cleanly, no retry needed).

Host pytest (no rclpy needed): `test_relations.py` 37 passed (unchanged),
`test_resolver_core_offline.py` 28 passed (27 from 8C plus the new agreement test).

## 6. Data freeze

`data/frozen/` gains `text_anchor_replay_{500,session1,session2}_v2.jsonl` (sha256, row count,
producing commit and command recorded in `MANIFEST.md`); the 8C-era files of the same name
without `_v2` are marked superseded in place, not deleted. `e2e150_production_8c.jsonl`'s
`MANIFEST.md` entry gets a one-line note that it is now the shipped e2e150 measurement, since
`text_anchor` forced on for that run is the configuration now shipped; no rerun.

## 7. What stands unchanged

The prompt, few-shot file, grammar (GBNF form), cue list, calibrator and threshold, and every
label on every held-out set. The extraction rule itself (`relations.extract_text_anchor`,
`apply_relational_hop`) is untouched; this phase changes only which default is shipped and which
figures are reported, per 11C.5.

## 8. Deviations

D65 (PLAN.md section 14, already recorded when this phase's plan section was added): the
shipping reversal itself. This report adds no new deviation; it carries out D65's decision and
corrects the figure D65 itself flagged as wrong.

## 9. Open items for a future phase

- The `multi_hop` raw top-1 regression this fix carries (6 gained, 7 lost on the 500, uncapped)
  is unchanged and still open; a `multi_hop`-aware rule or 16A O1's calibrator retrain remain the
  better next steps, per 8C's own framing, not reopened here.
- The D61 launch-test flake (issue #31) needs its own investigation into whether it is genuine
  backend latency variance or a bug in how the launch test waits for `matched_room_name`.
- Whether phi3.5-mini's lead over phi3-mini comes from better anchor-contract adherence (D63
  finding 8) is still untested.
