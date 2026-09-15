# Benchmark dataset card

Generated 2026-09-15 with `ministral-14b-latest` (Mistral free tier) via the Mistral chat completions REST API, temperature 1.0, `response_format: json_object`, one request per (category, batch of 25).

Deviation D2 (PLAN.md section 14): the specification names GPT-4 as the generation model; this build uses ministral-14b-latest on cost grounds (see docs/phase-4-brief.md and PLAN.md D2).

## Category counts (synthetic_500.jsonl)

| Category | Count |
|---|---|
| abbreviation | 65 |
| adversarial | 45 |
| alias | 65 |
| direct | 65 |
| functional | 65 |
| multi_hop | 65 |
| negation | 65 |
| spatial | 65 |
| **total** | **500** |

## Review procedure

1. Generation: ministral-14b-latest, 20 percent surplus per category, one request per (category, batch of 25).
2. Dedupe: normalized string equality, then `rapidfuzz.fuzz.ratio >= 90`, against the pool itself and against `config/prompts/fewshot.jsonl`.
3. Schema validation: `expected` must be a canonical name in `room_annotations.json` (resolvable categories) or exactly `"none"` (adversarial category).
4. Checker: a second ministral-14b-latest call per batch of 25 re-derives `expected` from the command and the graph independently; rows where the checker disagrees are flagged.
5. Human/reviewer pass: a deterministic stratified 10 percent sample (seed 42, `random.Random(42).sample` per category) plus every flagged row is reviewed manually (recorded as `checker+claude` in this build, since the phase ran as one continuous automated session; see the phase report for the deviation from the brief's `checker+human` label).
6. `adversarial_50.jsonl` = the adversarial-category surplus beyond the 45 rows used in synthetic_500.jsonl, plus 5 hand-added edge cases (empty command, emoji, two rooms in one command, a prompt-injection attempt, a 300+ character command).

Checker disagreement count on the final 500: 107

Reviewer breakdown (synthetic_500.jsonl):

| Reviewer | Count |
|---|---|
| checker | 392 |
| checker+claude | 108 |

Note for Phase 7: persona command sets (`data/calibration/session*_sim.jsonl`) must be checked for overlap against the normalized commands in this file before use, per PLAN.md section 10.
