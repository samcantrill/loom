## Summary

Implements Phase 3 of deterministic sweeps: cooperative early stopping and
direct sequential dispatch. Stage code can now call `context.stop_early(...)`,
which raises a typed signal that execution maps to `CANCELLED` lifecycle state
with structured `LifecycleReason(code="early_stop")` metadata instead of a
generic failure.

The sweep layer can now run a finite `SweepPlan` directly by building one
`RunRequest` per planned trial, preserving stable trial run URIs and
sweep/trial metadata, delegating execution to `PipelineRunner`, continuing
after failed trials, and reporting an aggregate failed sweep only when a
required trial fails.

## Acceptance Criteria

- [x] `context.stop_early(...)` raises a typed early-stop signal with
  plain-data detail.
- [x] Local and worker execution paths preserve controlled cancellation as
  `CANCELLED` plus `early_stop` reason metadata, not `ExecutionFailure`.
- [x] Direct dispatch consumes Phase 1 dispatch records and Phase 2 planned
  trial records to build ordinary `RunRequest` values.
- [x] Direct dispatch runs remaining trials after failed trials and reports a
  failed sweep result when a required trial fails.
- [x] Compatible existing manifests are honored and incompatible manifests
  block direct dispatch with structured diagnostics.

## Implementation Notes

- Added `loom.pipeline.early_stopping` as the generic signal home and
  `loom.pipeline.sweep.early_stopping` as the public sweep-facing re-export.
- Added lifecycle helpers for cancelled run and stage status records with
  structured reason metadata.
- Widened `StageExecutionResult` and `StageWorkerResult` to allow
  `StageStatus.CANCELLED` for controlled cancellation while keeping failures
  explicit.
- Updated local and subprocess execution handling so early stop is not
  swallowed as a generic stage exception.
- Added direct sweep dispatch result records and `run_sweep_direct(...)`,
  including per-trial dispatch requests, run request metadata, compatible plan
  checks, failure continuation, and early-stopped counts.

New tests cover context helper validation, runner lifecycle mapping, local and
subprocess-adjacent execution behavior, direct dispatch request construction,
failure continuation, early-stopped trials, manifest incompatibility, package
exports, and direct dispatch integration through `PipelineRunner`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 3 tests | Passed | 52 passed across context, runner, sweep unit, dispatch contract, and sweep integration tests |
| Adjacent execution/executor tests | Passed | 71 passed across execution models, lifecycle, stage worker, local/subprocess executors, and runner tests |
| Package/import-boundary tests | Passed | 45 passed |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Wrote `build/test-summary.md` |
| GitHub checks | Pending | Available after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 79 | 0 | 0 | 1 | 0 |
| unit | passed | 1077 | 0 | 0 | 7 | 1 |
| contract | passed | 195 | 0 | 0 | 2 | 0 |
| integration | passed | 153 | 0 | 0 | 8 | 13 |
| e2e | passed | 42 | 0 | 0 | 0 | 2 |
| config-extra | passed | 438 | 0 | 0 | 0 | 1555 |

## Risks / Follow-Ups

- Direct dispatch does not apply trial override values itself; callers provide
  the per-trial `RunRequest` template/factory and sweep records preserve the
  override facts for later CLI/config composition.
- Phase 4 owns authority-backed coordination, queue dispatch, and status
  aggregation, including derived `early_stopped` presentation.
- Phase 5 owns collection, public `loom sweep` CLI commands, docs, and final
  workflow hardening.
