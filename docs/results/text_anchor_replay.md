# PLAN.md 11B.3: text anchor fix, held-out replay (D64)

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

| id | category | before | after | expected | anchor source | direction |
|---|---|---|---|---|---|---|
| p0142 | spatial | meeting_room_b | kitchen | kitchen | text | to correct |
| p0143 | spatial | meeting_room_a | none | none | text | to correct |
| p0158 | spatial | meeting_room_b | meeting_room_a | none | text | wrong to wrong |
| p0160 | spatial | none | lab | none | text | from correct |
| p0182 | spatial | none | kitchen | kitchen | text | to correct |
| p0186 | spatial | kitchen | none | none | text | to correct |
| p0190 | spatial | charging_dock | none | none | text | to correct |
| p0400 | multi_hop | none | meeting_room_a | none | text | from correct |
| p0402 | multi_hop | meeting_room_a | none | none | text | to correct |
| p0407 | multi_hop | none | meeting_room_a | none | text | from correct |
| p0410 | multi_hop | none | meeting_room_b | none | text | from correct |
| p0412 | multi_hop | none | meeting_room_b | none | text | from correct |
| p0420 | multi_hop | reception | kitchen | none | text | wrong to wrong |
| p0438 | multi_hop | none | lab | none | text | from correct |
| p0447 | multi_hop | none | kitchen | none | text | from correct |

## Calibration session 1 (n=200)

Rows changed: 15 (5 to correct, 0 from correct, 10 wrong to wrong).

| run_id | category | before room | after room | intended | before edit_distance | after edit_distance | before calibrated | after calibrated | anchor source | direction |
|---|---|---|---|---|---|---|---|---|---|---|
| session1_107 | negation | none | meeting_room_b | meeting_room_a | 117.0 | 2 | 0.001 | 0.242 | text | wrong to wrong |
| session1_12 | spatial | none | meeting_room_a | meeting_room_a | 84.0 | 6 | 0.036 | 0.642 | text | to correct |
| session1_13 | spatial | server_room | charging_dock | charging_dock | 0.0 | 0 | 0.628 | 0.628 | text | to correct |
| session1_132 | spatial | charging_dock | storage_room | server_room | 0.0 | 4 | 0.847 | 0.820 | text | wrong to wrong |
| session1_136 | spatial | none | charging_dock | charging_dock | 99.0 | 3 | 0.009 | 0.516 | text | to correct |
| session1_15 | spatial | charging_dock | storage_room | workshop | 3.0 | 4 | 0.655 | 0.644 | text | wrong to wrong |
| session1_176 | spatial | lab | storage_room | workshop | 0.0 | 4 | 0.811 | 0.779 | text | wrong to wrong |
| session1_198 | multi_hop | none | office | tool_cabinet | 79.0 | 4 | 0.056 | 0.712 | text | wrong to wrong |
| session1_28 | negation | charging_dock | storage_room | storage_room | 0.0 | 0 | 0.809 | 0.809 | text | to correct |
| session1_36 | multi_hop | none | office | workshop_bench | 97.0 | 4 | 0.011 | 0.526 | text | wrong to wrong |
| session1_37 | multi_hop | none | workshop | office_desk_1 | 88.0 | 6 | 0.025 | 0.600 | text | wrong to wrong |
| session1_39 | multi_hop | none | kitchen | storage_shelf_1 | 123.0 | 4 | 0.001 | 0.258 | text | wrong to wrong |
| session1_92 | spatial | none | meeting_room_a | meeting_room_a | 91.0 | 6 | 0.019 | 0.567 | text | to correct |
| session1_94 | spatial | server_room | none | charging_dock | 0.0 | 107 | 0.464 | 0.004 | text | wrong to wrong |
| session1_97 | spatial | lab | none | workshop | 0.0 | 115 | 0.378 | 0.002 | text | wrong to wrong |

## Calibration session 2 (n=100)

Rows changed: 10 (0 to correct, 0 from correct, 10 wrong to wrong).

| run_id | category | before room | after room | intended | before edit_distance | after edit_distance | before calibrated | after calibrated | anchor source | direction |
|---|---|---|---|---|---|---|---|---|---|---|
| session2_18 | multi_hop | lab | workshop | meeting_room_b_screen | 2.0 | 4 | 0.484 | 0.459 | text | wrong to wrong |
| session2_27 | spatial | none | meeting_room_a | reception | 111.0 | 5 | 0.001 | 0.197 | text | wrong to wrong |
| session2_33 | negation | none | office | workshop_bench | 91.0 | 4 | 0.019 | 0.592 | text | wrong to wrong |
| session2_47 | spatial | none | meeting_room_a | coffee_machine | 115.0 | 6 | 0.002 | 0.310 | text | wrong to wrong |
| session2_59 | multi_hop | none | office | tool_cabinet | 68.0 | 4 | 0.143 | 0.801 | text | wrong to wrong |
| session2_66 | spatial | workshop | lab | storage_room | 0.0 | 0 | 0.809 | 0.809 | text | wrong to wrong |
| session2_7 | spatial | lab | none | workshop | 0.0 | 83 | 0.716 | 0.039 | text | wrong to wrong |
| session2_88 | spatial | kitchen | none | meeting_room_a | 0.0 | 83 | 0.716 | 0.039 | text | wrong to wrong |
| session2_98 | multi_hop | meeting_room_a | meeting_room_b | storage_room | 8.0 | 9 | 0.695 | 0.685 | text | wrong to wrong |
| session2_99 | multi_hop | none | workshop | office_desk_2 | 76.0 | 6 | 0.073 | 0.719 | text | wrong to wrong |

## Session 2 gate rates at 0.85

| | false pass rate | false rejection rate | n correct / n |
|---|---|---|---|
| before | 0.043 | 0.366 | 71/100 |
| after | 0.043 | 0.366 | 71/100 |

## PLAN.md 11B.5 decision rule inputs

- session 2 false pass at 0.85, after: 0.043 (<= 0.05)
- corrected 500 top-1, rows gained minus lost: -1 (< 0)
