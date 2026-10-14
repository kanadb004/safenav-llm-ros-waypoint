# SafeNav-LLM: consolidated results (Phases 4 through 8)

> **Amended 2026-10-14 (Phase 8B, `docs/reports/phase-8b-corrective.md`).** Sections 1, 3, 4, 5,
> 6 and 7 below are corrected in place for this pass; each superseded figure stays visible with
> a "superseded by 8B" note rather than being deleted. Every table now cites a file in
> `data/frozen/` (PLAN.md 11A.9). Headline corrections: the e2e150 gate-on vs. gate-off
> reached-intended comparison (section 5) was a navigation artifact, not a gate effect, and the
> corrected comparison (wrong-room action rate) shows the gate making no measurable difference
> on this command set; the e2e150 spatial category's intended rooms were mislabelled for six of
> ten room keys and are now 2/30 correct, not reported before; all latency figures below that
> were collected under GPU contention are now joined by an isolated remeasure.

> **Amended 2026-10-14 (Phase 8C, `docs/reports/phase-8c-spatial-anchor-fix.md`, D64).** Section
> 5.1's 2/30 spatial figure and the 26/140 wrong-pass finding are a resolver double hop
> (`_resolve_llm` hopping twice because the model's `room` field often holds the answer, not the
> anchor), not a calibrator separability problem; 11A.6's interpretation below is superseded.
> Section 5.2's offline gate comparison had a bug counting `none` answers as acted-on rows at
> threshold 0.0 (D63 finding 3), corrected here. The fix (`relations.apply_relational_hop`,
> `text_anchor` parameter) ships with its default **off**: it eliminates e2e150's spatial misses
> (2/30 to 30/30) but costs one net row on the held-out corrected 500 (`docs/results/
> text_anchor_replay.md`), all losses in `multi_hop` compound sentences. Section 3's latency gap
> (4494 vs. 3737 ms) stays an open, unexplained item (D63 finding 7), joined here by its own
> 3797/5160 ms ROS-path figure, previously missing from this file (D63 finding 6).

> **Amended 2026-10-14 (Phase 8D, `docs/reports/phase-8d-ship-text-anchor.md`, D65).** The
> "ships off" decision above is reversed: `text_anchor` now ships **on** everywhere. 11B.5's rule
> measured the corrected 500's raw top-1 without the gate, the wrong quantity for a shipping
> decision, because production always runs behind the 0.85 gate. Under the gate, across all 800
> held-out rows (500, session 1, session 2), the fix changes behaviour on exactly one row,
> removing a wrong action and adding none (`docs/results/text_anchor_replay_v2.md`, PLAN.md
> 11C.1). The project owner chose to ship on after seeing this gated evidence; this is disclosed
> as a decision made after the results, not as following the frozen 11B.5 rule. Section 5.2's
> offline Condition B versus C figure for the 8C diagnostic run (0.000 against 0.000) was also a
> computation error: the corrected figure is 0.000 against 0.020 (3/150 `negation` rows wrong at
> 0.798 without the gate), see section 5.3 and `docs/results/e2e150_report_8c.md`.

This is the single place every measured number in the project traces back to. Every table below
cites the JSONL or CSV file it is computed from, under `data/` unless noted; regenerable run
output lives under the gitignored `data/runs/`, committed source data lives under
`data/benchmark/` and `data/calibration/`.

Software simulation only (loopback, D30; see Limitations). Hardware (TurtleBot4, Jetson Orin NX)
is Phase 9/10.

## 1. Resolver accuracy, by phase

