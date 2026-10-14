# SafeNav-LLM: consolidated results (Phases 4 through 8)

This is the single place every measured number in the project traces back to. Every table below
cites the JSONL or CSV file it is computed from, under `data/` unless noted; regenerable run
output lives under the gitignored `data/runs/`, committed source data lives under
`data/benchmark/` and `data/calibration/`.

Software simulation only (loopback, D30; see Limitations). Hardware (TurtleBot4, Jetson Orin NX)
is Phase 9/10.

## 1. Resolver accuracy, by phase

| Phase | Configuration | n | top-1 | top-3 | out-of-graph |
|-------|--------------|---|-------|-------|--------------|
| 4 | v1 single-field grammar, best prompt iteration | 500 | 0.662 | n/a | 0.01 (D24) |
| 5 | v2 relational grammar, unconditional hop | 500 | 0.560 | 0.754 | 0.0 |
| 5A | v1/v2 cue-gated selection, corrected labels (`synthetic_500_v2.jsonl`) | 500 | **0.732** | 0.868 | 0.0 |
| 5A | same, original labels (continuity with Phase 4/5) | 500 | 0.646 | n/a | 0.0 |

The Phase 5A corrected-label top-1 (0.732) has no pass/fail gate (D45): 96 of 500 rows are
structurally unanswerable from the graph alone (two or more equally valid targets, no
distinguishing cue in the command text), so the benchmark's own ceiling is about 0.81. 0.732 is
about 90 percent of that ceiling.

### 1.1 Per-category top-1, all four configurations

| category | Phase 4 (v1 only) | Phase 5 (v2 unconditional) | Phase 5A, original labels | Phase 5A, corrected labels |
|---|---|---|---|---|
| direct | 0.923 | 0.877 | 0.969 | 0.969 |
| alias | 0.954 | 0.769 | 0.954 | 0.954 |
| negation | 0.969 | 0.692 | 0.877 | 0.877 |
| abbreviation | 0.862 | 0.800 | 0.877 | 0.877 |
| functional | 0.692 | 0.477 | 0.723 | 0.723 |
| adversarial | 0.400 | 0.556 | 0.444 | 0.444 |
| spatial | 0.262 | 0.246 | 0.215 | 0.615 |
| multi_hop | 0.154 | 0.062 | 0.046 | 0.308 |
| **total** | **0.662** | **0.560** | **0.646** | **0.732** |

Cue gating (Phase 5A, D40-D44) recovers the regression Phase 5 introduced on the four easy
categories (correct-anchor rows a spurious hop overwrote) while the relabel corrects the
benchmark's own `spatial`/`multi_hop` labels rather than the model's behaviour on them. See
`docs/reports/phase-5a-corrective.md` section 2 and `data/benchmark/RELABEL.md`.

## 2. Gated end-to-end accuracy (Phase 7)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Gated end-to-end accuracy, 500 benchmark, corrected labels | 0.72 | >= 0.75 (D54, KnowNo multi-step); 0.824 category-weighted | provisional (D53), within noise of 0.75, misses 0.824 |
| CV ECE (session 1, out-of-fold) | 0.0698 | <= 0.10 | met |
| Calibrated ECE (session 2) | 0.0730 | <= 0.08 | met |
| False pass rate (session 2) | 0.0426 | <= 5% | met |
| False rejection rate (session 2) | 0.3662 | gate withdrawn (D54); provable optimum for the shipped feature vector | reported |
| Help rate (session 2) | 0.53 | KnowNo band 0.58-0.92 | favourable (below every KnowNo setting) |
| Precision on acted-upon commands (session 2) | 0.957 | none set | reported |

**D53 (carried forward):** two of the five section 12.8 calibration features carry no
information in this build (`n_candidates` constant at 30.0 with a trained weight of 0.0;
`token_entropy` is the binary entropy of `raw_confidence`, not a room-level distribution
entropy). The gated-accuracy and false-rejection rows above are therefore provisional, not a
measurement of the system against the specification with a complete instrument. Not re-tuned,
per the Phase 7 scope's explicit instruction not to fit session 2.

Reliability diagram: `docs/results/calibration_session1.png`. Full metrics:
`docs/results/calibration_metrics.json`.

## 3. Latency

