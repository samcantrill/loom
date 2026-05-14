## Summary

Implements Phase 3 of v5 by adding serial subprocess execution behind the
existing executor protocol. `loom run CONFIG --executor subprocess` now prepares
one durable worker request per runnable stage, launches the public
`loom stage run` worker command in a subprocess, reads `worker_result.json`
through store APIs, and lets the parent runner perform final output validation,
failure persistence, provenance, artifact indexing, stage status, and run
status updates.

The subprocess executor treats the durable worker result as the source of truth
and fails explicitly on missing, invalid, mismatched, stale, process-failed,
signal-terminated, and structured/process-conflict outcomes. Phase 4 still owns
selected-executor worker/Python availability preflight and diagnostics UX.

## Acceptance Criteria

- [x] `loom run CONFIG --executor subprocess` runs synthetic success and failure
  pipelines through real worker subprocesses.
- [x] Parent-owned finalization remains the only path that writes final outputs,
  failures, provenance, artifact indexes, stage status, and run status.
- [x] Subprocess process failures, signal terminations, missing results, invalid
  results, identity mismatches, and structured-success/process-failure conflicts
  become explicit failed stage results.
- [x] The subprocess executor descriptor is registered without making runtime
  capability imports load executor implementation modules.
- [x] CLI executor selection supports `local` and `subprocess` while continuing
  to reject unknown executor names.

## Implementation Notes

- Added `SubprocessExecutor`, `SubprocessRunResult`, and worker command
  construction under `loom.pipeline.executors`.
- Added lazy subprocess exports so `loom.pipeline.executors` stays import-light.
- Added a prepared-worker runner path that calls `prepare_stage_attempt`, marks
  the stage running, invokes the executor, and reuses the existing parent
  finalization helper.
- Registered a built-in subprocess runtime descriptor for selected-executor
  validation.
- Updated CLI and execution docs for current subprocess support and deferred
  Phase 4 preflight/diagnostics scope.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright with config extra, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.20s |
| unit | passed | 587 | 0 | 0 | 1 | 0 | 6.51s |
| contract | passed | 55 | 0 | 0 | 2 | 0 | 1.98s |
| integration | passed | 20 | 0 | 0 | 7 | 7 | 2.97s |
| e2e | passed | 18 | 0 | 0 | 0 | 0 | 7.16s |
| config-extra | passed | 400 | 0 | 0 | 0 | 730 | 16.88s |

## Risks / Follow-Ups

- Worker command and Python executable availability preflight remains Phase 4.
- CLI diagnostics for subprocess failures remain intentionally concise until
  Phase 4 adds the dedicated diagnostics UX.
- Timeout enforcement, retries, leases, parallelism, and attempt archive
  directories remain deferred to later roadmap work.