| Phase | Configuration | n | top-1 | top-3 | out-of-graph |
|-------|--------------|---|-------|-------|--------------|
| 4 | v1 single-field grammar, best prompt iteration | 500 | 0.662 | 0.780 (superseded by 8B's finding that this table omitted it; `docs/reports/phase-4-prompt-study.md` line 165) | 0.01 (D24) |
| 5 | v2 relational grammar, unconditional hop | 500 | 0.560 | 0.754 | 0.0 |
| 5A | v1/v2 cue-gated selection, corrected labels (`synthetic_500_v2.jsonl`) | 500 | **0.732** | 0.868 | 0.0 |
| 5A | same, original labels (continuity with Phase 4/5) | 500 | 0.646 | n/a | 0.0 |

The Phase 5A corrected-label top-1 (0.732) has no pass/fail gate (D45): 96 of 500 rows are
structurally unanswerable from the graph alone (two or more equally valid targets, no
distinguishing cue in the command text), so the benchmark's own ceiling is about 0.81. 0.732 is
about 90 percent of that ceiling. **96 of 500 is D32's target-uniqueness count for the ceiling
calculation above, not the 8A.2 relabel's own count of rows it actually changed (99 of 130,
D42); the two measure different properties and are not interchangeable (8B correction).**

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
| macOS host, Metal, sustained session (Phase 5, thermal confound) | 6478 ms | 7220 ms | 7768 ms | superseded by the cold 5A figures; not citable as the system's number (D44, corrected from a prior mis-citation of D41) |
| Docker container, CPU only, arm64 VM (Phase 8 spot check, n=3, `backend=inprocess`) | 9612 ms (warm) | n/a | n/a | cold first call 165657 ms; confirms D16/D18's "tens of seconds to minutes" qualitatively, n too small for a real p50/p90; not the deployed path |
| Phase 8 e2e150 resolver latency (production, driven through the full ROS graph) | 7883 ms | 10373 ms | 12954 ms | `data/frozen/phase8_e2e150_loopback.jsonl`; **not a clean measurement** (D56): the model ablation's own `llama-server` was running concurrently on the same Metal GPU for most of this suite, so these numbers are inflated by GPU contention and should not be read as a second, independent confirmation of the p90 gate result. Relative comparisons within this table are unaffected. |
| macOS host, Metal, cold, isolated three-model remeasure (8B, `docs/results/model_ablation_latency_isolated.txt`) | 3579-4857 ms (per path) | 4087-5399 ms | 5698-12742 ms | phi3-mini traffic-weighted p90 4494 ms, a second GPU-isolated confirmation of the 5A figure (3737 ms); the 757 ms gap is session variance, not a methodology difference (open item, D63 finding 7, not explained further this phase). Both still miss the < 3000 ms gate. |
| Clean production ROS path (8B gate-off rerun, grammar on, isolated GPU, n=150, `data/frozen/e2e150_gate_off_8b.jsonl`) | 3797 ms | 5160 ms | n/a | the full `/semantic_goal` -> Nav2 -> resolver path, not a resolver-only benchmark; a third confirmation beside the 3737 ms (5A) and 4494 ms (8B isolated) cold figures above, this one through the real ROS graph. Previously measured but omitted from this table (D63 finding 6); its p90 exceeds the 5 s BT tick timeout default in the Review 2 table (PLAN.md 11B.0 finding 6). |
| Phase 8C e2e150 resolver latency, `text_anchor` on (diagnostic only, `data/frozen/e2e150_production_8c.jsonl`) | 3942 ms | 5540 ms | 7992 ms | +145/+380 ms beside the row above; the fix adds no tokens, so this is ordinary session variance, not contention (PLAN.md 11B.4) |

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

| model | n | top-1 (original) | top-1 (corrected, 8B) | top-3 | out-of-graph | p50 ms | p90 ms | llama-server RSS |
|---|---|---|---|---|---|---|---|---|
| phi3-mini-4k-instruct.Q4_K_M (production) | 500 | 0.650 | 0.726 | 0.763 | 0.0 | 5005 | 8329 | 3123 MB |
| tinyllama-1.1b-chat-v1.0.Q4_K_M | 500 | 0.402 | 0.530 | 0.686 | 0.0 | 1417 | 2749 | 717 MB |
| phi3.5-mini-instruct.Q4_K_M | 500 | 0.654 | 0.764 | 0.763 | 0.0 | 4427 | 7238 | 3010 MB |

**Top-3 denominator: 455** (resolvable rows under the original `synthetic_500.jsonl` labels
the `top_k_rooms` ranking was computed against; 45 adversarial rows excluded, stated here per
8B/D57 finding 8, previously unstated).

