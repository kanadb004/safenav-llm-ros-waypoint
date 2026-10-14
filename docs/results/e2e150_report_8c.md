# Phase 8C: e2e150 production confirmation, text_anchor on (PLAN.md 11B.4)

One-time diagnostic run (`data/frozen/e2e150_production_8c.jsonl`): production configuration
(grammar on, gate 0.85) with `text_anchor` forced on for this run only (the shipped default was
off at the time, per PLAN.md 11B.5; see `docs/results/text_anchor_replay.md`). Fresh host
`llama-server` (production model, Metal, nothing else on the GPU), fresh `semantic_nav.launch.py`,
launch health check passed ("Managed nodes are active" twice, no out-of-bounds/no-map warnings
before the suite started), `--no-bag` per D56/8B practice. Metrics via
`ml/safenav_ml/e2e_report.py` (PLAN.md 11A.2).

**Corrected by D65 (2026-10-14, Phase 8D).** `text_anchor` is now the shipped default
everywhere (PLAN.md 11C). This run used exactly the now-shipped configuration, so it is the
shipped e2e150 measurement, not a diagnostic-only run; no rerun was done.

| suite | n | acted rate | wrong-room action rate (of n / of acted) | correct abstention | resolver correct | reach given correct (valid rows) | nav_invalid | out of graph | e2e p50/p90/p99 (n) | resolver p50/p90/p99 (n) | nav start p50/p90 (n, nulls) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| production (grammar on, gate on, text_anchor on) | 150 | 0.933 (140/150) | 0.000 (0/150) / 0.000 | 1.000 (3/3) | 0.953 (143/150) | 0.986 (138/140) | 1 (0.007 (1/150)) | 0 (0.000 (0/150)) | 4614/42650/59698 (n=150) | 3942/5540/7992 (n=149) | 3998/6085 (n=47, null=103) |

## Per-category wrong-room action rate

| suite | direct | alias | negation | abbreviation | spatial |
|---|---|---|---|---|---|
| production (text_anchor on) | 0.000 (0/30) | 0.000 (0/30) | 0.000 (0/30) | 0.000 (0/30) | 0.000 (0/30) |

**Wrong-room gate-passed actions: 0 of 150, down from 8B's 26 of 150 (25 of them spatial).**
Spatial resolver correct: 30 of 30 (up from 2 of 30 in 8B), exceeding the probe-derived estimate
in PLAN.md 11B.4 ("about 18 spatial rows move to correct ... to about 20/30").

## model_room check on every left/right row (PLAN.md 11B.4, confirms 11B.0 finding 1)

`model_room` (the raw `room` field the model emitted) equals the corrected intended room on
17 of 30 spatial rows; `anchor_room` (what the hop actually used) is `"text"`-sourced on all 30.
Every row resolves correctly regardless of whether the model's own first answer happened to be
right, because the hop now anchors on the command text instead of the model's `room` field:

| command | model_room | anchor_room (used) | resolved | intended |
|---|---|---|---|---|
| Go to the room near the kitchen. | meeting_room_a / storage_room (x2) | kitchen | charging_dock | charging_dock |
| Go to the room near the meeting room a. | storage_room | meeting_room_a | storage_room | storage_room |
| Go to the room near the meeting room b. | storage_room / meeting_room_a (x2) | meeting_room_b | lab | lab |
| Go to the room near the workshop. | lab (x2) / workshop | workshop | office | office |
| Go to the room to the left of the lab. | storage_room / lab | lab | storage_room | storage_room |
| Go to the room to the right of the charging dock. | storage_room | charging_dock | storage_room | storage_room |
| Go to the room to the right of the kitchen. | meeting_room_a | kitchen | meeting_room_a | meeting_room_a |
| Go to the room to the right of the meeting room a. | meeting_room_b | meeting_room_a | meeting_room_b | meeting_room_b |
| Go to the room to the right of the meeting room b. | office | meeting_room_b | office | office |
| Go to the room to the right of the office. | meeting_room_b | office | none | none |

Full per-row data: `data/frozen/e2e150_production_8c.jsonl` (columns `model_room`, `anchor_room`,
`anchor_source`, `relation`, `n_relation_targets`, `grammar_version`, added by PLAN.md 11B.1).

## Offline Condition B versus C (re-gated at 0.0, no separate run)

| | acted | wrong-room action rate (of n) |
|---|---|---|
| gate on (0.85, as collected) | 140/150 | 0.000 |
| gate off (0.0, re-gated offline) | 140/150 | 0.000 |

Identical: every row that acts at 0.0 also acts at 0.85 on this run, and none of them are wrong.
With the double hop fixed, the gate has nothing left to catch on this command set in either
direction, for a different reason than 8B's finding (there, wrong answers already cleared the
threshold; here there are no wrong answers for the threshold to act on).

**Corrected by D65 (2026-10-14, Phase 8D).** The table above is wrong: its gate-off row read
`gate_passed` as recorded rather than recomputing acted from `attempted_room`/
`calibrated_confidence`, so it silently repeated the gate-on acted count instead of re-gating at
0.0. Recomputed with `ml/safenav_ml/e2e_report.py --regate <threshold>` (PLAN.md 11C.3), acted
means a real room (`attempted_room` not `none`) whose `calibrated_confidence` clears the
threshold:

| | acted | wrong-room action rate (of n) |
|---|---|---|
| gate on (0.85, `--regate 0.85`) | 140/150 | 0.000 |
| gate off (0.0, `--regate 0.0`) | 143/150 | 0.020 (3/150) |

The gate catches all 3: three `negation` rows resolve to `meeting_room_b` at calibrated
confidence 0.798, below 0.85, so they abstain under the gate and would act wrongly without it.
"The gate has nothing left to catch" above is wrong; the corrected figure is **0.000 against
0.020**.

## Resolver latency, beside 8B's

| | p50 | p90 | p99 |
|---|---|---|---|
| 8B (`docs/reports/phase-8b-corrective.md`, 11B.0 finding 6) | 3797 ms | 5160 ms | n/a |
| 8C (this run) | 3942 ms | 5540 ms | 7992 ms |

+145 ms p50, +380 ms p90 (about 4% and 7%): the fix adds no tokens to the prompt or completion,
and this is well short of the kind of shift that would indicate GPU contention (11B.4's own
standard); read as ordinary session variance, consistent with 11B.0 finding 7's open latency
variance question, not a new effect of this phase's change.
