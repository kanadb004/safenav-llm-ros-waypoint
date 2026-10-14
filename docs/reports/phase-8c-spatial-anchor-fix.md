# Phase 8C: spatial anchor fix

A review of Phase 8B (#27) found the e2e150 spatial failures are a resolver double hop, not a
calibrator problem (PLAN.md section 11B, D63). This phase fixes the post-decode step, measures
the fix on held-out data by exact replay with no new inference, confirms it once end to end, and
corrects the 8B claims the review found wrong. No change to the prompt, few-shot file, grammar,
cue list, calibrator, threshold, model or annotation graph.

## 1. The defect (11B.0)

For "the room to the left/right of X" and `adjacent`/`near` commands, Phi-3 mini often fills the
v2 grammar's `room` field with the command's **answer**, not the anchor X the prompt template
asks for. `_resolve_llm` then applied `resolve_relation` to that answer, landing the final room
two hops past the correct one. A local probe (reported in the 8B review, not re-run here)
reproduced the stored e2e150 outputs with the model correct on 18 of 18 calls before the second
hop. This also explains 8B's section 1.6 finding that the wrong spatial passes are not separable
on any calibrator feature: the feature vector never saw the broken intermediate step, only the
model's own (correct) first answer.

## 2. Telemetry first (11B.1)

`scripts/run_trials.py` now parses the resolver's `reasoning` field (already forwarded by
`/semantic_goal_result`, previously dropped by the harness) into `model_room`, `anchor_room`,
`anchor_source`, `relation`, `n_relation_targets` and `grammar_version` columns. `model_room` is
the raw `room` field the model emitted; `anchor_room` is whichever anchor the hop actually used;
`anchor_source` is `"text"` or `"model"`. A round-trip test (`test_run_trials_suite.py`)
exercises the exact payload shape `llm_resolver.py`'s `_encode_reasoning` emits. No message,
service or interface change; this is a harness gap only (PLAN.md 11B.0 finding 2).

## 3. The fix: anchor from the command text, one hop in code (11B.2)

`relations.extract_text_anchor` normalizes the command (lowercase, punctuation to spaces),
finds the end of the first relational cue phrase, and searches the remainder for canonical
names (underscores as spaces) and aliases of **edge bearing** rooms only, longest match first,
on word boundaries. `relations.apply_relational_hop` applies the rule: for
`left_of`/`right_of`/`adjacent`/`near`, if exactly one distinct room is found it is the anchor
(`anchor_source = "text"`); on zero or more than one match, the hop falls back to the model's
own `room` field (`anchor_source = "model"`, today's behaviour). `within` is unchanged (it
legitimately anchors on a sub location the model names). Both the resolver (`resolver_core.py`)
and the held-out replay (section 4) call this one function; it is never reimplemented.

A resolver parameter `text_anchor` (default `true` in code, overridable in
`planner_params.yaml` and the node) switches the rule off, so the pre-fix path stays
reproducible as a regression record.

Tests committed before any replay or run: an extraction truth table over all ten e2e150 spatial
phrasings plus the alias/word-boundary, ambiguous-match and sub-location cases
(`test_relations.py`), and a resolver-level test with a stub backend showing the same command
resolves differently with `text_anchor` on versus off, matching the pre-fix regression exactly
(`test_resolver_core_offline.py`).

## 4. Held-out replay (11B.3)