Phi3-mini's 0.650 top-1 here (original labels, cue-gated selection) is consistent with Phase
5A's own original-label figure of 0.646 for the same configuration, which cross-checks this
script against the Phase 5A result independently. Phi3.5-mini edges out phi3-mini by 0.4 points
on original labels, within noise at n=500 and far short of D36's "promote if more than 2 points
better" bar from Phase 5; phi3-mini remains production. TinyLlama trades about 25 points of
top-1 for roughly 3.5x lower latency and 4.3x lower RSS, consistent with its much smaller
parameter count, and confirms the capability gap motivating the Phi-3 family choice.

**Corrected by 8B.** Under the corrected `synthetic_500_v2.jsonl` labels, phi3.5-mini leads
phi3-mini by 3.8 points (0.764 vs. 0.726), which clears D36's 2-point promotion bar. This is a
measurement, not a decision: 11A.7 only measures, and no model swap is made in this pass. A
future phase choosing production models should use the corrected-label column, not the
original one, and should re-run session 2 calibration on the candidate before promoting it.

**Amended 2026-10-14 (Phase 8C, D63 finding 8).** The lead is significant on a paired exact
McNemar test (45 rows only phi3.5-mini gets right, 26 only phi3-mini, p = 0.032), but 12 of the
net 19 come from `multi_hop` (18 against 6), single run, and run-to-run variation of the same
model is about 0.6 points (phi3-mini's 0.726 here against 5A's 0.732). The top-3 column above is
still on original labels while top-1 is corrected; whether phi3.5-mini follows the anchor
contract (names the anchor, not the answer, in `room`) better than phi3-mini is untested. Given
`multi_hop`'s outsized share of the lead and this phase's finding that the anchor contract is
exactly where phi3-mini's spatial/multi_hop failures concentrate, that question should be
answered before any promotion decision.

Raw data: `data/frozen/model_ablation_<model>.jsonl`. Summary: `docs/results/model_ablation.json`,
`docs/results/model_ablation_corrected.txt`.

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

**Superseded by 8B, table kept for the record.** This table's gate-on vs. gate-off headline
(0.772 vs. 0.080 reached-intended) is withdrawn as a navigation artifact, not a gate effect
(D57); its spatial category's intended rooms were mislabelled for six of ten room keys; the
grammar-off and gate-off rows below are n=50, superseded by 8B's n=150 reruns.

| suite | n | success rate | gate pass rate | reached intended | false start rate | out of graph | e2e p50/p90/p99 ms | resolver p50/p90/p99 ms | nav start p50/p90 ms |
|---|---|---|---|---|---|---|---|---|---|
| production (grammar on, gate on, n=150) | 150 | 0.987 | 0.933 | 0.772 | 0.243 | 0 (0.000) | 9806/54620/76048 | 7883/10373/12954 | 7868/11110 |
| grammar off, gate on (n=50) | 50 | 1.000 | 0.960 | 0.800 | 0.208 | 0 (0.000) | 9199/55687/82704 | 8426/9496/44342 | 8785/10432 |
| gate off, threshold 0.0 (n=50) | 50 | 1.000 | 0.960 | 0.080 | **0.917** | 0 (0.000) | 25639/603918/1104027 | 3878/9611/12159 | 5971/10679 |

~~**The gate-on vs. gate-off comparison the specification asks for (Condition B vs. Condition C)
is the headline of this table.** With the gate at its deployed threshold, 77.2% of accepted
navigations actually reach the intended room (false start rate 24.3%). With the gate disabled,
that collapses to 8.0% reached (false start rate 91.7%): removing the gate does not just let a
few more wrong answers through, it makes "the robot moved somewhere" almost uncorrelated with
"the robot moved somewhere correct." This is the core safety claim in one number.~~ **Withdrawn
(D57):** 45 of the 50 gate-off rows ended off the map while `nav_result` read `succeeded`
(production trial 0 on the same 50 commands acted on 47 with 8 wrong; gate-off acted on 48 with
10 wrong; the suites agree almost everywhere). The 0.080 measured a diverging loopback
simulator, not the gate. See 8B below for the corrected comparison.

### 5.1 8B corrective reruns (PLAN.md 11A.2 and 11A.4 metrics)

Production rescored against the 11A.1 relabel rule (`data/frozen/e2e150_loopback_rescored.jsonl`);
gate-off and grammar-off rerun at the full 150 each on a fresh stack and a fresh, isolated host
`llama-server`, per 11A.4 (`data/frozen/e2e150_gate_off_8b.jsonl`,
`data/frozen/e2e150_grammar_off_8b.jsonl`). The reach/false-start conflation above is replaced by
separate numerators and denominators (11A.2): acted rate, wrong-room action rate, correct
abstention, resolver correct, and reach given a correct resolution (navigation-invalid rows
excluded, reported as a simulator health figure, not a task metric).