| Where | p50 | p90 | p99 | Notes |
|-------|-----|-----|-----|-------|
| macOS host, Metal, cold, v1 grammar path (cue-free, 5A) | 3026 ms | 3497 ms | 9448 ms | `predicted_per_token_ms` 137.7 |
| macOS host, Metal, cold, v2 grammar path (cued, 5A) | 3939 ms | 4272 ms | 5057 ms | `predicted_per_token_ms` 139.7 |
| macOS host, Metal, sustained session (Phase 5, thermal confound) | 6478 ms | 7220 ms | 7768 ms | superseded by the cold 5A figures; not citable as the system's number (D41) |
| Docker container, CPU only, arm64 VM (Phase 8 spot check, n=3, `backend=inprocess`) | 9612 ms (warm) | n/a | n/a | cold first call 165657 ms; confirms D16/D18's "tens of seconds to minutes" qualitatively, n too small for a real p50/p90; not the deployed path |
| Phase 8 e2e150 resolver latency (production, driven through the full ROS graph) | 7883 ms | 10373 ms | 12954 ms | `data/runs/e2e150_loopback.jsonl`; **not a clean measurement** (D56): the model ablation's own `llama-server` was running concurrently on the same Metal GPU for most of this suite, so these numbers are inflated by GPU contention and should not be read as a second, independent confirmation of the p90 gate result. Relative comparisons within this table are unaffected. |

**Gate: p90 < 3000 ms, internally set, stricter than nothing in the literature (D54).** The
cold v1-path p90 (3497 ms) and the cue-gated traffic-weighted p90 (3737 ms, 5A) both miss it.
The grammar-size hypothesis behind the original miss is refuted by the cold per-token
measurement: v1 and v2 paths decode at nearly the same per-token cost (137.7 vs 139.7 ms),
so the gap is the base model's decode speed on this prompt length, not the grammar.
16A O3 (perceived-latency filler) does not change this row; see PLAN.md section 1.

## 4. Model ablation (Phase 8)

Production configuration (`fewshot_count=0`, `temperature=0.3`, grammar on), full 500 benchmark
(`synthetic_500.jsonl`, original labels, for continuity with Phases 4/5), each model loaded into
its own `llama-server` instance on the Metal host, one at a time. Latency was measured while the
e2e150 suite's own resolver was concurrently active on a separate `llama-server` instance for
all of phi3-mini and tinyllama's rows and part of phi3.5-mini's, so, as in section 3, absolute
latency here is inflated by GPU contention; relative ordering between models is still meaningful.

| model | n | top-1 | top-3 | out-of-graph | p50 ms | p90 ms | llama-server RSS |
|---|---|---|---|---|---|---|---|
| phi3-mini-4k-instruct.Q4_K_M (production) | 500 | 0.650 | 0.763 | 0.0 | 5005 | 8329 | 3123 MB |
| tinyllama-1.1b-chat-v1.0.Q4_K_M | 500 | 0.402 | 0.686 | 0.0 | 1417 | 2749 | 717 MB |
| phi3.5-mini-instruct.Q4_K_M | 500 | 0.654 | 0.763 | 0.0 | 4427 | 7238 | 3010 MB |

Phi3-mini's 0.650 top-1 here (original labels, cue-gated selection) is consistent with Phase
5A's own original-label figure of 0.646 for the same configuration, which cross-checks this
script against the Phase 5A result independently. Phi3.5-mini edges out phi3-mini by 0.4 points,
within noise at n=500 and far short of D36's "promote if more than 2 points better" bar from
Phase 5; phi3-mini remains production. TinyLlama trades about 25 points of top-1 for roughly
3.5x lower latency and 4.3x lower RSS, consistent with its much smaller parameter count, and
confirms the capability gap motivating the Phi-3 family choice in the first place.

Raw data: `data/runs/model_ablation/<model>.jsonl`. Summary: `docs/results/model_ablation.json`.

## 5. e2e150 suite (Phase 8)

