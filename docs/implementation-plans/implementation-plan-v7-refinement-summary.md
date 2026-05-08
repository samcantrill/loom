# Plan Refinement Summary

## Metadata

- Refined plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source review report:
  `docs/implementation-plans/implementation-plan-v7-plan-review-report.md`
- Refiner: Codex managing agent
- Refinement date: 2026-05-08
- Gate: plan quality
- Plan refinement budget status after this pass: used

## Findings Addressed

| Original finding | Change made | Location |
| --- | --- | --- |
| Missing submitted stage-job startup semantics | Added the generic `SUBMITTED -> RUNNING` continuation contract, including identity/attempt/backend/submission metadata validation, Phase 1 scope, Phase 1 acceptance criteria, Phase 1 test obligations, and Phase 4 afterok startup acceptance. | `implementation-plan-v7.md` Key Design Choices, Phase 1, Phase 4 |
| Inconsistent `submission.json` vs `manifest.json` path | Standardized v7 on the existing v6 `slurm/submissions/<submission_id>/manifest.json` path and prohibited a second `submission.json` source of truth. | `implementation-plan-v7.md` Key Design Choices, Phase 2 |
| Underspecified submitted-operation registry | Added required generic registry fields, state values, active/terminal predicates, deterministic latest/latest-active ordering, backend metadata boundary, and shared submit/status/cancel predicate requirements. | `implementation-plan-v7.md` Key Design Choices, Extensibility Assessment, Phase 1 |
| Cancellation status outcomes not objective enough | Added a Phase 6 cancellation mutation matrix covering full, partial, unknown, already-terminal, and missing-command outcomes, plus acceptance and unit-test obligations for the matrix. | `implementation-plan-v7.md` Phase 6 |

## Accepted Risks

| Risk | Why accepted | Revisit trigger |
| --- | --- | --- |
| `SUBMITTED` remains a coarse generic state | Backend-specific scheduler state remains in submitted-operation metadata and SLURM manifests. | A second submitted backend shows `SUBMITTED` is too coarse, or status/resume semantics become ambiguous. |
| Status inspection does not reconcile core statuses | Avoids silent repair and false certainty from stale scheduler data. | A future explicit repair/reconcile command or v16 reliability policy needs controlled mutation. |
| Real-cluster acceptance is extensive but not a certification matrix | SLURM sites vary too much for one opt-in suite to certify every configuration. | A dedicated CI cluster or site-specific acceptance profiles become available. |

## Remaining Blockers

- None known after refinement; confirmation review is still required before the
  plan quality gate can pass.

## Confirmation Review Handoff

- Sections changed:
  - Metadata
  - Key Design Choices
  - Extensibility Assessment
  - Plan Quality Gate
  - Phase 1
  - Phase 2
  - Phase 4
  - Phase 6
- Design choices clarified:
  - `SUBMITTED -> RUNNING` submitted stage-job continuation
  - canonical `manifest.json` live SLURM path
  - generic submitted-operation registry states and predicates
  - cancellation mutation outcomes
- Test strategy changes:
  - Added submitted stage-job validation coverage.
  - Added registry active/terminal predicate coverage.
  - Added cancellation mutation matrix coverage.
- Phase splits or scope changes:
  - No phase split changed.
  - Phase 1 now explicitly owns submitted continuation semantics and registry
    predicates.
  - Phase 6 now owns a reviewable cancellation mutation matrix.
- Recommended confirmation review focus:
  - Verify all four initial findings are fully resolved.
  - Confirm the refinement did not move SLURM-specific state into generic
    registry records.
  - Confirm phase scopes remain one-PR reviewable.
