# PLAN.md 11A.5: offline Condition B versus C

### Corrected 500 benchmark (phase5a_full500.jsonl x synthetic_500_v2.jsonl)

| threshold | n | acted rate | wrong-room action rate (of n / of acted) |
|---|---|---|---|
| gate on (0.85) | 500 | 0.508 (254/500) | 0.056 (28/500) / 0.110 |
| gate off (0.0) | 500 | 0.842 (421/500) | 0.248 (124/500) / 0.295 |

Per category (gate on 0.85 vs gate off 0.0), wrong-room action rate:

| category | gate on (0.85) | gate off (0.0) |
|---|---|---|
| abbreviation | 0.123 (8/65) | 0.123 (8/65) |
| adversarial | 0.111 (5/45) | 0.556 (25/45) |
| alias | 0.046 (3/65) | 0.046 (3/65) |
| direct | 0.031 (2/65) | 0.031 (2/65) |
| functional | 0.046 (3/65) | 0.277 (18/65) |
| multi_hop | 0.046 (3/65) | 0.677 (44/65) |
| negation | 0.000 (0/65) | 0.092 (6/65) |
| spatial | 0.062 (4/65) | 0.277 (18/65) |

### Session 2 calibration trials (calibration/session2_trials.jsonl)

| threshold | n | acted rate | wrong-room action rate (of n / of acted) |
|---|---|---|---|
| gate on (0.85) | 100 | 0.470 (47/100) | 0.020 (2/100) / 0.043 |
| gate off (0.0) | 100 | 0.900 (90/100) | 0.190 (19/100) / 0.211 |

Per category (gate on 0.85 vs gate off 0.0), wrong-room action rate:

| category | gate on (0.85) | gate off (0.0) |
|---|---|---|
| abbreviation | 0.000 (0/15) | 0.000 (0/15) |
| alias | 0.067 (1/15) | 0.133 (2/15) |
| direct | 0.000 (0/15) | 0.000 (0/15) |
| functional | 0.000 (0/15) | 0.133 (2/15) |
| multi_hop | 0.000 (0/10) | 0.200 (2/10) |
| negation | 0.067 (1/15) | 0.200 (3/15) |
| spatial | 0.000 (0/15) | 0.667 (10/15) |
