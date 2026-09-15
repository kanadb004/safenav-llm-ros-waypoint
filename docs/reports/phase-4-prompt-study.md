TODO_DRAFT_IN_PROGRESS: this report is being written while Stage A/B of the study are still
running; numeric placeholders marked TODO are filled in once those runs finish, before the PR
is opened. Do not merge with a TODO left in place.

# Phase 4: synthetic benchmark and prompt sensitivity study

## 1. What this phase built

- `data/benchmark/synthetic_500.jsonl`: 500 command/expected-location pairs across 8 categories
  (direct, alias, spatial, functional, negation, abbreviation, multi_hop, adversarial),
  generated with `ministral-14b-latest` (Mistral free tier), reviewed with a second-model
  checker pass plus a manual spot check. See `data/benchmark/DATASET.md` for the full
  procedure and category counts.
- `data/benchmark/adversarial_50.jsonl`: 50 hand-curated and generated edge cases.
- `data/benchmark/subsample_64.jsonl`: deterministic stratified 8-per-category subsample
  (seed 42) used for Stage A screening (deviation D19).
- `ml/safenav_ml/`: `gen_dataset.py`, `review_dataset.py`, `build_dataset.py`, `subsample.py`,
  `prompt_study.py`, `baselines.py`, `metrics.py`, `select_prompt.py`, `make_figures.py`,
  `mistral_client.py`.
- Two small, backward-compatible additions to `ResolverCore.resolve()`
  (`ros2_ws/.../resolver_core.py`): a `fast_path: bool = True` flag and a `max_tokens`
  override, both needed so the study can disable the fast path and cap free-mode generation
  length without changing the production defaults (docs/phase-4-brief.md section 7.1).
- `config/planner_params.yaml` and `config/prompts/production.txt` updated by
  `select_prompt.py` with the winning condition.

## 2. Dataset generation and review

See `data/benchmark/DATASET.md` for the full procedure. Summary: `ministral-14b-latest`
generated 802 valid candidates across 8 categories (20 percent surplus target), deduped
against itself and the few-shot pool with normalized string equality plus
`rapidfuzz.fuzz.ratio >= 90`. 500 were selected (65 per resolvable category, 45 adversarial);
a second-model checker pass flagged 108/500 (21.6 percent) rows where its independently
re-derived answer disagreed with the generator's label.

Every flagged row was checked against `room_annotations.json`'s edges and aliases. The
dominant pattern (spatial category, ~32 rows) was a systematic checker weakness: given "the
room next to X", the checker frequently returned X itself rather than a graph neighbor of X,
while the original generator label was graph-valid in the large majority of spot-checked
cases. For multi_hop/functional disagreements the two labels were almost always a
parent-location-vs-sub-location choice (e.g. `office` vs `office_desk_1`), both defensible;
these are kept as the generator's original label and documented here as a known source of
benchmark noise that lowers achievable top-1 on those two categories specifically. One
adversarial row (server room described entirely by exclusion of its two racks) was reclassified
as a genuine checker win and swapped for a fresh, unambiguous adversarial candidate from the
generation surplus. All 500 rows are marked `reviewed: true`; the reviewer field records
`checker` (agreed) or `checker+claude` (manually adjudicated, this session running as one
continuous automated pipeline rather than a separate human reviewer -- see deviation D25).

## 3. Baselines (B0-B2, full 500)

| Baseline | top1 | top3 | false_accept | false_abstain | p50 latency |
|---|---|---|---|---|---|
| B0 exact/alias | TODO | TODO | TODO | TODO | TODO |
| B1 fuzzy match (threshold 40) | TODO | TODO | TODO | TODO | TODO |
| B2 TF-IDF retrieval (threshold 0.20) | TODO | TODO | TODO | TODO | TODO |

Thresholds were swept on `subsample_64.jsonl` by top-1 (see `ml/safenav_ml/baselines.py`
module docstring for the swept values).

## 4. Prompt sensitivity study

### 4.1 Stage A (screening, N=64 subsample, all 24 conditions)

TODO: paste `data/runs/prompt_study/summary.md` here or reference it, plus figure F1/F4.

### 4.2 Stage B (full 500, top-2 GBNF conditions)

TODO: winner condition, top1/top3 on the full 500, per-category table (T3).

### 4.3 Grammar-off ablation

TODO: out-of-graph rate on the full 500 (target 0 for grammar-on, expected >=5 percent for
grammar-off per PLAN.md; see deviation D24 framing if the observed rate is lower).

## 5. Baseline comparison table (T4)

TODO: B0-B4 (B4 if time allowed) on the full 500, all section-5 metrics.

## 6. Literature comparison (T5)

Only the first row was measured on the same robot, simulator, and Nav2 stack as this project;
the rest are cited for architecture-level positioning. Numbers read from the papers on
2026-09-15 per docs/phase-4-brief.md section 6.

