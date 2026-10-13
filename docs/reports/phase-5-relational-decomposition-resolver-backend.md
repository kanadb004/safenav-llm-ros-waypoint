# Phase 5: relational decomposition and resolver backend

## 1. What this phase built

- `semantic_waypoint_planner/relations.py` (new): `resolve_relation(graph, anchor, relation,
  command)`, the deterministic hop that replaces model-side spatial traversal (D29).
- `semantic_waypoint_planner/graph.py`: `related_rooms(name, relation)`, which materializes
  symmetric (`adjacent`, `near`) and inverse (`left_of`/`right_of`) edges at load time so the
  file only needs to author one directional fact per pair.
- `semantic_waypoint_planner/grammar.py`: GBNF v2. `root` now emits `room`, `relation`,
  `confidence` in that order; `relation-value` is closed to `none | left_of | right_of |
  adjacent | near | within`.
- `semantic_waypoint_planner/backends.py` (new): `Backend`, `InProcessBackend`
  (llama-cpp-python), `HttpBackend` (`llama-server` over HTTP), `build_backend()`. Same GBNF
  string goes to either one.
- `semantic_waypoint_planner/resolver_core.py`: `ResolverCore` now talks to a `Backend`
  instead of `llama_cpp` directly; `resolve()` applies the hop after parsing and before
  returning, so `ResolveResult.room` is always the single final answer and `anchor_room`,
  `relation`, `n_relation_targets` record the pre-hop state.
- `scripts/llm_resolver.py`: new `backend`/`backend_url` parameters; the phase 5 hop fields
  ride in the existing `reasoning` string field as JSON (`ResolveWaypoint.srv`, section 12.2,
  is frozen and was not touched); a backend exception no longer crashes the node (see D33).
- `config/prompts/system_template.txt` (now version 4) and `config/prompts/fewshot.jsonl`:
  document the two-field contract with three short worked examples (none, left_of, within).
- `maps/room_annotations.json`: added the `left_of` edges missing for same-row adjacent pairs
  (section 2).
- `docs/hardware/llama-server.md`: building `llama-server` with Metal on the host and CUDA
  flags for Jetson; the `host.docker.internal` route verified from inside the running
  container.