| suite | n | acted rate | wrong-room action rate (of n / of acted) | correct abstention | resolver correct | reach given correct (valid rows) | nav_invalid |
|---|---|---|---|---|---|---|---|
| production (grammar on, gate on, rescored) | 150 | 0.933 (140/150) | 0.173 (26/150) / 0.186 | 0.333 (1/3) | 0.767 (115/150) | 0.921 (105/114) | 1 (0.007) |
| grammar off (gate on, 8B rerun) | 150 | 0.960 (144/150) | 0.187 (28/150) / 0.194 | 0.000 (0/3) | 0.773 (116/150) | 1.000 (116/116) | 0 (0.000) |
| gate off, threshold 0.0 (8B rerun) | 150 | 0.960 (144/150) | 0.187 (28/150) / 0.194 | 0.000 (0/3) | 0.773 (116/150) | 1.000 (116/116) | 0 (0.000) |

Per-category wrong-room action rate:

| suite | direct | alias | negation | abbreviation | spatial |
|---|---|---|---|---|---|
| production (rescored) | 0.000 (0/30) | 0.000 (0/30) | 0.033 (1/30) | 0.000 (0/30) | 0.833 (25/30) |
| grammar off (8B) | 0.000 (0/30) | 0.000 (0/30) | 0.100 (3/30) | 0.000 (0/30) | 0.833 (25/30) |
| gate off (8B) | 0.000 (0/30) | 0.000 (0/30) | 0.100 (3/30) | 0.000 (0/30) | 0.833 (25/30) |

**The corrected Condition B versus C result: the gate makes no measurable difference on this
command set.** Wrong-room action rate is 0.173 with the gate on versus 0.187 with it off,
within sampling noise of each other. 148 of 150 rows resolve to the same room whether the
grammar is on or off. This is consistent with, and explains, finding 2 below: the wrong
answers the gate would need to catch are themselves calibrated at 0.90-0.95 confidence, above
the 0.85 threshold, so there is almost nothing in this command set for the gate to catch.
**Reported as measured, with no pass/fail threshold attached, per 11A.4's instruction that
whatever the comparison shows is the result.**

**Finding 2: the gate passes wrong rooms at high confidence on relational commands.** 26 of the
140 production commands that passed the gate went to a room other than the intended one, 25 of
them `spatial`, at calibrated confidence 0.90 to 0.95; against this, Phase 7's session 2 false
pass rate is 0.0426 (section 2). The offline comparison in `docs/results/offline_gate_comparison.md`
places this beside the two sets the gate was tuned against: on the corrected 500 benchmark the
gate-on wrong-room action rate is 0.056 (of n) vs. 0.268 off, and on session 2 it is 0.020 vs.
0.290, both showing the gate doing real work. e2e150's spatial commands are specifically the
case where it does not.

**Corrected 2026-10-14 (Phase 8C, D63 finding 3).** `offline_gate_comparison.py` counted a
`none` answer as acted-on at threshold 0.0 (e2e150's own `gate_passed` already requires a real
room, so this bug was local to that script). Gate-off wrong-room action rate corrects from
0.268 to **0.248** (500) and from 0.290 to **0.190** (session 2); gate-on figures (0.056, 0.020)
are unaffected. The "roughly a factor of 5" reduction below still holds with the corrected
figures (about 4.4x and 9.5x respectively).

**Finding 4: spatial resolution nearly fails on unambiguous commands.** Rescored against the
corrected labels, 2 of 30 production spatial rows are correct (1 of 30 under the original
inverted labels). Phase 5A's 0.615 `spatial` figure in section 1 came mostly from correct
abstention on rows relabelled to `none`; its original-label figure was 0.215.