`ml/safenav_ml/replay_text_anchor.py` replays each cached row's stored `anchor_room`/`relation`
(the model's own output, unchanged) through the new post-decode step; since the prompt and
grammar do not change and the fix acts after decoding, this is the exact paired effect of the
fix with no new inference and no sampling noise (verified per-row: replaying with the fix
disabled reproduces every cached `resolved_room` exactly).

| set | before | after | change |
|---|---|---|---|
| Corrected 500, raw top-1 | 0.732 | 0.730 | -1 row net (6 gained, 7 lost, 2 wrong-to-wrong) |
| Corrected 500, gated top-1 (0.85) | 0.720 | 0.722 | +1 row net |
| Corrected 500, `spatial` top-1 | 0.615 | 0.677 | +4 rows |
| Corrected 500, `multi_hop` top-1 | 0.308 | 0.231 | -5 rows |
| Session 2, false pass (0.85) | 0.043 | 0.043 | unchanged |
| Session 2, false rejection (0.85) | 0.366 | 0.366 | unchanged |

Every one of the 7 lost rows on the 500 is `multi_hop`: a compound, two-clause sentence (e.g.
"Find the second bench in the lab, but first go to the room with the tool storage.") where the
"first cue, nearest edge bearing room" rule picks up a room name from the wrong clause, or an
ordinary generic alias (`storage_room`'s alias "storage") matching inside an unrelated phrase
two clauses from the actual anchor. This is a property of the frozen rule interacting with
`multi_hop`'s more complex phrasing, not an implementation bug; per PLAN.md 11B.7 it is reported
as measured, not tuned against. Full before/after tables and every changed row:
`docs/results/text_anchor_replay.md`.

### Decision (11B.5)

`text_anchor` ships default **on** only if both hold: session 2 false pass stays at or below
0.05, and the corrected 500's top-1 does not fall (rows gained minus lost >= 0). Session 2
clears its bound; the 500 does not (-1). **`text_anchor` therefore ships `false`** in
`planner_params.yaml`. The calibrator, threshold and prompt are unchanged; no retraining was
done, per 11B.7.

## 5. One live confirmation: e2e150 production at 150, text_anchor forced on (11B.4)

Fresh host `llama-server` (production model, Metal, nothing else on the GPU), fresh
`semantic_nav.launch.py` (launch health check passed: "Managed nodes are active" twice, no
out-of-bounds/no-map warnings before the suite started), production configuration (grammar on,
gate 0.85) with `text_anchor` forced on in `planner_params.yaml` for this one diagnostic run
only (reverted to `false` immediately after, before any commit), `--no-bag` per D56/8B practice.

| | before (8B) | after (8C, diagnostic) |
|---|---|---|
| spatial resolver correct | 2/30 | **30/30** |
| wrong-room gate-passed actions (of 140) | 26 | **0** |
| offline Condition B (0.85) vs C (0.0), wrong-room rate | 0.173 vs 0.187 | **0.000 vs 0.000** |
| resolver p50/p90/p99 | 3797/5160/n.a. ms | 3942/5540/7992 ms |

Exceeds the probe-derived estimate in PLAN.md 11B.4 ("about 18 spatial rows move to correct, to
about 20/30"). `model_room` (the model's raw `room` field) equals the corrected intended room on
17 of 30 spatial rows and `anchor_source` is `"text"` on all 30, confirming 11B.0 finding 1 from
committed data rather than the uncommitted probe. The resolver latency shift (+145/+380 ms
p50/p90) is well short of what GPU contention would produce (the fix adds no tokens) and is read
as ordinary session variance. Full table: `docs/results/e2e150_report_8c.md`. Raw data:
`data/frozen/e2e150_production_8c.jsonl`.

## 6. 8B corrections (11B.6)

- `ml/safenav_ml/offline_gate_comparison.py`: `gate_summary`'s "acted" definition now excludes a
  `"none"` answer (it was counting every row as acted at threshold 0.0). Gate-off wrong-room
  action rate corrects from 0.268 to 0.248 (500) and 0.290 to 0.190 (session 2); gate-on figures
  are unaffected. `docs/results/offline_gate_comparison.md` regenerated.
- `docs/results/RESULTS.md`: section 1's Phi-3.5 note gets the McNemar result and `multi_hop`
  concentration; section 3 gets the 3797/5160 ms ROS-path latency row (previously measured but
  missing from this file) beside the 8C diagnostic figure; section 5.1/5.2's offline gate table
  and 11A.6 interpretation are corrected in place with the superseded figures kept visible; a
  new section 5.3 holds the 8C before/after tables; section 6's spec table row is updated.
- `docs/reports/phase-8b-corrective.md`: dated amendment banner naming 11B.0 findings 1, 3, 4,
  5, 7 and 8 and pointing to this report. Body untouched.
- `docs/PLAN.md` section 1: the two e2e150 rows' citation fixed (D62, not D58); two new rows add
  the 8C diagnostic numbers rather than overwriting 8B's; a "Corrected by D64" note added.
- D59: a "Corrected by D63/D64" note appended, since the "90 of 91 null rows" claim cites the
  two 8B rerun files, not the production file the heading describes (79 nulls, 77 at the
  previous row's pose).
- Section 12.6: a dated note records the text anchor rule and D64; the grammar itself is
  unchanged.
- `README.md`: results summary gets the double-hop finding and the 8C result.

## 7. Tests (DoD)

```
docker exec safenav-dev bash -lc "cd /ws/ros2_ws && colcon build --symlink-install --packages-select semantic_waypoint_planner"
# Finished <<< semantic_waypoint_planner, clean

docker exec -e ROS_DOMAIN_ID=82 safenav-dev bash -lc "cd /ws/ros2_ws && colcon test --packages-select semantic_waypoint_planner"
# 166 tests, 0 errors, 0 failures, 0 skipped (no stack up, isolated domain)
```

One retry was needed: `test_test_resolver_only_launch.py`'s `test_five_commands` failed twice in
a row immediately after the e2e150 live run (empty `matched_room_name` for "somewhere I can
charge the robot", an in-process CPU-backend call on a container under elevated ambient load
from the desktop session), then passed cleanly on a third, otherwise-identical attempt. This is
the same flake D61 recorded in Phase 8B (same command, same failure mode, same documented
CPU-backend latency variance under `temperature=0.3` sampling), recurring under load rather than
newly introduced; no resolver, launch-graph or lifecycle-management change was made for it, per
D61's own scope note.

Host pytest (no rclpy needed): `test_relations.py` 37 passed, `test_resolver_core_offline.py` 27
passed (both include the new 11B.2 tests).

## 8. Data freeze

`data/frozen/` gains `text_anchor_replay_500.jsonl`, `text_anchor_replay_session1.jsonl`,
`text_anchor_replay_session2.jsonl` (the replay row-level output) and
`e2e150_production_8c.jsonl` (the live confirmation run), each with sha256, row count, producing
commit and command in `data/frozen/MANIFEST.md`. The host `llama-server` used `--no-bag` per
8B's own D56 practice.

## 9. What stands unchanged

The prompt, few-shot file, grammar (GBNF form), cue list, calibrator and threshold. The
calibration sessions' own labels, the corrected 500's labels, and e2e150's commands and labels.
8B's own findings that were not reopened by this review (the relabel, the metric split, the
reruns, 5 of 5 tests, 0.173 vs 0.187 as 8B measured it before this fix).

## 10. Deviations

D64 (PLAN.md section 14): the text anchor rule, its default-off shipping decision, and the
`offline_gate_comparison.py` fix.

## 11. Open items for a future phase

- The extraction rule's `multi_hop` regression (section 4) is a real, measured limitation, not
  tuned against here. A `multi_hop`-aware rule (e.g. restricting text anchor extraction to
  single-clause commands, or scoring the nearest cue to each clause separately) or 16A O1's
  calibrator retrain on the fixed resolver are both more promising than further tuning this one
  rule.
- 11B.0 finding 7 (the 4494 vs. 3737 ms isolated latency gap) remains open, unexplained beyond
  "session variance"; not investigated further here, per 11B.0's own framing.
- Whether phi3.5-mini's lead over phi3-mini (D63 finding 8) comes from better anchor-contract
  adherence, given this phase's finding that phi3-mini's defect is specifically in that
  contract, is untested and worth checking before any model-promotion decision.
