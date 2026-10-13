# docs/archive

Superseded planning documents. Nothing here is live. The current plan is always `docs/PLAN.md`.

These are kept because the merged phase reports in `docs/reports/` cite section numbers from
the plan version that was current when each phase ran, and because a later session needs to be
able to tell a deliberate reversal from something that was forgotten.

| File | What it is |
|------|------------|
| `PLAN-v1.md` | The master plan verbatim as it stood after Phase 4 merged (commit `5dd62da`, 2026-09-16). Phases 0 to 4 were executed against this document. |
| `superseded-decisions.md` | What changed between plan v1 and plan v2 on 2026-10-13, and the reasoning behind each reversal. Six entries, S1 to S6, cross-referenced to deviations D27 to D31 in the live plan. |

## Which plan did a given report follow?

| Report | Plan version |
|--------|--------------|
| `phase-0-scaffolding-environment.md` | v1 |
| `phase-1-interfaces-annotation-map.md` | v1 |
| `phase-2-sim-world-nav2-bringup.md` | v1 |
| `phase-3-llm-resolver-prototype.md` | v1 |
| `phase-4-prompt-study.md` | v1 |
| `phase-5-*` onwards | v2 (`docs/PLAN.md`) |

## Reading order if you are picking this project up cold

1. `CLAUDE.md` at the repo root, for conventions.
2. `docs/PLAN.md`, the live plan.
3. `docs/archive/superseded-decisions.md`, to understand why the back half of the plan looks
   different from the phase 0 to 4 reports' assumptions.
4. Only then `PLAN-v1.md`, and only if you need the original wording of something.