**Superseded 2026-10-14 (Phase 8C, D63/D64).** Phase 8C found the cause: `_resolve_llm` was
hopping twice, because the v2 grammar's `room` field often holds the model's final answer, not
the anchor the template asks for; the model was correct before the second hop on 18 of 18 local
probe calls. The fix (`relations.apply_relational_hop`/`extract_text_anchor`, `text_anchor`
parameter) takes e2e150 spatial resolution to 30/30 and wrong-room gate-passed actions to 0/140
when forced on (`docs/results/e2e150_report_8c.md`); it shipped with its default off because of a
held-out regression elsewhere (`docs/results/text_anchor_replay.md`), **superseded by D65 (Phase
8D): under the 0.85 gate the regression disappears (exactly one of 800 held-out rows changes,
removing a wrong action), and the default now ships on, see section 5.3**. This also means
finding 2 above and the "no measurable difference" headline were a symptom of the double hop,
not an independent calibrator problem.

**11A.6 calibrator diagnostic** (`docs/results/calibrator_diagnostic_e2e150.txt`): wrong passes
have lower mean `raw_confidence` (0.904 vs. 0.955) and higher mean `token_entropy` and
`edit_distance` than correct passes, but all four features' ranges overlap substantially
(e.g. `raw_confidence` wrong max 0.95 equals correct min 0.90); the wrong spatial passes are
not cleanly separable on any single feature without retraining, which was not done. This is
evidence against relaxing the false-pass bound in 16A O2 to 0.15: the problem on this command
set is not a threshold that is too strict, it is that wrong answers already carry threshold-
clearing confidence.

**Superseded 2026-10-14 (Phase 8C, D63 finding 1).** This diagnostic's premise does not hold:
the wrong passes are not a confidence-separability problem at all. They are confident because
the model's own first answer (before the resolver's second, spurious hop) is usually correct;
the feature vector never saw the wrong intermediate step that broke it. 11A.6's conclusion
("evidence for 16A O1", withdrawn by D63) and the read against 16A O2's false-pass bound above
rest on the wrong cause and should not be relied on; see section 1's D64 note instead.

**The gate-off suite's e2e latency numbers are not a clean measurement of nominal drive time**
and should not be read as "the system is this slow without the gate." `data/frozen/
phase8_e2e150_gate_off.jsonl` shows 16 of 50 rows (32%) taking 60 s to over 20 minutes, and the
Nav2 log for that window (`/tmp/launch2.log`, not committed) shows long alternating `spin`/`backup`
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

**8B's gate-off and grammar-off reruns relaunched a fresh stack per suite (11A.3) and resolved
this**, confirming it was a measurement artifact: 0 of 150 rows in either 8B rerun are
`nav_invalid` (final pose outside the map bounds, read from the map YAML), and the gate-off
rerun's e2e p50/p90/p99 (4271/43232/53168 ms, `data/frozen/e2e150_gate_off_8b.jsonl`) no longer
shows the earlier run's multi-minute tail. An off-map guard (stop after three consecutive
invalid rows) is implemented in `scripts/run_trials.py` in case a future rerun diverges again.

### 5.2 Offline Condition B versus C, where the gate has something to catch (PLAN.md 11A.5)

No inference: the cached `phase5a_full500.jsonl` (features reconstructed through the deployed
calibrator) and `calibration_session2_trials.jsonl` (recalibrated the same way, since it was
collected with `calibrator_loaded=False`), re-gated at 0.85 vs. 0.0. Full table and per-category
breakdown: `docs/results/offline_gate_comparison.md`.

