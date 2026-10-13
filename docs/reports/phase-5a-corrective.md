# Phase 5A: corrective pass

## 1. What this phase built

- `ros2_ws/src/semantic_waypoint_planner/config/relational_cues.json`: the frozen cue list
  (8A.1), with its own pre-check numbers recorded inline.
- `semantic_waypoint_planner/relations.py`: `has_relational_cue()`, `load_cues()`.
- `semantic_waypoint_planner/grammar.py`: `build_grammar_v1()`, the literal pre-Phase-5
  single-field grammar, added back alongside `build_grammar()` (v2), not replacing it.
- `semantic_waypoint_planner/resolver_core.py`: `ResolverCore` now builds and caches both
  grammars per graph version and selects per request via `has_relational_cue()`. A cue-free
  command is forced to `relation: "none"` regardless of what the grammar or free-form text
  said, structurally suppressing the hop, not just discouraging it. New `cue_gating`
  constructor parameter (default `True`) and `ResolveResult.grammar_version`
  (`"v1" | "v2" | "fast_path"`).
- `scripts/llm_resolver.py`: new `cue_gating` node parameter, default `true`; the reasoning
  field now also carries `grammar_version` when it is not `v2`/`fast_path`.
- `ml/safenav_ml/cue_precheck.py`: reproduces the 8A.1 go/no-go numbers.
- `ml/safenav_ml/audit_edges.py`: `detect_anchors()` gained a label-blind mode
  (`expected=None`), reused by the relabel rule rather than duplicated.
- `ml/safenav_ml/relabel_benchmark.py`: the frozen, label-blind relabel rule (8A.2), committed
  before being run.
- `ml/safenav_ml/phase5a_analysis.py`: joins a benchmark run against both label sets and runs
  the section 5.1 regression check.
- `ml/safenav_ml/cold_latency_remeasure.py`: isolated v1/v2 latency with real server timings.
- `data/benchmark/synthetic_500_v2.jsonl`, `data/benchmark/RELABEL.md` (new).
  `data/benchmark/synthetic_500.jsonl` is untouched (confirmed with `git diff`, section 4).

## 2. Cue gating (8A.1)

**Pre-check, run before any cue-gating code existed.** The cue list was derived by reading
every `spatial`/`multi_hop` command in `synthetic_500.jsonl` (130 rows) and extracting the
phrases that actually appear, not from intuition (full counts in the commit that froze
`relational_cues.json`). 15 cues survived: `next to`, `beside`, `left of`, `right of`, `near`,
`adjacent`, `with the`, `that has`, `closest to`, `on its left`, `on its right`, `on the
left`, `on the right`, `other side`, `opposite`.

| | measured | gate |
|---|---|---|
| Recall on spatial + multi_hop (128/130) | 0.9846 | >= 0.85 |
| False positive rate on direct/alias/negation/abbreviation (4/260) | 0.0154 | near zero |

**Verdict: pass, decisively.** The list and these numbers were committed
(`ros2_ws/.../config/relational_cues.json`) before `has_relational_cue()` or any grammar
selection code was written. The four false positives are all in `negation` and, read
individually, are arguably mislabelled themselves ("adjacent one where we have the
projector", "the one next to it" are genuinely relational phrasing under a `negation`
category tag) rather than failures of the cue list; this is noted, not acted on, since the
rule in section 8A.4 is not to tune after seeing results.

**Mechanism**: a cue-free command is resolved against `build_grammar_v1()` (`{"room",
"confidence"}`, no `relation` field, structurally smaller alternation) with the hop forced
off; a cued command takes `build_grammar_v2()` exactly as Phase 5 built it. Both grammars are
built once per `set_graph()` call and cached (`ResolverCore._grammar_str_v1` /
`_grammar_str`). Unit tests (`test_resolver_core_offline.py`) prove this with a fake backend
that records which grammar string it was handed: a cue-free command gets
`core.grammar_str_v1`, a cued command gets `core.grammar_str`, and the result's
`grammar_version` and `relation` fields match.

## 3. Regression check: did it fix what section 5.1 found?