10 navigable rooms (the Phase 2 ten-room tour) x 5 phrasing categories (direct, alias, negation,
abbreviation, spatial) x 3 trials = **150 commands for the production suite** (grammar on, gate
on at the deployed threshold 0.85), driven through the real `/semantic_goal` -> `bt_navigator`
-> Nav2 graph in loopback (D30), not a resolver-only replay (contrast with Phase 7's
`ml/safenav_ml/run_trials.py`, D49). Each spatial command's (anchor, relation) pair is checked
against `AnnotationGraph.related_rooms()` at import time
(`ros2_ws/src/semantic_waypoint_planner/scripts/run_trials.py`) so it resolves to exactly the
intended room given the committed graph, independent of what the model actually outputs.

**D56: the grammar-off and gate-off ablations ran at 1 trial per command (50 rows), not 3
(150).** The production suite's own throughput (observed ~20 s/row, dominated by genuine Nav2
drive time on first arrival at a new room) made a second and third full 150-row pass a multi-hour
addition with no plan in the budget for it; the DoD's requirement is 0 out-of-graph on the
production suite specifically and "as measured" reporting for the ablations, both of which a
50-row pass still satisfies, so this is a reporting-depth tradeoff, not a skipped gate. All three
suites share the same `build_commands()` 50-command set, so the 50-row ablations are a strict
subset of the conditions the production suite covers at 3x the repetition.

| suite | n | success rate | gate pass rate | reached intended | false start rate | out of graph | e2e p50/p90/p99 ms | resolver p50/p90/p99 ms | nav start p50/p90 ms |
|---|---|---|---|---|---|---|---|---|---|
| production (grammar on, gate on, n=150) | 150 | 0.987 | 0.933 | 0.772 | 0.243 | 0 (0.000) | 9806/54620/76048 | 7883/10373/12954 | 7868/11110 |
| grammar off, gate on (n=50) | 50 | 1.000 | 0.960 | 0.800 | 0.208 | 0 (0.000) | 9199/55687/82704 | 8426/9496/44342 | 8785/10432 |
| gate off, threshold 0.0 (n=50) | 50 | 1.000 | 0.960 | 0.080 | **0.917** | 0 (0.000) | 25639/603918/1104027 | 3878/9611/12159 | 5971/10679 |

**The gate-on vs. gate-off comparison the specification asks for (Condition B vs. Condition C)
is the headline of this table.** With the gate at its deployed threshold, 77.2% of accepted
navigations actually reach the intended room (false start rate 24.3%). With the gate disabled,
that collapses to 8.0% reached (false start rate 91.7%): removing the gate does not just let a
few more wrong answers through, it makes "the robot moved somewhere" almost uncorrelated with
"the robot moved somewhere correct." This is the core safety claim in one number.

**The gate-off suite's e2e latency numbers are not a clean measurement of nominal drive time**
and should not be read as "the system is this slow without the gate." `data/runs/
e2e150_gate_off.jsonl` shows 16 of 50 rows (32%) taking 60 s to over 20 minutes, and the Nav2
log for that window (`/tmp/launch2.log`, not committed) shows long alternating `spin`/`backup`
recovery-behavior loops, not a single slow drive. Grammar-off's e2e p99 (82.7 s) and the
production suite's own (76.0 s) also exceed what distance alone explains, pointing at the same
mechanism to a lesser degree: all three suites were run back to back against one continuous
`semantic_nav.launch.py` session (one `loopback_sim_node`, one `semantic_goal_node`) totalling
250 real `NavigateToPose` goals with no pose reset between suites, and the loopback simulator
(D11/D30: a unicycle integrator and ray-cast `/scan`, not a physics engine) was not designed or
tested for that many sequential goals in one session. Gate-off is disproportionately affected
because its higher accept rate sends far more of its 50 commands into real navigation than the
other two suites, so it accumulates more of whatever drift or costmap staleness builds up over
the session. **This is a real limitation of how this phase measured, not a property of
disabling the gate that a reader should generalize from.** A clean measurement would reset the
loopback sim (or relaunch the stack) between suites; that is recorded as an open risk for
Phase 9 rather than redone here, since the false-start-rate comparison above, which does not
depend on absolute drive time, already carries the DoD's point.

Raw data: `data/runs/e2e150_loopback.jsonl` (production), `data/runs/e2e150_grammar_off.jsonl`,
`data/runs/e2e150_gate_off.jsonl`. Bags: `data/bags/e2e150_production/` (production suite only;
the two 50-row ablations ran with `--no-bag` to save time, per D56).

## 6. Specification evaluation metrics table (filled in)

