# Phase 6 Execution Plan: Authority Read Models

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 6 - Authority Read Models For Status, Catalog, Plan, And Diagnostics
- Status: in_progress
- Branch: `codex/authority-read-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-read-models`
- Stack predecessor: none; Phase 5 merged before branch creation.
- Base branch: `develop`
- PR target branch: `develop`
- PR: pending
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 6: Authority Read Models`
- Draft pass: complete on 2026-05-10
- Refine pass: complete on 2026-05-10 because this phase spans status,
  catalog, planning resume, diagnostics, and preflight read behavior.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Scope

This phase prevents supported user-visible behavior reads from treating local
status files as lifecycle truth.

The implementation will:

- Route `loom status` and diagnostics status/artifact summaries through
  authoritative snapshots when lifecycle behavior is requested.
- Preserve local log and artifact materialization access for commands that read
  logs, artifact refs, payload paths, generated files, or provenance documents.
- Route `loom plan --resume` and resume decisions through the
  authority-backed run-store factory instead of a bare `LocalRunStore`.
- Route SLURM active-submission preflight checks through authority-backed
  submitted-operation reads.
- Make catalog direct scans use authority snapshots for run/stage behavior and
  warn instead of indexing local-only lifecycle status when a run has no
  supported authority backend.
- Add or update diagnostics/tests so corrupt or stale local status files cannot
  override authority facts, and historical local-only runs are described as
  artifact-only rather than supported lifecycle state.

## Out Of Scope

- Bundle/export behavior.
- Migrating historical local-only runs into authority.
- Concrete service/database backend implementation.
- Removing local materialization helpers or log/artifact readers.
- Removing the transitional SQLite authority backend.

## Design Impact

High. This phase changes public read behavior for status, catalog, planning
resume, and preflight so lifecycle facts come from authority instead of local
compatibility files.

## Future Compatibility

Service-backed read models, dashboards, sweeps, bundle/export, and reliability
features can build on the same authority snapshot boundary without re-adding
local lifecycle fallback.

## Alternatives Rejected

- Keeping local `status.json` and stage status files as fallback behavior
  reads. That would keep v9-post lifecycle escape hatches alive through
  inspection paths.
- Removing local log/artifact access. Logs, artifacts, manifests, and generated
  files are materialization, not lifecycle authority.
- Implementing service-specific reads now. Phase 7 owns the concrete backend.

## Debt Introduced

- Historical local-only runs remain inspectable only for materialized files and
  may need manual or external migration for lifecycle behavior.
- The authority snapshot helper still targets the transitional SQLite-backed
  authority until later service-backend phases.

## Acceptance Criteria

- `loom status`, catalog summaries, plan resume decisions, diagnostics status,
  and SLURM active-submission preflight read authority facts for lifecycle
  behavior.
- Local run/stage files are not used as lifecycle fallback when authority is
  missing, corrupt, or stale.
- Local logs, artifact refs, generated artifacts, and provenance/materialized
  documents remain readable through materialization paths.
- Catalog warnings make local-only lifecycle state explicit and do not index
  those facts as supported current behavior.
- Tests prove local status files cannot override authority facts.

## Suite Obligations

- Package: `loom.runs`, diagnostics, and CLI imports remain lightweight and do
  not add concrete execution or optional config imports at module import time.
- Unit: diagnostics read selection, local-only lifecycle rejection, catalog
  warning codes, plan resume store selection, and preflight submitted-operation
  authority reads.
- Contract: existing authoritative snapshot/read-model contracts remain green.
- Integration: status/logs, run catalog list/diff, plan resume, diagnostics,
  and preflight over authority-backed runs.
- E2E: CLI status/logs/runs commands on authority-backed runs and local-only
  lifecycle rejection where deterministic.
- Opt-in: not required.

## Implementation Summary

- Pending.

## Validation Evidence

- Pending.

## Stop Conditions

- The phase requires service/database backend behavior to express the read
  boundary.
- Existing supported commands require local lifecycle files as behavior truth
  instead of materialization.
- Removing local lifecycle fallback would make logs or artifacts unreadable;
  in that case, split lifecycle rejection from materialization access.