| set | gate on (0.85), wrong-room action rate | gate off (0.0), wrong-room action rate (superseded) | gate off (0.0), corrected (D63/D64) |
|---|---|---|---|
| Corrected 500 benchmark | 0.056 (28/500) | 0.268 (134/500) | **0.248 (124/500)** |
| Session 2 calibration trials | 0.020 (2/100), false pass 0.043 of acted (reproduces Phase 7's reported 0.0426) | 0.290 (29/100) | **0.190 (19/100)** |

**Corrected 2026-10-14 (Phase 8C, D63 finding 3).** The gate-off column counted a `none` answer
as acted-on; the rightmost column fixes it (`ml/safenav_ml/offline_gate_comparison.py`). Both
sets still show the gate reducing the wrong-room action rate (about 4.4x and 9.5x with the
corrected figures, "roughly a factor of 5" either way); e2e150 (section 5.1) does not, because
its wrong spatial passes already clear the threshold, per the double-hop finding above.

Raw data (Phase 8, superseded tables above): `data/frozen/phase8_e2e150_loopback.jsonl`,
`data/frozen/phase8_e2e150_grammar_off.jsonl`, `data/frozen/phase8_e2e150_gate_off.jsonl`.
8B reruns: `data/frozen/e2e150_gate_off_8b.jsonl`, `data/frozen/e2e150_grammar_off_8b.jsonl`,
`data/frozen/e2e150_loopback_rescored.jsonl`. Bags: `data/bags/e2e150_production/` (production
suite only; the two 50-row Phase 8 ablations and the two 8B reruns all used `--no-bag`, per
D56 and MANIFEST.md).

### 5.3 Phase 8C: the spatial anchor fix, before and after (PLAN.md 11B, D64)

**e2e150 (`text_anchor` forced on for this one run; superseded by D65, see below, `text_anchor`
is now the shipped default everywhere, so this is the shipped e2e150 measurement):**

| | spatial resolver correct | wrong-room gate-passed actions (of 140) |
|---|---|---|
| before (8B, production) | 2/30 | 26 |
| after (8C, this run) | **30/30** | **0** |

Full table: `docs/results/e2e150_report_8c.md`. Raw: `data/frozen/e2e150_production_8c.jsonl`.

**Offline Condition B versus C on this run, corrected by D65.** 8C reported 0.000 against 0.000
("the gate has nothing left to catch"); the gate-off figure was computed wrong (it reused the
gate-on acted count instead of re-gating at 0.0). Recomputed with `e2e_report.py --regate`
(PLAN.md 11C.3): gate on (0.85) acts on 140/150 with 0 wrong; gate off (0.0) acts on 143/150
with 3 wrong (`negation` rows resolving to `meeting_room_b` at 0.798, below the gate). The
corrected figure is **0.000 against 0.020**, not 0.000 against 0.000: the gate does catch
something on this run. Full detail: `docs/results/e2e150_report_8c.md`.

**Held-out replay, no inference re-run (`docs/results/text_anchor_replay.md`):**

| | corrected 500, raw top-1 | corrected 500, rows changed | session 2 false pass (0.85) |
|---|---|---|---|
| before | 0.732 | - | 0.043 |
| after | 0.730 | 15 (6 gained, 7 lost, 2 wrong-to-wrong) | 0.043 |

**Decision (PLAN.md 11B.5): `text_anchor` shipped `false`. Superseded by D65 (below).** Session
2 false pass cleared the bound (<= 0.05), but the corrected 500's raw top-1 fell (rows gained
minus lost = -1 < 0); every lost row is in `multi_hop`, where the fix's compound-sentence false
positives (e.g. "storage" matching `storage_room`'s alias inside an unrelated "tool storage"
phrase two clauses away from the actual anchor) outweigh its single-clause spatial gains. Not
tuned against this data per 11B.7.

Raw data: `data/frozen/text_anchor_replay_500.jsonl`, `data/frozen/text_anchor_replay_session1.jsonl`,
`data/frozen/text_anchor_replay_session2.jsonl`, `data/frozen/e2e150_production_8c.jsonl`.

#### D65 (Phase 8D): `text_anchor` ships on, gated evidence from committed code

11B.5's rule measured the corrected 500's raw top-1, uncapped. Production always runs behind
the 0.85 gate, and under the gate the picture is different. From the committed replay
(`ml/safenav_ml/replay_text_anchor.py`, extended for PLAN.md 11C.1,
`docs/results/text_anchor_replay_v2.md`), for every row the fix changes, gated at 0.85:

| held-out set | rows changed | changed rows acting at 0.85, before | after | net effect on actions |
|---|---|---|---|---|
| corrected 500 | 15 | 1 | 0 | 1 wrong action removed |
| session 1 | 15 | 0 | 0 | none |
| session 2 | 10 | 0 | 0 | none |

