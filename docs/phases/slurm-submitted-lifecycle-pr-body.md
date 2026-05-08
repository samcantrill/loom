## Summary

Implements the Phase 1 foundation for v7 SLURM live operations by adding a shared submitted lifecycle and a backend-neutral submitted-operation registry. Runs and stages can now persist `SUBMITTED` as a non-terminal Loom state, ordinary status can show persisted submitted facts without scheduler access, and submitted stage-job continuations are gated before user code can run.

This PR deliberately does not add SLURM command execution, live submission, scheduler polling, `status --jobs`, or cancellation. Backend-specific scheduler details remain out of generic status, execution, store, diagnostics, and CLI modules.

## Acceptance Criteria

- [x] Shared run and stage status records parse and round-trip `SUBMITTED`.
- [x] `SUBMITTED` is non-terminal and remains non-reusable for planning/resume.
- [x] Generic submitted-operation records are schema-versioned, backend-neutral, store-safe, and discoverable by latest/latest-active helpers.
- [x] Ordinary `loom status RUN_URI` can report persisted submitted state and registry summaries without scheduler access.
- [x] `loom stage-job run` accepts only a matching submitted prepared attempt and rejects stale or mismatched submitted identity before reconstructing user stage code.
- [x] Generic code does not import `loom.pipeline.executors.slurm`.

## Implementation Notes

Adds `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`, plus lifecycle writers for submitted runs and stages that do not set execution timestamps. Adds `loom.pipeline.submitted` for `SubmittedOperationRecord`, states, active/terminal predicates, deterministic latest selection, and shared submitted-stage metadata.

Extends `RunStore` and `LocalRunStore` with submitted-operation read/write/list/latest/latest-active helpers under a store-owned `submitted_operations` directory. Diagnostics and CLI status now include compact submitted-operation summaries from persisted store state only.

Stage-job continuation now has a separate submitted path: `SUBMITTED` attempts must match stage status metadata, worker request metadata, submitted-operation registry identity, backend, mode, submission ID, manifest path, stage name, attempt, and continuation executor before transitioning through the existing `RUNNING` lifecycle.

New tests cover status serialization, submitted-operation validation and predicates, local store persistence/discovery, lifecycle writers, diagnostics/CLI status output, package exports, contract protocols, and submitted stage-job success and rejection paths.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default isolated suite, config-extra isolated suite, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 1282 passed, 11 skipped, 880 deselected. |
| GitHub checks | Pending | PR not opened yet. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 52 | 0 | 0 | 1 | 0 | 53 | 6.70s | 17% |
| unit | passed | 703 | 0 | 0 | 1 | 0 | 704 | 10.19s | 69% |
| contract | passed | 61 | 0 | 0 | 2 | 0 | 63 | 2.49s | 45% |
| integration | passed | 33 | 0 | 0 | 7 | 9 | 40 | 4.77s | 51% |
| e2e | passed | 22 | 0 | 0 | 0 | 0 | 22 | 9.55s | 71% |
| config-extra | passed | 411 | 0 | 0 | 0 | 871 | 411 | 23.37s | 76% |
| Overall | passed | 1282 | 0 | 0 | 11 | 880 | 1293 | 57.07s | - |

## Risks / Follow-Ups

- `SUBMITTED` is intentionally coarse; SLURM scheduler states, job IDs, command results, snapshots, and cancellation attempts are deferred to later v7 phases.
- Phase 1 validates backend-neutral manifest pointers and submitted identity metadata, but backend manifest internals are Phase 2 scope.
- Force/resubmit policy, active old-job guards, scheduler-aware status, and cancellation remain deferred to later phases.