Phase 5's section 5.1 identified 68 of 500 rows where the model's anchor exactly matched the
expected answer but a spurious non-`none` relation overwrote it with the wrong final room.
Matched by command text against this phase's full-500 run
(`data/runs/phase5a_full500.jsonl`):

- **68/68** matched (every row from the original list is present in this run).
- **49/68 (72 percent) now answered correctly** against the original labels.
- **49/68 took the v1 grammar** this time, i.e. the hop was structurally suppressed for
  exactly the rows that recovered. The remaining 19/68 contain a frozen cue (most often
  `near`, `with the`, or `adjacent`, used in a non-relational sense by the generator, e.g.
  "I need to charge my battery, go to the charger" style phrasing that happens to contain a
  cue substring) and still take v2; a few of those are now wrong for a different reason than
  the one section 5.1 diagnosed. This is the honest residual: cue gating recovers the large
  majority of the spurious-hop regression, not all of it, because the cue list is lexical and
  the generator's phrasing is not perfectly separable from it.

## 4. Benchmark re-audit (8A.2)

The frozen rule (verbatim in `data/benchmark/RELABEL.md`): for every `spatial`/`multi_hop`
row, find every anchor the command text plausibly names (label-blind: the rule never sees the
row's own `expected` value), apply every relation keyword the text contains, and collect the
set of distinct targets `relations.py`'s own traversal reaches from any (anchor, relation)
pair. Exactly one target keeps the label; zero or more than one relabels `expected` to
`"none"`. This reuses `audit_edges.detect_anchors`/`detect_relations`, the same functions the
Phase 5 D32 ceiling check used, rather than a second implementation that could disagree with
it.

| category | relabelled to none | total |
|---|---|---|
| spatial | 45 | 65 |
| multi_hop | 54 | 65 |
| **total** | **99** | **130** |

This is close to, but not identical to, D32's "96 of 500 structurally unanswerable" figure,
because the two checks ask different questions: D32 tested whether the *original* label was
among the reachable targets (a recall-style check against a known answer), while this rule
tests whether there is a *unique* target at all regardless of which one the original label
picked. A row can have its original label among several reachable targets (D32 calls it
servable) while this rule still calls it ambiguous (more than one target survives). Both
numbers point the same direction and neither was adjusted to match the other.

Ten worked examples are in `data/benchmark/RELABEL.md`; one is reproduced here. `p0132`,
"Take me to the space that's next to the boardroom on the other side," original label
`office`: the anchor-detection step matches both `meeting_room_a` and `meeting_room_b` (both
have "boardroom" in an alias, `boardroom a` / `boardroom b`), and the default relation
(`adjacent`, no explicit keyword in this sentence) reaches `{kitchen, meeting_room_a,
meeting_room_b, office}` across the two candidate anchors. Four surviving targets, relabelled
to `none`. This is the rule working as specified, not a defect: "boardroom" alone really does
not distinguish which boardroom without the "on the other side" clause, which this
label-blind, keyword-level rule has no way to use.

**Self-adjudication exposure, stated plainly.** This relabel was designed after seeing Phase
5's results, by the same session that produced them, which is the same self-adjudication
pattern D25 recorded for the Phase 4 dataset review. The defences, for a reader to judge
rather than take on trust: the rule is graph-derived and never reads a model prediction or the
row's own original label when choosing anchors; it was written and committed to git before it
was run, so its logic cannot have been shaped by this run's numbers; it ran over all 130 rows
without exception or hand-adjustment, and its output (99/130, including some individually
debatable calls like the `p0132` example above) was kept as computed; both label sets are
reported in every table in this phase and the original file is untouched and in git history.
A Review 2 panel reaching for the uncharitable reading first is reasonable, and the honest
answer is that this correction being self-designed is a real weakness of the process, not
fully resolved by any of these defences, only mitigated by them.

## 5. Headline accuracy (full 500, cue gating on, both label sets)

Production configuration unchanged (`phi3-mini-4k-instruct.Q4_K_M`, `fewshot_count=0`,
`temperature=0.3`, grammar on, `backend=http`). `data/runs/phase5a_full500.jsonl`.
Grammar split: 350/500 rows took v1 (no cue), 150/500 took v2 (cued) -- a 30 percent v2 rate
on the full set, close to the 31 percent cue rate measured independently on the held-out slice
(section 6), which is a useful internal consistency check on the cue list.

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

**The four categories Phase 5's section 5.1 regression hit are recovered, and then some**:
`direct` 0.877 -> 0.969, `alias` 0.769 -> 0.954, `negation` 0.692 -> 0.877, `abbreviation`
0.800 -> 0.877. All four clear the 0.85 no-regression floor from Phase 5's own DoD (`direct`
and `alias` are now at or above their Phase 4 ceiling, since the v1 grammar path is, by
construction, identical to Phase 4's). `negation`/`abbreviation` land a few points under their
Phase 4 values (0.877 vs 0.969/0.862); a handful of rows in these categories carry a frozen
cue and still take v2, same residual as section 3.

**`spatial` and `multi_hop` only look recovered against the corrected labels**, which is
expected and not circular: a row relabelled to `"none"` because the graph itself cannot
answer it uniquely is counted correct exactly when the resolver abstains, which cue gating and
the v2 hop's own abstention policy make much more likely now that fewer non-relational rows
are forced through the hop machinery at all. `spatial` 0.215 -> 0.615 and `multi_hop` 0.046 ->
0.308 under the corrected labels; against the *original* labels both actually look slightly
worse than Phase 5 (0.246 -> 0.215, 0.062 -> 0.046), because cue gating does nothing to help a
row that needs the hop and was always going to need it; it only stops the hop firing where it
should not.

**Full 500, corrected labels: top-1 0.732, top-3 0.868.** Below the >= 0.76 gate this phase
restates (D37), above the 0.70 stop floor. Per the stop rule and section 8A.4's scope
discipline, this is reported as a documented shortfall and **no further prompt or grammar
iteration was attempted.**

## 6. Cold latency re-measure (8A.3)

Fresh `llama-server` (phi3-mini-4k Q4_K_M, Metal, `--parallel 1`), started immediately before
measuring, nothing else contending for the GPU (`ps aux` checked clean beforehand), 50 calls
per grammar path over the held-out 100 slice, `requests` against `/completion` directly so the
server's own `timings.predicted_per_token_ms` is used rather than a text-length guess (an
earlier version of this script used `len(text) // 4` as a token-count proxy and produced a
backwards-looking result; fixed and rerun from a second fresh server start, see D43).