Across all 800 held-out rows the fix changes the gated system's behaviour on exactly one row
(`p0143`: a wrong `meeting_room_a` at 0.949 becomes an abstention). It adds no wrong action and
removes no correct one. All 7 `multi_hop` raw losses (11B.3) stay below the threshold either way
(0.256 to 0.753); before the fix they "passed" only because the model had anchored on an edgeless
sub location and abstained by accident, not because the old behaviour was actually right.
Against keeping the fix off: the double hop it replaces passes 25 wrong spatial rooms at 0.90 to
0.95 on e2e150 (section 5.1). **The project owner chose to ship `text_anchor` on after seeing
this gated evidence, reversing 11B.5's rule rather than following it; this is disclosed as a
decision made after the results, not as the frozen rule's own outcome.** `text_anchor: true` is
now the one value in `planner_params.yaml`, the `ResolverCore` constructor default and the
node's declared default (PLAN.md 11C.2). Raw data: `data/frozen/text_anchor_replay_500_v2.jsonl`,
`data/frozen/text_anchor_replay_session1_v2.jsonl`, `data/frozen/text_anchor_replay_session2_v2.jsonl`.

## 6. Specification evaluation metrics table (filled in)

| Specification metric | Measured | Source |
|---|---|---|
| Resolver top-3, corrected 500 benchmark | 0.868, against both >= 0.85 and the Review 2 table's 0.97 (D58) | section 1 |
| Out of graph rate, grammar on | 0% (structural) | section 1, section 5 |
| Out of graph rate, grammar off | 0/150 on the 8B rerun (section 5.1), 0/50 on the superseded Phase 8 ablation; 1.0% (5/500) on the Phase 4 full-500 study | section 5, D24 |
| Gated end-to-end accuracy | 0.72 (provisional, D53) | section 2 |
| Resolver latency p90 (deployed backend) | 3497-4272 ms cold (5A, isolated); 4494 ms cold (8B, isolated remeasure, a second confirmation); 7883-10373 ms under Phase 8's concurrent-GPU-load measurement (not citable against the gate, see section 3) | section 3 |
| 150-run e2e validation, grammar on | 0/150 out-of-graph outputs (required, met) | section 5 |
| Gate on vs. gate off, e2e150 wrong-room action rate | 0.173 (gate on, rescored) vs. 0.187 (gate off, 8B rerun): no measurable difference (8B, section 5.1). Supersedes the withdrawn 0.772 vs. 0.080 reached-intended figure (D57), which measured a diverging simulator. Phase 8C found the cause (a resolver double hop, not a calibrator problem) and fixed it; with the fix on (the shipped default as of D65), gate on drops to 0.000 and gate off to 0.020, corrected by D65 from the wrong 0.000 vs. 0.000 figure (section 5.3) |

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
- **Un-reset loopback session across the three e2e150 suites (D56), resolved by 8B.** Phase 8
  sent 250 real `NavigateToPose` goals to one continuous launch with no pose reset between
  suites; Nav2 recovery-behaviour loops inflated the e2e latency tails, most severely for
  gate-off, and the resulting 0.772 vs. 0.080 reached-intended figure was withdrawn as a
  simulator artifact (D57), not a measure of absolute drive time as this note originally said.
  8B relaunches a fresh stack per suite (11A.3) and adds an off-map guard; the reruns show 0
  navigation-invalid rows in either 150-row suite (section 5.1).
- **Model ablation latency measured under concurrent GPU load (D56), partially resolved by
  8B.** The Phase 8 model ablation table's `p50_ms`/`p90_ms` columns were collected under GPU
  contention; relative ordering between the three models is still meaningful, but absolute
  values should not be compared against Phase 3/5A's isolated cold-latency figures or the 3000
  ms gate. 8B adds an isolated remeasure of all three models (section 3); the model ablation's
  own `p50`/`p90` columns in section 4 are unchanged and still contention-affected.
- **Grammar-off and gate-off ablations ran at n=50, not n=150 (D56), resolved by 8B.** Both
  reran at the full 150 on an isolated GPU and a fresh stack (section 5.1).
- **Resolver top-3 target history undocumented until 8B (D58).** The gate was 0.97 (Review 2
  table, plan v1), then 0.88 (v2 redraft), then 0.85 (5A plan), with no deviation recorded for
  either change. Both 0.85 and 0.97 are now reported against the measured 0.868 in section 1.
- **e2e150 spatial category mislabelled for six of ten room keys until 8B (D57/D59).** The
  suite checked the wrong traversal direction for "room to the right/left of X" queries; the
  frozen correction and its rescore are in section 1 and section 5.1.
