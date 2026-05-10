# Phase 4 Execution Plan: Python Runner Authority Migration

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 4 - Python Runner And Public Example Migration
- Status: in_progress
- Branch: `codex/python-runner-authority`
- Worktree: `/home/samcantrill/work/loom-worktrees/python-runner-authority`
- Stack predecessor: none; Phase 3 merged before PR opening.
- Base branch: `develop`
- PR target branch: `develop`
- PR: pending
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 4: Python Runner Authority`
- Draft pass: complete on 2026-05-10
- Refine pass: complete on 2026-05-10 because this phase changes public Python
  API guidance.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Stack Maintenance Notes

- Rebased `codex/python-runner-authority` onto updated `origin/develop` after
  Phase 3 merged and `docs: record phase 3 merge` was pushed to `develop`.

## Scope

This phase closes the direct Python API escape hatch where callers can run a
mutating `PipelineRunner` with a bare `LocalRunStore`.

The implementation will:

- Add an explicit runner guard that rejects `LocalRunStore` as a mutating
  `PipelineRunner` store with a clear authority-backed diagnostic.
- Preserve serial local execution through
  `create_authority_backed_serial_run_store`, which keeps local
  materialization paths while routing lifecycle writes through authority.
- Expose the authority-backed serial factory from the public execution package
  without adding heavyweight imports.
- Update direct Python examples, README snippets, and package docs that teach
  `PipelineRunner(run_store=LocalRunStore(...))`.
- Update runner and package tests to use authority-backed stores for mutating
  execution while retaining local artifact/materialization helper tests where
  lifecycle mutation is not the behavior under test.

## Out Of Scope

- CLI worker, `loom stage run`, `loom stage-job run`, prepared-run
  continuation, SLURM live/dry-run migration, and submitted-operation
  finalization. Those belong to Phase 5.
- Authority read-model changes for status, catalog, diagnostics, and plan
  resume. Those belong to Phase 6.
- Concrete service/database backend work.
- Removing the transitional SQLite authority backend.

## Design Impact

High. The primary Python execution facade remains stable, but its accepted
store boundary becomes authority-backed instead of local-file-backed.

## Future Compatibility

The guard makes future service/database authority adoption safer because direct
Python callers can no longer rely on local lifecycle files. The transitional
serial adapter remains a compatibility bridge until later phases replace it
with service-backed authority.

## Alternatives Rejected

- Warning-only deprecation. The phase acceptance criteria require hard failure.
- Accepting public `RunStore` alone. The current runner still needs local
  materialization paths for serial execution, so the accepted bridge must
  combine authority lifecycle behavior with local artifact paths.
- Migrating worker and SLURM examples in this phase. That would pull Phase 5
  operational behavior into the Python API phase.

## Debt Introduced

- `create_authority_backed_serial_run_store` remains transitional and still
  delegates materialization paths to the local layout while later phases finish
  caller migration.

## Acceptance Criteria

- `PipelineRunner(run_store=LocalRunStore(...))` hard-fails before mutating the
  run directory.
- `run_pipeline(..., run_store=LocalRunStore(...))` fails through the same
  guard.
- Authority-backed serial execution remains the default working Python API path.
- Public Python examples use the authority-backed factory instead of direct
  `LocalRunStore` runtime construction.
- Package import tests prove the new public factory export stays cheap.

## Suite Obligations

- Package: public execution API exports and direct pipeline import-boundary
  example using the authority-backed factory.
- Unit: runner rejection for bare local stores, factory-backed execution,
  diagnostics, and existing runner behavior with authority-backed stores.
- Contract: authority-backed runner behavior remains covered through existing
  authority adapter and run-store contract tests.
- Integration: local serial execution and resume continue through
  authority-backed stores; direct docs examples run with authority-backed
  stores.
- E2E: Python example coverage where existing docs tests exercise it.
- Opt-in: not required.

## Stop Conditions

- Runner acceptance requires migrating worker, SLURM, or continuation paths in
  this phase.
- The authority-backed serial adapter cannot satisfy existing serial execution
  behavior without widening local lifecycle semantics.
- Public example migration requires service/database backend features that do
  not exist yet.
