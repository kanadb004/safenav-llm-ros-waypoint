# PLAN.md 11C.1: text anchor fix, held-out replay v2 (D65)

Extends the 8C replay (`docs/results/text_anchor_replay.md`, D64) with the gated (0.85) effect on every held-out set's changed rows, since production always runs behind the gate (D65). The 8C replay's raw top-1 tables below are unchanged; this is an addition, not a correction of them.

## Corrected 500 benchmark (phase5a_full500.jsonl x synthetic_500_v2.jsonl)

n = 500. Rows changed: 15 (6 to correct, 7 from correct, 2 wrong to wrong).

| | raw top-1 (uncapped) | gated top-1 (0.85) |
|---|---|---|
| before | 0.732 | 0.720 |
| after | 0.730 | 0.722 |

Per category, raw top-1:

| category | before | after |
|---|---|---|
| abbreviation | 0.877 | 0.877 |
| adversarial | 0.444 | 0.444 |
| alias | 0.954 | 0.954 |
| direct | 0.969 | 0.969 |
| functional | 0.723 | 0.723 |
| multi_hop | 0.308 | 0.231 |
| negation | 0.877 | 0.877 |
| spatial | 0.615 | 0.677 |

Per category, gated top-1 (0.85):

| category | before | after |
|---|---|---|
| abbreviation | 0.877 | 0.877 |
| adversarial | 0.889 | 0.889 |
| alias | 0.938 | 0.938 |
| direct | 0.969 | 0.969 |
| functional | 0.323 | 0.323 |
| multi_hop | 0.815 | 0.815 |
| negation | 0.292 | 0.292 |
| spatial | 0.708 | 0.723 |

Every changed row:

| id | category | before | after | expected | model_room | anchor_used | anchor source | before calibrated | after calibrated | direction |
|---|---|---|---|---|---|---|---|---|---|---|
| p0142 | spatial | meeting_room_b | kitchen | kitchen | office | reception | text | 0.726 | 0.754 | to correct |
| p0143 | spatial | meeting_room_a | none | none | meeting_room_b | meeting_room_a | text | 0.949 | 0.593 | to correct |
| p0158 | spatial | meeting_room_b | meeting_room_a | none | meeting_room_a | kitchen | text | 0.698 | 0.698 | wrong to wrong |
| p0160 | spatial | none | lab | none | storage_shelf_1 | storage_room | text | 0.067 | 0.749 | from correct |
| p0182 | spatial | none | kitchen | kitchen | reception_desk | reception | text | 0.181 | 0.822 | to correct |
| p0186 | spatial | kitchen | none | none | reception | kitchen | text | 0.679 | 0.027 | to correct |
| p0190 | spatial | charging_dock | none | none | storage_room | charging_dock | text | 0.509 | 0.006 | to correct |
| p0400 | multi_hop | none | meeting_room_a | none | tool_cabinet | storage_room | text | 0.047 | 0.672 | from correct |
| p0402 | multi_hop | meeting_room_a | none | none | meeting_room_b | storage_room | text | 0.563 | 0.011 | to correct |
| p0407 | multi_hop | none | meeting_room_a | none | lab_bench_1 | storage_room | text | 0.002 | 0.281 | from correct |
| p0410 | multi_hop | none | meeting_room_b | none | storage_shelf_1 | lab | text | 0.006 | 0.424 | from correct |
| p0412 | multi_hop | none | meeting_room_b | none | office_desk_1 | lab | text | 0.001 | 0.256 | from correct |
| p0420 | multi_hop | reception | kitchen | none | server_room | charging_dock | text | 0.753 | 0.753 | wrong to wrong |
| p0438 | multi_hop | none | lab | none | battery_shelf | storage_room | text | 0.006 | 0.473 | from correct |
| p0447 | multi_hop | none | kitchen | none | server_rack_a | charging_dock | text | 0.027 | 0.634 | from correct |

### Gated (0.85) effect on actions, changed rows only (PLAN.md 11C.1)

| held-out set | rows changed | changed rows acting at 0.85, before | after | net effect on actions |
|---|---|---|---|---|
| corrected 500 | 15 | 1 | 0 | 1 wrong action(s) removed |

## Calibration session 1 (n=200)

Rows changed: 15 (5 to correct, 0 from correct, 10 wrong to wrong).

