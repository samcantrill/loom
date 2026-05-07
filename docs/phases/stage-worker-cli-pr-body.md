## Summary

Implements Phase 2 of v5 by adding the direct stage-worker execution path and
public `loom stage run` command. A worker can now open an existing run URI,
infer or validate one prepared attempt, reconstruct a single stage execution
request from durable Loom records, run it through the local executor path, and
write a schema-versioned `worker_result.json` handoff.

The worker preserves the parent/worker boundary: it writes only the structured
result handoff and does not finalize stage outputs, failure records,
provenance, artifact indexes, stage status, or run status. Subprocess parent
orchestration remains deferred to Phase 3.

## Acceptance Criteria

- [x] `loom stage run --run-uri RUN_URI --stage STAGE [--attempt N]` executes one
  prepared stage attempt and returns direct-worker exit codes for success,
  stage failure, usage, state errors, and interruption.
- [x] Worker reconstruction consumes durable run records: prepared request,
  execution plan, fingerprint payload, resolved runtime metadata, local
  artifact/run-store paths, and prior input artifacts.
- [x] The direct worker writes `worker_result.json` and does not perform
  parent-owned finalization.
- [x] Missing, completed, invalid, or unprepared state fails clearly before
  running stage code.

## Implementation Notes

- Added `StageWorkerRunRequest`, `StageWorkerStateError`,
  `infer_stage_worker_attempt`, `reconstruct_stage_execution_request`, and
  `run_stage_worker` to `loom.pipeline.execution`.
- Reconstructs the stage spec from the prepared request fingerprint payload,
  avoiding a normal worker `--config` input.
- Added `loom stage run` with text and JSON output through the existing CLI
  dispatch/error formatting pattern.
- Updated execution and CLI docs to mark direct worker execution as implemented
  while keeping subprocess execution out of scope.

New tests cover worker attempt inference, exact attempts, state errors,
handoff-only persistence, direct CLI output/exit codes, real successful worker
execution, and real stage-failure handoffs.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright with config extra, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 6.17s |
| unit | passed | 578 | 0 | 0 | 1 | 0 | 6.63s |
| contract | passed | 54 | 0 | 0 | 2 | 0 | 2.44s |
| integration | passed | 18 | 0 | 0 | 7 | 7 | 2.48s |
| e2e | passed | 16 | 0 | 0 | 0 | 0 | 6.48s |
| config-extra | passed | 400 | 0 | 0 | 0 | 716 | 19.29s |

## Risks / Follow-Ups

- Subprocess parent orchestration, process metadata/readback, selected-executor
  preflight, and diagnostics UX remain Phase 3 and Phase 4 work.
- Direct worker reconstruction currently derives the stage spec from the
  fingerprint payload. A later phase can add an explicit durable full-config
  snapshot if direct worker execution needs exact full resolved-config context.
- Full attempt archive directories, retries, leases, timeout enforcement, and
  cleanup policy remain deferred to later roadmap owners.
