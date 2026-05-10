# Phase 5 Execution Plan: CLI And Worker Authority Migration

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 5 - CLI, Worker, Submitted Job, And SLURM Migration
- Status: in_progress
- Branch: `codex/cli-worker-authority`
- Worktree: `/home/samcantrill/work/loom-worktrees/cli-worker-authority`
- Stack predecessor: none; Phase 4 merged before PR opening.
- Base branch: `develop`
- PR target branch: `develop`
- PR: pending
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 5: CLI and Worker Authority`
- Draft pass: complete on 2026-05-10
- Refine pass: complete on 2026-05-10 because this phase spans operational
  entrypoints, worker handoff, submitted jobs, cancellation, and scheduler
  observation.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Stack Maintenance Notes

- Created `codex/cli-worker-authority` from
  `codex/python-runner-authority` while Phase 4 PR #112 was open and waiting
  on final CI after approval metadata.
- Rebased `codex/cli-worker-authority` onto updated `origin/develop` after
  Phase 4 merged and `docs: record phase 4 merge` was pushed to `develop`.
- Removed the obsolete Phase 4 worktrees and deleted
  `codex/python-runner-authority` locally and on GitHub after the rebase.

## Scope

This phase closes supported operational mutation escape hatches that can still
construct `LocalRunStore` as runtime authority.

The implementation will:

- Route `loom stage run`, `loom stage-job run`, and `loom prepared-run
  continue` through the authority-backed serial run-store factory.
- Route SLURM dry-run and live submission preparation through the same
  authority-backed store while keeping generated scripts, manifests, logs, and
  worker handoff files as local materialization artifacts.
- Route SLURM cancellation and scheduler-status observation through
  authority-backed submitted-operation reads and guarded lifecycle writes.
- Preserve existing deterministic local, fake-SLURM, continuation, and worker
  coverage while tightening diagnostics when authority state, attempt metadata,
  leases, or fencing material is missing or stale.
- Keep regular `loom run` on the authority-backed default path introduced by
  Phase 4.

## Out Of Scope

- Concrete service/database backend implementation.
- New scheduler, worker daemon, queue, retry, timeout, or reconciliation policy.
- Authority read-model migration for catalog, status, plan, diagnostics, and
  preflight beyond submitted-job paths touched in this phase.
- Removing the transitional SQLite authority backend.
- Changing real SLURM acceptance requirements beyond existing opt-in coverage.

## Design Impact

Very high. This phase changes the operational entrypoints that launch
out-of-process work, finalize submitted stages, and observe or cancel scheduler
jobs.

## Future Compatibility

Future service/database authority and HPC worker modes can reuse these
entrypoint boundaries because CLI commands and submitted-job helpers no longer
default to local-only lifecycle files.

## Alternatives Rejected

- Migrating only `loom run`. That leaves direct worker, continuation, and
  submitted-job commands able to mutate lifecycle state outside authority.
- Treating SLURM manifests as authoritative submitted state. Manifests remain
  materialized evidence; submitted-operation records remain the lifecycle
  state path.
- Adding service-backend configuration now. The implementation plan assigns
  concrete service/database backend work to Phase 7.

## Debt Introduced

- Worker and SLURM commands still use the transitional authority-backed serial
  adapter until the service backend exists.
- Live multi-host authority remains capability-limited by the transitional
  backend. This phase preserves fail-closed authority/fencing checks without
  claiming service-grade HPC reachability.

## Acceptance Criteria

- No supported CLI, worker, or submitted mutating entrypoint constructs
  `LocalRunStore` as runtime authority.
- Submitted operations are idempotent and authority-recorded.
- Worker finalization cannot succeed without active authority and correct
  fencing.
- SLURM live paths fail before submission when authority admission or selected
  backend/profile cannot prove required live semantics.
- SLURM dry-run and live paths materialize scripts/manifests without making
  those files lifecycle truth.

## Suite Obligations

- Package: CLI imports stay presentation-only and public execution imports stay
  cheap.
- Unit: CLI helper construction, stage worker requests, stage-job authority
  fencing, submitted-operation updates, cancellation/status transitions, and
  failure diagnostics.
- Contract: existing authority/store submitted-operation and fenced commit
  behavior remain green.
- Integration: SLURM dry-run/live with fakes, worker continuation, stage-job
  continuation, prepared-run continuation, cancellation, and status paths.
- E2E: CLI run, CLI SLURM dry-run, cancellation/status where deterministic.
- Opt-in: real SLURM acceptance remains opt-in and is not required locally.

## Implementation Summary

- Pending.

## Validation Evidence

- Pending.

## Stop Conditions

- The phase requires service/database backend behavior to express a safe
  authority handoff.
- Existing continuation semantics require preserving local-only lifecycle
  mutation as a supported path.
- SLURM live submission would submit before authority admission, fencing, or
  submitted-operation recording can fail closed.