- `ml/safenav_ml/audit_edges.py`, `run_phase5_benchmark.py`, `backend_parity.py` (new tooling
  for this phase's measurements).
- `docker/requirements.txt`: added `requests` (D33).

## 2. Edge coverage audit (section 8.1, done first)

`ml/safenav_ml/audit_edges.py` checks every `spatial`/`multi_hop` benchmark row against the
graph directly: it looks for a room name/alias/tag word overlap in the command text (an
"anchor candidate") and a relation keyword, then asks whether `related_rooms`/`parent` already
reaches the row's expected answer. This isolates the graph from the model.

| relation | edges before | edges after | lexical rows served (of 130 hard-subset rows) |
|---|---|---|---|
| `left_of` | 2 | 7 | 6/12 |
| `right_of` | 1 (materializes to 7 after the `left_of` fix) | 2 | 6/16 |
| `adjacent` | 8 | 8 | 55/103 |
| `near` | 5 | 5 | 1/13 |
| `within` | (parent field, 0 explicit edges) | unchanged | 13/50 |

Fix applied: `left_of` existed for only one pair (`charging_dock`/`storage_room`) plus one
`right_of` fact (`kitchen`/`reception`). Every other same-row adjacent pair (the two hallways
at `y=6` and `y=-6`) was missing its `left_of` fact entirely, so `left_of`/`right_of` were
unanswerable for most of the layout. Added the six missing `left_of` edges (geometric: lower
`x` is `left_of` higher `x`, matching the file's own existing convention); `right_of` comes
free from `graph.py`'s inverse materialization, so no `right_of` edges needed adding.
`parent` values were already correct for every sub-location (coffee_machine -> kitchen,
tool_cabinet -> workshop, etc.), so `within` needed no data fix.

**The graph is not the primary limiter, but the graph's topology combined with the specified
disambiguation policy is.** A second check (`resolve_relation` run directly against every
lexically-detected `(anchor, relation)` pair on the 130 hard-subset rows, i.e. "if the model
always picked a textually-plausible anchor and relation, what is the best case") finds only
**34/130 (26 percent)** of hard-subset rows are structurally resolvable at all. The reason:
most rooms in this facility have two or more `adjacent`/`near` neighbors (it is a hallway, not
a tree), and section 8.1's specified policy ("disambiguate by alias and tag overlap with the
normalized command; if still tied, abstain") has no signal to work with when the command says
only "the room next to the kitchen" and never mentions either neighbor's alias or tag. This is
exactly the scenario section 8.1 names explicitly: *"If the graph turns out to be the limiting
factor rather than the model, say so plainly, because that changes the conclusion of the whole
phase."* It does, and it is said plainly in section 5 below.

A direction bug was caught and fixed during this audit, before any benchmark run: an edge
`(A, B, left_of)` means "A is left_of B" (12.7's own convention), so "the room left of the
anchor" must be answered by the anchor's **inverse** relation (`right_of`), not its own
`left_of` edges. `relations.py` and the audit script both apply this flip; `test_relations.py`
checks it against the natural-language meaning directly (`test_left_of_means_target_is_left_of_anchor`),
not just against whatever the implementation returns.

## 3. Engineering DoD items (all met)

- **GBNF v2**: `test_grammar.py` extends the Phase 3 suite; every canonical name and every
  relation value is present, every out-of-set value (room or relation) is absent, the grammar
  compiles, and `relation` is ordered between `room` and `confidence`.
- **relations.py hop matrix**: `test_relations.py`, 12 cases covering every relation on the
  shipped map plus a synthetic two-target tie graph: single target, zero targets (abstain),
  materialized `left_of`/`right_of` inversion, `within` with and without a parent, tied targets
  broken by alias overlap, by tag overlap, and still-tied abstention.
- **Backend parity**: 100 benchmark commands, `inprocess` vs `http`, same model
  (`phi3-mini-4k-instruct.Q4_K_M`), temperature 0: **100/100 agreement (100 percent)**, well
  above the 99 percent gate. `data/runs/phase5_backend_parity.jsonl`.
- **`host.docker.internal` route**: verified from inside the running container (not assumed):
  `getent hosts host.docker.internal` resolves, and `curl .../health` through it returns 200
  against a `llama-server` running on the macOS host. See `docs/hardware/llama-server.md`.
- **`semantic_cli` relation/anchor_room visibility**: confirmed. `ResolveWaypoint.srv` (12.2)
  is frozen, so these ride in the existing `reasoning` field as JSON:

  ```
  $ ros2 run semantic_waypoint_planner semantic_cli "the room to the left of the kitchen"
  {
    "matched_room_name": "kitchen",
    "reasoning": "{\"anchor_room\": \"meeting_room_a\", \"relation\": \"left_of\", \"n_relation_targets\": 1}",
    ...
  }
  ```

  The mechanism works exactly as designed (anchor and relation are visible, the hop is
  applied, `matched_room_name` is the single final room). The *answer* for this specific
  example is wrong (the model named `meeting_room_a` as the anchor instead of `kitchen`),
  which is the accuracy problem documented in section 5, not a wiring defect; the DoD item is
  about the field being visible and the hop being applied, and it is.

## 4. Headline numbers (production configuration: `phi3-mini-4k-instruct.Q4_K_M`, `fewshot_count=0`,
`temperature=0.3`, grammar on, `backend=http` against the host Metal `llama-server`)

Implementation frozen before this section's runs (section 8.4); none of these numbers fed back
into another prompt or grammar change.

| Set | n | top-1 | top-3 | out-of-graph |
|---|---|---|---|---|
| Full 500 (`data/runs/phase5_full500.jsonl`) | 500 | **0.560** | 0.754 | 0.0 |
| Held-out 100 slice, deterministic every-5th row (`phase5_heldout100.jsonl`) | 100 | 0.570 | 0.824 | 0.0 |
| `adversarial_50.jsonl`, untouched since Phase 4 (`phase5_adversarial50.jsonl`) | 50 | 0.580 | n/a | 0.0 |

The held-out slice (0.570) and `adversarial_50` (0.580) both land within a couple of points of
the full-500 headline (0.560), which is the honesty check section 8.4 asks for: this is not an
artifact of the full run including rows the implementation was tuned against, because nothing
in this phase was tuned against the full 500, the held-out slice, or `adversarial_50` at all
(development used only the `spatial`+`multi_hop` hard subset, see section 5).

Per-category top-1, full 500:

| category | Phase 4 (v1, single field) | Phase 5 (v2, relational) | delta |
|---|---|---|---|
| direct | 0.923 | 0.877 | -0.046 |
| alias | 0.954 | 0.769 | -0.185 |
| negation | 0.969 | 0.692 | -0.277 |
| abbreviation | 0.862 | 0.800 | -0.062 |
| functional | 0.692 | 0.477 | -0.215 |
| adversarial | 0.400 | 0.556 | **+0.156** |
| spatial | 0.262 | 0.246 | -0.016 |
| multi_hop | 0.154 | 0.062 | -0.092 |

**Gate: not met.** Full-500 top-1 is 0.560, below the 0.74 floor section 8 sets for "stop,
report the error analysis, do not start a fourth prompt iteration" (0.560 is also below the
0.74-0.80 band that would have allowed a documented-shortfall merge). Per category floors
(`spatial >= 0.80`, `multi_hop >= 0.65`, `functional >= 0.75`, no regression below 0.85 on
`direct`/`alias`/`negation`/`abbreviation`) are not met by any of the seven categories they
name. Per section 8's own instructions for this outcome, no further prompt iteration was
attempted; section 5 is the required error analysis.

## 5. Error analysis: why the decomposition made things worse, not better

This is the central finding of the phase, and it reverses the premise of D29.

D29's hypothesis, from the Phase 4 finding that the model "was not reliably using the spatial
relationships block of the prompt," was that moving traversal into code would recover accuracy
on `spatial`/`multi_hop` while leaving the easy categories (`direct`/`alias`/`negation`/
`abbreviation`) untouched, since those should resolve with `relation: "none"` exactly as
before. Neither half of that held.

**5.1 The easy categories regressed because the model over-applies `relation`.** Across the
full 500, 202/500 rows got a non-`none` relation from the model, including 7/65 `direct`,
12/65 `alias`, 18/65 `negation`, and 6/65 `abbreviation` rows that should never need a hop at
all. Of the 68 rows (any category) where the model's **anchor matched the expected answer
exactly** but the final prediction did not, every single one is a case where the model
assigned a non-`none` relation to a command that should have gotten `none`, and the hop then
overwrote an already-correct answer with the wrong one. That is 68 of 500 rows (13.6 points)
of pure, avoidable regression, concentrated in exactly the categories the design assumed would
be unaffected: 39 of the 56 total failures (70 percent) in `direct`/`alias`/`negation`/
`abbreviation` are this failure mode. The clearest pattern is sub-locations: naming
`kitchen_sink`, `tool_cabinet`, `whiteboard`, or `office_desk_1` directly (a correct, specific
answer under v1) now frequently gets `relation: within` attached, which sends the answer up to
the parent room (`kitchen`, `workshop`, `meeting_room_a`, `office`) instead. The `within`
worked example in the system template ("the room with the coffee machine" -> `coffee_machine`,
`within`) teaches exactly the pattern the model over-generalizes: any mention of a named
sub-location, even as the intended destination itself, now looks like grounds for `within`.

**5.2 The hard categories did not improve because the graph's topology, not the model, is the
binding constraint for most of them.** Section 2's ceiling check found only 26 percent of
`spatial`/`multi_hop` rows are structurally answerable even with perfect anchor and relation
selection, because most anchors have multiple `adjacent`/`near` neighbors and the command text
usually gives no alias/tag cue to disambiguate between them (the dataset's phrasing style
mostly does not mention the target room's own name or aliases when describing it
relationally, by design, since that is the whole point of a relational question). The
resolver, following section 8.1's specified policy exactly, abstains rather than guesses in
this situation. 71 resolvable rows abstained in total; 30 were multi-target ties and 41 were
zero-target hops (a wrong anchor choice with no valid hop at all); zero rows abstained by the
model directly answering `"none"` without attempting a hop, confirming the model essentially
never volunteers `"none"` on its own (consistent with Phase 4's finding on `adversarial`).

**5.3 `adversarial` is the one category that improved** (0.400 -> 0.556), because many
adversarial commands now trigger a hop that finds zero or ambiguous targets, which is a
legitimate way to land on `"none"` even though the model is not directly recognizing the
command as out-of-scope. `false_accept_rate` on `adversarial_50` is still 0.444 and
`false_abstain_rate` on resolvable rows is 0.156 (`abstain_precision` 0.260, `abstain_recall`
0.556): the gate is still doing real work here, just not reliably, which is exactly what Phase
7's calibrator is for.

**Conclusion.** The relational decomposition does not, on this evidence, isolate anchor
extraction from traversal as cleanly as D29 assumed. The model's errors are not confined to
*which* relation or anchor it names on genuinely relational commands (section 5.2); it also
makes a new kind of error -- naming a relation when none was asked for -- on commands the v1
architecture already handled well (section 5.1). Both are capability-ceiling findings about
Phi-3-mini-4k Q4_K_M's grasp of this two-field contract, not implementation defects: the
grammar, traversal, and backend code are all verified correct independently (sections 2-3), and
backend parity is 100 percent, so the wrong answers are what the model actually decided, not an
artifact of how that decision was executed. Per section 8's explicit instruction for a result
this far under 0.74, no further prompt iteration was attempted.

## 6. Latency

A dedicated, isolated 100-call measurement (held-out slice, nothing else contending for the
Metal GPU) against the host `llama-server`:

| | p50 | p90 | p99 |
|---|---|---|---|
| Metal `llama-server`, `backend=http` | 6478 ms | 7220 ms | 7768 ms |

**Gate not met**: p90 < 3000 ms. This is roughly double Phase 3's measured v1 number (p50 2874
ms, p90 3678 ms, section 13). Root cause, confirmed directly against the server's own
`timings`: prompt evaluation is fast and fully cached (`cache_n` ~1215-1218 of ~1218 prompt
tokens, `prompt_ms` 100-550 ms) exactly as section 13 requires, so the regression is entirely
in **decode**: `predicted_per_token_ms` was measured at ~228 ms per token against the v2
grammar versus ~40 ms per token on an unconstrained or simpler-grammar completion in the same
session. Grammar-constrained decoding is already documented as expensive for this stack
(`resolver_core.py`'s own docstring on candidate scoring, and Phase 4 section 4.3's grammar-off
latency variance); v2's grammar is larger (adds the 6-value `relation` field's alternation on
top of the ~30-value `room` field), which increases the per-step branching the sampler must
check. A secondary, honestly-disclosed confound: these numbers come after roughly 45 minutes
of sustained back-to-back Metal inference in this session (five benchmark runs in a row), and
an isolated single-call spot check taken mid-session measured ~950 ms-1000 ms per completion
at the same grammar and model, well under the gate; thermal throttling on the macOS host over
a long session is a plausible partial contributor and this measurement should be re-taken from
a cold start before being treated as the final hardware-readiness number in Phase 9.
Container CPU-only (`backend=inprocess` inside the Docker image) was not separately
re-measured this phase; Phase 3/4 established it at tens of seconds to minutes per call
(D16/D18), consistent with section 13's existing table, and nothing in this phase changes that
backend's code path.

## 7. Model check

Run on the held-out 100 slice rather than the full 500: at ~6-7 s/call under the v2 grammar
(section 6), a full-500 run is roughly 100 minutes per model, and the held-out slice was
already shown (section 4) to track the full-500 number within a couple of points for Phi-3
mini, so it is used here as a faster, still-representative comparison. Recorded as a
deviation (D36) rather than silently substituted.

| model | top-1 (held-out 100) | top-3 | notes |
|---|---|---|---|
| `phi3-mini-4k-instruct.Q4_K_M` (production) | 0.570 | 0.824 | `data/runs/phase5_heldout100.jsonl` |
| `phi3.5-mini-instruct.Q4_K_M` | 0.500 | 0.791 | `data/runs/phase5_heldout100_phi35.jsonl` |

Per-category (held-out 100), Phi-3 mini vs Phi-3.5 mini: direct 1.00/0.77, alias 0.77/0.54,
negation 0.77/0.85, abbreviation 1.00/0.85, functional 0.54/0.62, spatial 0.08/0.15, multi_hop
0.00/0.00, adversarial 0.33/0.11.

**Production model: `phi3-mini-4k-instruct.Q4_K_M`, unchanged.** Phi-3.5 mini is 7 points
*worse* overall (0.500 vs 0.570), not better by the 2-point margin section 8.3 requires for
promotion; it trades a few points on `negation`/`spatial`/`functional` for a larger loss on
`alias`, `direct`, and `adversarial`. Neither model clears the phase's accuracy gates, so this
is a negative result, not a close call the extra full-500 compute would be likely to reverse.

## 8. Measurement honesty (section 8.4)

- Development (grammar, `relations.py`, the template's worked examples, the edge audit and
  fix) used only the `spatial`+`multi_hop` hard subset and ad hoc smoke-test commands, scored
  by inspection and by the graph-only ceiling check (section 2), never by running the full 500
  or `adversarial_50` and iterating on the score.
- The implementation (template version 4, grammar v2, `relations.py`, edge fixes) was frozen
  before any of section 4's runs. No change was made in response to the full-500, held-out, or
  adversarial numbers; section 5's error analysis was written from the frozen run's own
  records (`data/runs/phase5_full500.jsonl`), not used to trigger another iteration.
- `adversarial_50.jsonl` was not opened or read during development, only during the frozen run.
- The held-out 100 slice (`all_500[4::5]`, deterministic, documented in
  `run_phase5_benchmark.py`) and `adversarial_50` both score within 2 points of the full-500
  headline (section 4), which is the cross-check this section exists to report.

## 9. Deviations recorded this phase

- **D32**: `relations.py`'s disambiguation (alias/tag keyword overlap, abstain on a tie) is
  implemented exactly as section 8.1 specifies, and found to resolve only 26 percent of the
  `spatial`/`multi_hop` hard subset even under a best-case anchor/relation choice (section 2).
  The graph's topology (most rooms have 2+ `adjacent`/`near` neighbors) combined with this
  policy, not missing edges, is the binding constraint for this category; recorded per section
  8.1's own instruction to say so plainly if this turned out to be the case.
- **D33**: the Docker image had no `requests` package, so `HttpBackend` could not construct
  inside the container at all; this was only caught by actually launching the resolver node in
  the container with `backend:=http` (section 3), not by unit tests (which run on the host).
  Added `requests` to `docker/requirements.txt` and rebuilt the image. Separately, a concurrent
  `llama-server` request (this phase's own benchmark script running at the same time as the
  manual `semantic_cli` check) produced a context-overflow 500 error that crashed the whole
  `llm_resolver_node_py` process, since only `concurrent.futures.TimeoutError` was caught in
  `_on_resolve`. Any backend exception is now caught there the same way a timeout is
  (`scripts/llm_resolver.py`), so a single bad backend response degrades one request instead of
  the node.
- **D34**: an edge `(A, B, left_of)` was being queried as "A's own `left_of` neighbors" when it
  actually needs to answer "what is `left_of` the anchor," which is the anchor's **inverse**
  relation given the file's "A is `left_of` B" convention (12.7). Caught by writing a test
  against the natural-language meaning directly rather than against the first implementation's
  output; see section 2. Both `relations.py` and `audit_edges.py` apply the fix.
- **D35**: `config/prompts/fewshot.jsonl` and `prompt.py`'s `fewshot_block()` predated the v2
  grammar and rendered examples missing the required `relation` field, which would have taught
  the model a schema the grammar no longer accepts whenever `fewshot_count > 0`. Fixed (added
  `relation` to every example, plus two new worked examples). Production's `fewshot_count=0`
  means this bug had no effect on any number in this report; recorded because it would have
  affected any future session that raises `fewshot_count` without noticing.

- **D36**: the Phi-3.5 model check (section 7) ran on the held-out 100 slice rather than the
  full 500. Reason: at the measured ~6-7 s/call decode cost under the v2 grammar (section 6),
  a full-500 run is roughly 100 minutes per model; the held-out slice was already validated
  (section 4) to track the full-500 number within 1-2 points for Phi-3 mini, and the result
  (Phi-3.5 mini 7 points worse, not within 2 points of beating production) is decisive enough
  on 100 rows that the extra compute would not plausibly change the promotion decision.

## 10. DoD

- [x] Edge coverage audit table in the report; inverse edge materialization unit tested.
- [x] GBNF v2 accepts every (canonical, relation) pair and rejects everything else.
- [x] `relations.py` unit tested on the full hop matrix including zero/multi target abstention.
- [x] Backend parity: 100/100 agreement (100 percent), >= 99 percent gate.
- [ ] Full 500, production configuration, grammar on: top-1 >= 0.80 (actual 0.560), top-3 >=
      0.88 (actual 0.754), out of graph rate 0.0 (met).
- [ ] Per category floors: not met by `spatial`, `multi_hop`, `functional`, or by
      `direct`/`alias`/`negation`/`abbreviation`'s no-regression-below-0.85 requirement.
- [x] Held-out 100 row slice and `adversarial_50.jsonl` reported separately (section 4).
- [ ] Latency p90 < 3000 ms on the Metal backend (actual 7220 ms; section 6).
- [x] `semantic_cli` shows `relation`/`anchor_room` in the JSON output (section 3); the
      specific example's answer is wrong for the accuracy reasons in section 5, not a wiring
      defect.
- [x] Phi-3.5 comparison row recorded; production model stated explicitly (section 7).
- [x] Report written.

Gate: resolver raw top-1 >= 0.80, or a documented shortfall with the 0.74-0.80 band respected.
**Neither is met**: 0.560 is below the 0.74 floor section 8 sets for stopping outright. Per
that section's own instruction, this is reported as a stop with the error analysis above,
carried into Phase 8 as PLAN.md section 8 requires, rather than a fourth prompt iteration.