| Specification metric | Measured | Source |
|---|---|---|
| Out of graph rate, grammar on | 0% (structural) | section 1, section 5 |
| Out of graph rate, grammar off | 0/50 on the e2e150 ablation (D56: n=50, too small to confirm or refute D24's 1.0%/500 figure on its own); 1.0% (5/500) on the Phase 4 full-500 study | section 5, D24 |
| Gated end-to-end accuracy | 0.72 (provisional, D53) | section 2 |
| Resolver latency p90 (deployed backend) | 3497-4272 ms cold (5A, isolated); 7883-10373 ms under Phase 8's concurrent-GPU-load measurement (not citable against the gate, see section 3) | section 3 |
| 150-run e2e validation, grammar on | 0/150 out-of-graph outputs (required, met) | section 5 |
| Gate on vs. gate off reached-intended rate | 0.772 (gate on) vs. 0.080 (gate off) | section 5 |

This table reproduces the shape of the metrics table in `docs/reference/Review_2_Phase_2.docx`,
which was drafted inside this project and never approved at Review 2 (D54); its numbers carry
no external authority here. Every measured value above is reported plainly against the
literature-anchored or internally-set target recorded in PLAN.md section 1, not against that
document's table.

## 7. Limitations

- **Gazebo gap (D11, D30).** Robot spawn (lidar/depth sensor creation) segfaults the Ignition
  Fortress server under the container's software renderer. Every simulation result in this
  project, including the e2e150 suite, is loopback: a unicycle integrator with ray-cast `/scan`
  and an identity `map -> odom` transform, not a physics simulation. Controller behaviour,
  collision avoidance and sensor noise are therefore not exercised by anything in this report.
- **Simulated calibration logs (D7).** The five-persona deployment logs behind the Phase 7
  calibrator are generated by the Mistral API, not collected from a human operator session.
  Human sessions and hardware are Phase 10.
- **Heuristic top-3 ranking (D12).** `token_entropy` and `room_ranking` are not model scores:
  entropy is the binary entropy of the reported confidence, and the ranking splits the
  remaining probability mass by inverse Levenshtein distance. Every top-3 figure in this report
  inherits this.
- **Incomplete calibration feature vector (D53).** `n_candidates` is constant and
  `token_entropy` duplicates `raw_confidence`'s information rather than adding a genuine
  per-instance uncertainty signal. The gated-accuracy and false-rejection numbers in section 2
  are provisional until PLAN.md section 16A's fix lands.
- **Self-adjudication throughout.** The Phase 4 dataset review (D25) and the Phase 5A benchmark
  relabel (8A.2) were both adjudicated by the same session that produced the system under test,
  not an independent reviewer. The relabel rule is graph-derived and model-blind and was frozen
  before running, and both label sets are reported side by side in section 1, but a reader
  should weigh this against an external audit rather than take either defence as dispositive.
- **One operator, one goal at a time (D46).** The `/semantic_resolution_result` side channel
  correlates by command text, not a goal ID; concurrent identical-text goals are unsupported.
- **Un-reset loopback session across the three e2e150 suites (D56).** 250 real `NavigateToPose`
  goals were sent to one continuous launch of `semantic_nav.launch.py` with no pose reset between
  suites; Nav2 recovery-behaviour loops (`spin`/`backup` cycling, visible in the uncommitted
  launch log) inflate the e2e latency tails reported in section 5, most severely for gate-off.
  The false-start-rate comparison (0.772 vs. 0.080 reached-intended) does not depend on absolute
  timing and is unaffected; absolute e2e latency figures for the ablation suites should not be
  read as the system's nominal drive time. Resetting between suites is an open risk for Phase 9.
- **Model ablation latency measured under concurrent GPU load (D56).** The Phase 8 model
  ablation table's `p50_ms`/`p90_ms` columns were collected while the e2e150 production and
  grammar-off suites were running their own `llama-server` concurrently on the same Metal GPU.
  Relative ordering between the three models is still meaningful; absolute values should not be
  compared against Phase 3/5A's isolated cold-latency figures or the 3000 ms gate.
- **Grammar-off and gate-off ablations ran at n=50, not n=150 (D56).** A budget tradeoff given
  the production suite's own ~3-hour wall-clock time; see section 5.