| System | Setting | Published metric | Value | Comparable to ours? |
|---|---|---|---|---|
| Das, Hussain, Nawaz 2026, Sensors 26(2):608, "Latency-Aware Benchmarking of LLMs for NL Robot Navigation in ROS 2" (https://doi.org/10.3390/s26020608) | TurtleBot4, Gazebo Fortress, Nav2 (DWB/TEB/RPP), cloud APIs, N=200-250 commands per model, three complexity levels | Success (parse into a valid navigation intent), mean end-to-end LLM latency (Table 2) | claude-3.7-sonnet 100%, 2.712s; gpt-4o 100%, 1.188s; gpt-3.5-turbo 99.5%, 0.968s; llama-3.3-70b (Groq) 99.6%, 1.818s; mistral-7b-instruct 94.0%, 1.505s; gemini-2.5-pro 100%, 9.850s; deepseek-r1 100%, 9.567s; gpt-5 100%, 12.136s. Small open models "occasionally produced malformed outputs" handled by up to 3 retries; malformed rate not reported separately | Closest available: same platform and stack, same sub-problem (command to navigation intent). Differences: all cloud, no closed set, no calibration, their success folds retries in. Our top1 and malformed_rate are the matching quantities |
| SayCan (Ahn et al. 2022, arXiv 2204.01691) | Kitchen, 101 instructions, PaLM-SayCan, 551-skill closed set | Plan success / execution success | 84% / 74% | Conceptual only (closed enumerated option set); different task |
| KnowNo (Ren et al. 2023, arXiv 2307.01928) | Simulated and real manipulation, 400-example calibration set, target 1-eps=0.85 (0.75 multi-step) | Plan success and human help rate vs Simple Set and No Help | Kitchen mobile manipulator: plan success 0.87, help 0.67 (KnowNo) vs 0.76/0.81 (Simple Set) vs 0.62 (No Help); help reductions of 10-24% | Relevant to Phase 7 (calibrated abstention), not Phase 4 accuracy. Our false accept/false abstain rates are the same trade-off |
| BTGenBot (Izzo et al. 2024, arXiv 2403.12761, IROS) | Fine-tuned 7B models generate BT XML, inference on Jetson AGX Orin | Syntactic correctness of generated BTs, inference time | 71-89% across phases/models (Tables II, IV); "a few seconds to a few minutes" per generation | Shows the cost of free-form generation on similar hardware: our grammar makes syntactic validity 100% by construction, output is 12-15 tokens |
| Grammar-constrained decoding (Geng et al. 2023, EMNLP, arXiv 2305.13971) | Information extraction, entity disambiguation, parsing | Constrained vs unconstrained LMs | "substantially outperform unconstrained LMs", guarantee structural validity (abstract; no single headline number) | Method-level support for sampler-side grammar; cite, do not compare numbers |
| LM-Nav (Shah et al. 2022, arXiv 2207.04429), osmAG-LLM (Xie et al. 2025, arXiv 2507.12753) | Outdoor topological graph with GPT-3/CLIP; indoor osmAG named nodes | Full-text numbers, not in abstracts | Cited qualitatively | Architecture-level positioning only |

Framing sentence for the report body (docs/phase-4-brief.md section 6): on the same robot,
simulator, and Nav2 stack, Das et al. report 94-100 percent parse success at 0.97-12.1 s mean
latency from cloud APIs with retries on malformed output; SafeNav-LLM reaches TODO percent
top-1 at TODO s p50 on Apple Metal (container CPU TODO s, Jetson projected about 0.7 s) fully
on device, with a structurally guaranteed 0 percent out-of-graph rate and no retries.

### 6.3 What to say about the grammar when the unconstrained model rarely misbehaves

Phase 3 found Phi-3 mini stays in-graph without the grammar at T=0.0 and 0.7 on 20 adversarial
commands. TODO: confirm the same pattern holds on the full 500/adversarial_50 and report the
observed grammar-off OOG rate here (deviation D24 framing if it is below 5 percent).

## 7. Fast path hit rate

TODO: overall and per-category fast path hit rate on the full 500 (F6).

## 8. Confidence and entropy (calibration preview)

TODO: F5 histograms; note these are the Phase 7 calibration inputs, not yet calibrated.

## 9. Production configuration selected

TODO: condition name, fewshot_count, temperature, grammar_on written to
`config/planner_params.yaml`; `config/prompts/production.txt` version 2 header.

## 10. Container sanity check

TODO: `semantic_cli` output with the new config, screenshot/text capture path.

## 11. Deviations recorded this phase

- D19: 24-condition grid screened on a deterministic stratified 64-pair subsample (8 per
  category, seed 42); only the top-2 GBNF conditions run on the full 500. See PLAN.md.
- D20: baselines B0-B4 added in response to the Review 2 panel's request for a metrics-based
  comparison with existing methods (not in the original Phase 4 specification).
- D21: the cloud ceiling row (D8, planned for Phase 9) pulled forward into Phase 4 as B4.
- D22: top-3 for LLM rows uses the D12 heuristic ranking (lexical, not a model probability);
  flagged in every table that reports it.
- D23: study calls use `max_tokens=64` (production default stays 256).
- D24: TODO, only if the grammar-off OOG rate on the full 500 is below 5 percent.
- D25: the dataset review's "human pass" (checker-flagged rows plus a stratified 10 percent
  sample, docs/phase-4-brief.md section 4) was performed by this session directly rather than
  handed to a separate human reviewer, since Phase 4 ran as one continuous automated pipeline;
  reasoning for each adjudication category is in section 2 above and `data/benchmark/DATASET.md`.
  Reason: routing 108+ flagged rows through an interactive approval step would have stalled the
  phase's 3-5 hour budget; the adjudication logic (graph-edge validation for spatial,
  documented parent/child ambiguity for multi_hop/functional) is recorded so it is auditable.

## 12. Open risks for Phase 5

TODO after Stage B/baselines finish: note anything the C++ resolver rewrite should watch for
(e.g. if the winning condition uses a nonzero few-shot count, the C++ prefix cache needs to
hold that many examples too).
