# Phase 8B: e2e150 suite results (PLAN.md 11A.2 metrics)

| suite | n | acted rate | wrong-room action rate (of n / of acted) | correct abstention | resolver correct | reach given correct (valid rows) | nav_invalid | out of graph | e2e p50/p90/p99 (n) | resolver p50/p90/p99 (n) | nav start p50/p90 (n, nulls) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| production (grammar on, gate on) | 150 | 0.933 (140/150) | 0.173 (26/150) / 0.186 | 0.333 (1/3) | 0.767 (115/150) | 0.921 (105/114) | 1 (0.007 (1/150)) | 0 (0.000 (0/150)) | 9806/54620/76048 (n=150) | 7883/10373/12954 (n=148) | 7868/11110 (n=71, null=79) |
| grammar off (gate on) | 150 | 0.960 (144/150) | 0.187 (28/150) / 0.194 | 0.000 (0/3) | 0.773 (116/150) | 1.000 (116/116) | 0 (0.000 (0/150)) | 0 (0.000 (0/150)) | 5005/51189/60079 (n=150) | 4709/5642/37935 (n=150) | 5060/5822 (n=59, null=91) |
| gate off (threshold 0.0) | 150 | 0.960 (144/150) | 0.187 (28/150) / 0.194 | 0.000 (0/3) | 0.773 (116/150) | 1.000 (116/116) | 0 (0.000 (0/150)) | 0 (0.000 (0/150)) | 4271/43232/53168 (n=150) | 3797/5160/6019 (n=150) | 4587/5904 (n=59, null=91) |

## Per-category wrong-room action rate

| suite | direct | alias | negation | abbreviation | spatial |
|---|---|---|---|---|---|
| production (grammar on, gate on) | 0.000 (0/30) | 0.000 (0/30) | 0.033 (1/30) | 0.000 (0/30) | 0.833 (25/30) |
| grammar off (gate on) | 0.000 (0/30) | 0.000 (0/30) | 0.100 (3/30) | 0.000 (0/30) | 0.833 (25/30) |
| gate off (threshold 0.0) | 0.000 (0/30) | 0.000 (0/30) | 0.100 (3/30) | 0.000 (0/30) | 0.833 (25/30) |
