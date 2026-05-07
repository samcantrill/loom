## Summary

Implements Phase 1 of v5 by adding the durable stage-worker contract for one
prepared attempt. The PR introduces schema-versioned worker request/result
records, signal-aware failure metadata, executor metadata redaction, store APIs
for latest-stage-compatible worker handoff records, and the parent-side
`prepare_stage_attempt` API.

It also aligns the execution, CLI, and run-store source docs with the v5 worker
contract: `--run-uri` is the stable worker input, normal worker `--config` is
out of scope, the worker writes only a structured handoff, and parent-owned
finalization remains preserved.

## Acceptance Criteria

- [x] Request/result/failure records round-trip through plain-data
  serialization and reject invalid identity, status, failure, exit-code, and
  signal combinations.
- [x] Prepared attempts persist request metadata, inputs, fingerprints, log
  paths, result handoff paths, safe resolved runtime metadata, and explicit
  attempt identity through store APIs.
- [x] Store APIs preserve the current latest-stage-compatible layout while
  hiding worker request/result paths behind run-store methods.
- [x] Redaction helpers avoid persisting full environment values or obvious
  secret-bearing command metadata.
- [x] Source docs no longer conflict with the v5 worker command and
  parent-finalization decisions.

## Implementation Notes

- Added `StageWorkerRequest` and `StageWorkerResult` in
  `loom.pipeline.execution.models`, plus `signal` support on
  `ExecutionFailure`.
- Added `prepare_stage_attempt`, which binds planned inputs, computes the
  fingerprint, allocates log/result paths, writes the worker request, writes
  latest-compatible input/fingerprint records, prepares the workspace, and
  records a pending prepared stage status without constructing or running stage
  code.
- Added `read/write_stage_worker_request`, `read/write_stage_worker_result`,
  and local worker handoff path helpers to the run-store surface.

New tests cover model validation, redaction, store protocol conformance, local
store persistence/readback, and real prepared-attempt state written through the
prepare API.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright with config extra, default test harness, config-extra test harness, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.90s |
| unit | passed | 569 | 0 | 0 | 1 | 0 | 6.32s |
| contract | passed | 53 | 0 | 0 | 2 | 0 | 2.45s |
| integration | passed | 15 | 0 | 0 | 7 | 7 | 2.22s |
| e2e | passed | 16 | 0 | 0 | 0 | 0 | 7.58s |
| config-extra | passed | 397 | 0 | 0 | 0 | 703 | 18.02s |

## Risks / Follow-Ups

- Direct worker CLI behavior, subprocess launch, preflight availability checks,
  and result readback are intentionally deferred to later v5 phases.
- Full attempt archive directories, retries, locks/leases, and timeout policy
  remain deferred to their later roadmap owners.