| path | n | p50 | p90 | p99 | predicted_per_token_ms |
|---|---|---|---|---|---|
| v1 grammar | 50 | 3026 ms | 3497 ms | 9448 ms | 137.7 |
| v2 grammar | 50 | 3939 ms | 4272 ms | 5057 ms | 139.7 |

Measured cue rate on the held-out slice: 0.31 (31 of 100). Traffic-weighted p90 (blending the
v1 and v2 p90 by that rate): **3737 ms.**

**Verdict: Phase 5's 7220 ms was partly, not purely, a thermal artifact.** The cold, isolated
number is roughly half of Phase 5's sustained-session figure, so the thermal/sustained-load
confound section 6 of the Phase 5 report flagged was real and should be read as having
inflated that number substantially. But the cold baseline **still does not clear 3000 ms**
(3737 ms traffic-weighted, 3497 ms even on the smaller v1 grammar alone), so the gate miss is
not fully explained away and must still be carried forward as a real finding, not dismissed.

**The grammar-size hypothesis from Phase 5 section 6 is refuted by this measurement.**
`predicted_per_token_ms` is essentially identical between the v1 and v2 grammar paths (137.7
vs 139.7, a 1.5 percent difference, well within call-to-call noise) when measured from the
server's own timings rather than approximated. Phase 5's 228 ms/token vs ~40 ms/token
comparison was informal (one ad hoc call each, mid-session, not controlled for the confound
this section exists to remove) and does not replicate here. The real source of v2's higher
total latency is that it generates more output tokens (the `relation` field adds JSON
characters to decode), not that each token costs more to sample under the larger grammar's
alternation. Cue gating's latency benefit is therefore real (most traffic now takes the
shorter v1 output) but smaller than Phase 5 attributed to it, and the mechanism is "fewer
output tokens on the common path," not "a cheaper per-token grammar."

