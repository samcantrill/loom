## Summary

@samcantrill

This PR adds the generic prepared-run and lifecycle foundations for SLURM script planning without adding SLURM-specific execution, script generation, or CLI continuation behavior. It introduces a schema-versioned prepared-run record as a run-level sibling document, store-owned persistence and path resolution contracts, and validation that rejects secret-bearing or scheduler-specific payloads before they can be written.

It also extracts narrowly scoped runner lifecycle helpers for input binding and artifact-index updates so later continuation flows can reuse existing runner semantics without changing local or subprocess behavior.

## Acceptance Criteria

- [x] Prepared-run metadata can be written and read through public execution and store APIs.
- [x] Secret-bearing resolved values, resolver outputs, environment payloads, raw adapter payloads, and scheduler facts are rejected with structured errors.
- [x] Shared lifecycle helpers preserve existing local and subprocess execution behavior.
- [x] Generic execution and store modules remain domain-neutral, with no SLURM package, CLI continuation command, script generation, scheduler state, or live scheduler behavior added.
- [x] Run-scoped generated artifact paths resolve through a store-owned helper that accepts safe relative paths and rejects unsafe paths.

## Implementation Notes

- Added `PreparedRunRecord`, prepared-run schema constants, and structured payload errors under `loom.pipeline.execution`, with public exports separate from `StageWorkerRequest`.
- Added store-safe prepared-run document validation under `loom.pipeline.stores`, including deny-by-default field and metadata-kind checks for unsafe resolved, environment, raw adapter, secret, scheduler, and job-ID payloads.
- Extended the `RunStore` and `LocalRunStorePaths` protocols, plus `LocalRunStore`, with `prepared_run.json` read/write support and `local_generated_artifact_path()` safe-relative path resolution.
- Moved existing runner-owned input binding and artifact-index update behavior into `execution.lifecycle` helpers while preserving the runner commit/status/event flow.

New tests implemented:

- Package API tests cover the new execution and store exports.
- Unit tests cover prepared-run schema validation, safe payload acceptance, unsafe payload rejection, lifecycle helper behavior, local prepared-run persistence, generated artifact path safety, and store error inheritance.
- Contract and integration tests cover the updated store protocol obligations and real local-store prepared-run round trips.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright passed with 0 errors; default harness passed 747 selected tests with 14 skipped and 8 deselected; config-extra harness passed 405 selected tests with 765 deselected; build produced source distribution and wheel. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall 1170 passed, 0 failed, 0 errors, 11 skipped, 773 deselected in 47.36s. |
| GitHub checks | Not run | Expanded-path draft pass only; PR creation and remote checks are left for the PR body refine pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.69s |
| unit | passed | 621 | 0 | 0 | 1 | 0 | 7.27s |
| contract | passed | 55 | 0 | 0 | 2 | 0 | 2.15s |
| integration | passed | 21 | 0 | 0 | 7 | 8 | 3.54s |
| e2e | passed | 18 | 0 | 0 | 0 | 0 | 7.77s |
| config-extra | passed | 405 | 0 | 0 | 0 | 765 | 20.94s |
| Overall | passed | 1170 | 0 | 0 | 11 | 773 | 47.36s |

## Risks / Follow-Ups

- Phase 2 still owns public `loom prepared-run continue` and `loom stage-job run` continuation commands.
- Later SLURM phases still own SLURM models, manifests, script generation, CLI dry-run wiring, and full secret-surface hardening across generated artifacts.
- Stronger submitted-job locking remains deferred until live or multi-coordinator submitted execution requires it.