| run_id | category | before room | after room | intended | model_room | anchor_used | before edit_distance | after edit_distance | before calibrated | after calibrated | anchor source | direction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| session1_107 | negation | none | meeting_room_b | meeting_room_a | meeting_room_b | office | 117.0 | 2 | 0.001 | 0.242 | text | wrong to wrong |
| session1_12 | spatial | none | meeting_room_a | meeting_room_a | meeting_room_a | kitchen | 84.0 | 6 | 0.036 | 0.642 | text | to correct |
| session1_13 | spatial | server_room | charging_dock | charging_dock | charging_dock | server_room | 0.0 | 0 | 0.628 | 0.628 | text | to correct |
| session1_132 | spatial | charging_dock | storage_room | server_room | server_room | charging_dock | 0.0 | 4 | 0.847 | 0.820 | text | wrong to wrong |
| session1_136 | spatial | none | charging_dock | charging_dock | storage_shelf_1 | storage_room | 99.0 | 3 | 0.009 | 0.516 | text | to correct |
| session1_15 | spatial | charging_dock | storage_room | workshop | storage_room | lab | 3.0 | 4 | 0.655 | 0.644 | text | wrong to wrong |
| session1_176 | spatial | lab | storage_room | workshop | workshop | lab | 0.0 | 4 | 0.811 | 0.779 | text | wrong to wrong |
| session1_198 | multi_hop | none | office | tool_cabinet | tool_cabinet | workshop | 79.0 | 4 | 0.056 | 0.712 | text | wrong to wrong |
| session1_28 | negation | charging_dock | storage_room | storage_room | storage_room | charging_dock | 0.0 | 0 | 0.809 | 0.809 | text | to correct |
| session1_36 | multi_hop | none | office | workshop_bench | tool_cabinet | workshop | 97.0 | 4 | 0.011 | 0.526 | text | wrong to wrong |
| session1_37 | multi_hop | none | workshop | office_desk_1 | office_desk_1 | office | 88.0 | 6 | 0.025 | 0.600 | text | wrong to wrong |
| session1_39 | multi_hop | none | kitchen | storage_shelf_1 | storage_shelf_1 | charging_dock | 123.0 | 4 | 0.001 | 0.258 | text | wrong to wrong |
| session1_92 | spatial | none | meeting_room_a | meeting_room_a | meeting_room_a | kitchen | 91.0 | 6 | 0.019 | 0.567 | text | to correct |
| session1_94 | spatial | server_room | none | charging_dock | charging_dock | server_room | 0.0 | 107 | 0.464 | 0.004 | text | wrong to wrong |
| session1_97 | spatial | lab | none | workshop | workshop | lab | 0.0 | 115 | 0.378 | 0.002 | text | wrong to wrong |

## Calibration session 2 (n=100)

Rows changed: 10 (0 to correct, 0 from correct, 10 wrong to wrong).

| run_id | category | before room | after room | intended | model_room | anchor_used | before edit_distance | after edit_distance | before calibrated | after calibrated | anchor source | direction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| session2_18 | multi_hop | lab | workshop | meeting_room_b_screen | meeting_room_b | office | 2.0 | 4 | 0.484 | 0.459 | text | wrong to wrong |
| session2_27 | spatial | none | meeting_room_a | reception | kitchen_sink | kitchen | 111.0 | 5 | 0.001 | 0.197 | text | wrong to wrong |
| session2_33 | negation | none | office | workshop_bench | lab_bench_1 | workshop | 91.0 | 4 | 0.019 | 0.592 | text | wrong to wrong |
| session2_47 | spatial | none | meeting_room_a | coffee_machine | kitchen_sink | kitchen | 115.0 | 6 | 0.002 | 0.310 | text | wrong to wrong |
| session2_59 | multi_hop | none | office | tool_cabinet | tool_cabinet | workshop | 68.0 | 4 | 0.143 | 0.801 | text | wrong to wrong |
| session2_66 | spatial | workshop | lab | storage_room | lab | workshop | 0.0 | 0 | 0.809 | 0.809 | text | wrong to wrong |
| session2_7 | spatial | lab | none | workshop | workshop | lab | 0.0 | 83 | 0.716 | 0.039 | text | wrong to wrong |
| session2_88 | spatial | kitchen | none | meeting_room_a | meeting_room_a | kitchen | 0.0 | 83 | 0.716 | 0.039 | text | wrong to wrong |
| session2_98 | multi_hop | meeting_room_a | meeting_room_b | storage_room | storage_room | lab | 8.0 | 9 | 0.695 | 0.685 | text | wrong to wrong |
| session2_99 | multi_hop | none | workshop | office_desk_2 | office_desk_1 | office | 76.0 | 6 | 0.073 | 0.719 | text | wrong to wrong |

### Gated (0.85) effect on actions, changed rows only, sessions (PLAN.md 11C.1)

| held-out set | rows changed | changed rows acting at 0.85, before | after | net effect on actions |
|---|---|---|---|---|
| session 1 | 15 | 0 | 0 | none |
| session 2 | 10 | 0 | 0 | none |

## Session 2 gate rates at 0.85

| | false pass rate | false rejection rate | n correct / n |
|---|---|---|---|
| before | 0.043 | 0.366 | 71/100 |
| after | 0.043 | 0.366 | 71/100 |

## PLAN.md 11B.5 decision rule inputs (superseded by D65, kept as measured)

- session 2 false pass at 0.85, after: 0.043 (<= 0.05)
- corrected 500 top-1, rows gained minus lost: -1 (< 0)

## PLAN.md 11C.1 stop rule (11C.0 finding 1 reproduction)

- no wrong action added at 0.85 on any held-out set: True
- no correct action removed at 0.85 on any held-out set: True
- session 2 false pass at 0.85 at or below 0.05: True (0.043)
- **stop rule clears: True**