The v1 path's p99 (9448 ms) is a single first-call outlier consistent with genuine model/Metal
warm-up on a server that has served zero prior requests (the v1 batch ran first against each
fresh server); it is reported as observed rather than excluded, since excluding it would be
exactly the kind of after-the-fact adjustment this phase is trying not to do elsewhere.

## 7. Stop rule and gate

Full 500, corrected labels, top-1 = **0.732**. The stop rule triggers below 0.70; this phase
is above it, so per PLAN.md section 8A: **do not iterate further, report, and move to Phase
6** with the 0.732 vs 0.76 shortfall and the 3737 ms vs 3000 ms latency shortfall both carried
into Phase 8 as documented limitations. No fourth prompt-template iteration, no new model
download, and the backend seam/grammar correctness/traversal correctness were not touched
(8A.4); only the cue-gating selection layer and the benchmark labels changed.

## 8. Deviations recorded this phase (D40 onward; D32-D36 Phase 5, D37-D39 the replan)

- **D40: cue gating recovers most but not all of Phase 5's section 5.1 regression.** 49/68
  (72 percent) of the correct-anchor-overwritten rows are now answered correctly; the
  remaining 19/68 contain a frozen cue phrase used non-relationally by the generator and still
  take the v2 grammar. The cue list was not retuned in response to this (8A.1's rule), so this
  residual is reported rather than closed.
- **D41: `audit_edges.detect_anchors` gained a label-blind mode** (`expected=None`) so the
  8A.2 relabel rule could reuse it rather than duplicate it; the Phase 5 ceiling check's own
  call site (which still needs to exclude the known-correct label) is unaffected.
- **D42: the benchmark relabel (D39) produces 99/130 relabelled rows, not the 96/500 D32
  reported.** Both numbers are legitimate and measure different things (recall of a known
  label among reachable targets, vs. overall target uniqueness); see section 4. Neither was
  adjusted to match the other.
- **D43: the first cold-latency measurement used a text-length proxy for token count and
  produced a result suggesting v1 was slower per-token than v2**, which is backwards from
  Phase 5's hypothesis and from this fixed measurement. Caught before being written into this
  report; the script was corrected to read the server's own `timings.predicted_per_token_ms`
  and rerun from a second fresh server start (section 6).
- **D44: Phase 5's section 6 grammar-size latency hypothesis is not confirmed and is
  superseded.** Cold, controlled, per-token decode cost is statistically indistinguishable
  between the v1 and v2 grammars (section 6). The latency gate miss persists (3737 ms
  traffic-weighted p90 cold vs the 3000 ms gate) but is attributed to output token count, not
  per-token grammar cost, and to a real (if partial) thermal confound in Phase 5's number.

## 9. DoD

- [x] Cue list frozen in a committed file before any measurement; recall 0.9846 >= 0.85 gate,
      false positive rate 0.0154 on the four easy categories.
- [x] Two-path grammar selection implemented; unit tests prove a cue-free command takes v1 and
      a cued command takes v2 (`test_resolver_core_offline.py`).
- [x] Regression check: 49/68 of the section 5.1 rows now answered correctly (section 3).
- [x] Relabel rule frozen and committed before running; `synthetic_500_v2.jsonl` and
      `RELABEL.md` produced; `synthetic_500.jsonl` unmodified (`git diff` empty, section 1).
- [ ] Full 500 on corrected labels: top-1 >= 0.76 (actual 0.732), top-3 >= 0.85 (actual
      0.868, met), out of graph 0.0 (met).
- [x] Full 500 on original labels reported in the same table (section 5).
- [x] Per-category table against both label sets, with Phase 4 and Phase 5 columns alongside
      (section 5).
- [x] Cold latency re-measure: v1 path, v2 path, traffic-weighted p90, each with per-token
      decode cost; verdict that Phase 5's 7220 ms was partly, not purely, thermal (section 6).
- [x] Self-adjudication exposure paragraph present (section 4).
- [x] Report written.

Gate: top-1 >= 0.76 on corrected labels, or a documented stop per the 0.70 floor. **0.732 is
below 0.76 and above 0.70**: reported as a documented shortfall, not a stop, per section 7.
