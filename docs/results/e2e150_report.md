# Phase 8: e2e150 suite results

| suite | n | success rate | gate pass rate | reached intended | false start rate | out of graph | e2e p50/p90/p99 ms | resolver p50/p90/p99 ms | nav start p50/p90 ms |
|---|---|---|---|---|---|---|---|---|---|
| production (grammar on, gate on) | 150 | 0.987 | 0.933 | 0.772 | 0.243 | 0 (0.000) | 9806/54620/76048 | 7883/10373/12954 | 7868/11110 |
| grammar off (gate on) | 50 | 1.000 | 0.960 | 0.800 | 0.208 | 0 (0.000) | 9199/55687/82704 | 8426/9496/44342 | 8785/10432 |
| gate off (threshold 0.0) | 50 | 1.000 | 0.960 | 0.080 | 0.917 | 0 (0.000) | 25639/603918/1104027 | 3878/9611/12159 | 5971/10679 |
