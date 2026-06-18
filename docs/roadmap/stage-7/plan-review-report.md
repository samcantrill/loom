# Plan Review Report

## Metadata

- Reviewed plan: `docs/roadmap/stage-7/implementation-plan.md`
- Reviewer: `loom_plan_reviewer`
- Review date: 2026-05-08
- Gate: plan quality
- Budget status after this review: used

## Findings

| Severity | Location | Finding | Required remedy |
| --- | --- | --- | --- |
| Blocking | `docs/roadmap/stage-7/implementation-plan.md` design choices and Phase 4; `src/loom/pipeline/execution/stage_worker.py` current gate behavior | `StageStatus.SUBMITTED` is introduced before live afterok submission, and Phase 4 marks accepted jobs `SUBMITTED`, but the current stage-job continuation gates only accept `PENDING` or `RUNNING`. Without an explicit transition contract, submitted SLURM jobs can start and then fail before user code. | Add generic continuation semantics for `SUBMITTED -> RUNNING`: stage-job attempt inference/validation must accept a submitted prepared attempt only when identity, attempt, and submission metadata match, then transition to running without weakening local/subprocess behavior. Add unit/integration/e2e obligations for submitted stage-job continuation. |
| Blocking | `docs/roadmap/stage-7/implementation-plan.md` key design choices and Phase 2; `src/loom/pipeline/executors/slurm/paths.py` current helper | The durable SLURM artifact name is inconsistent. The plan says to extend `slurm/submissions/<submission_id>/submission.json`, while v6/current code and the rest of the plan use `manifest.json`. This risks duplicate live state files and broken run-store discovery. | Standardize the plan on one canonical live manifest path. Prefer extending the existing v6 `manifest.json` with a schema-versioned live manifest model, or else document a deliberate rename with compatibility and migration rules. Update all phase criteria and registry fields to use the same name. |
| Blocking | `docs/roadmap/stage-7/implementation-plan.md` submitted-operation registry references and Phase 6 | The generic submitted-operation registry is central to active-job guards, latest-submission status, and cancellation, but the plan does not define the minimum generic lifecycle states or active/terminal predicates. Later phases could each infer "latest active" differently. | Add a small generic registry contract in Phase 1: required fields, schema version, ordering rule, latest vs latest active selection, active/terminal state values, how backend manifests remain nested, and which later operations may mutate registry state. Keep SLURM-specific payloads out of the generic record. |
| High | `docs/roadmap/stage-7/implementation-plan.md` Phase 6 | Cancellation mutation is described as "where safe," but the acceptance criteria do not define objective run/stage status outcomes for full, partial, unknown, already-terminal, and missing-command cases. This is a mutating public operation and needs a reviewable state matrix. | Add a concise cancellation mutation matrix to Phase 6: when run status may become `CANCELLED`, when submitted stages may become `CANCELLED`, when statuses must remain `SUBMITTED`, and how partial/unknown outcomes affect exit code, manifest records, and registry active state. |

## Open Questions Or Assumptions

- V6 is treated as an intended prerequisite per the roadmap notes. Phase
  implementation should still verify the actual base has the v6 continuation
  contracts before starting.
- The backend-neutral `status --jobs` and `cancel --jobs` surface is sound; the
  blockers are about making contracts precise enough for small phase PRs.

## Readiness Decision

- Ready for phase implementation: no
- Blocking findings remaining: 3 before refinement
- Accepted risks and revisit triggers: coarse `SUBMITTED`, no force/resubmit,
  no automatic partial cleanup, and opt-in-only real SLURM coverage are
  acceptable if refinement adds the missing transition, artifact, and registry
  contracts.

## Handoff

- Manager should run the single allowed plan refinement pass and then request
  confirmation review.
