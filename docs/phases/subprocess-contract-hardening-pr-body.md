## Summary

Implements Phase 5 of v5 by hardening the local/subprocess worker contract with
missing edge-case tests, adding runnable subprocess examples, and documenting
current guarantees plus deferred behavior boundaries.

The PR adds deterministic subprocess executor coverage for invalid worker
results, mismatched worker-result identity, launch errors, signal metadata, and
redacted command metadata. It also adds integration evidence for
local/subprocess success equivalence and subprocess failure diagnostics through
status/log inspection.

## Acceptance Criteria

- [x] Component and cross-component behavior has expanded test evidence.
- [x] Examples are runnable locally with synthetic, domain-neutral stages.
- [x] Examples demonstrate local versus subprocess success, subprocess failure
  diagnostics, and direct `loom stage run` against a prepared stage.
- [x] Docs state the current v5 subprocess guarantees and no-sandboxing/trusted
  config boundaries.
- [x] Docs identify deferred behavior owners and revisit triggers for retries,
  timeouts, parallelism, SLURM, containers, plugins, remote stores, cleanup,
  attempt archives, and stronger locking.

## Implementation Notes

- Added hardening tests in `tests/unit/loom/pipeline/executors/test_subprocess_executor.py`.
- Added local/subprocess equivalence coverage in
  `tests/integration/pipeline/test_subprocess_executor_integration.py`.
- Added subprocess failure status/log inspection coverage in
  `tests/integration/diagnostics/test_cli_status_logs.py`.
- Added `examples/pipelines/subprocess-run/` with three smoke entrypoints:
  success comparison, failure diagnostics, and direct worker execution.
- Updated execution/testing docs for v5 trust, privacy, and deferred behavior
  boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused tests | Passed | `uv run --extra config pytest ...` passed with 53 tests. |
| `make validate-pr` | Passed | Ruff, Pyright with config extra, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Passed | CI `checks` completed successfully for PR #81. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.35s |
| unit | passed | 599 | 0 | 0 | 1 | 0 | 6.73s |
| contract | passed | 55 | 0 | 0 | 2 | 0 | 1.99s |
| integration | passed | 21 | 0 | 0 | 7 | 8 | 3.37s |
| e2e | passed | 18 | 0 | 0 | 0 | 0 | 7.50s |
| config-extra | passed | 405 | 0 | 0 | 0 | 743 | 19.51s |

## Risks / Follow-Ups

- The direct worker example prepares a stage attempt through Python APIs because
  v5 does not expose a standalone prepare-attempt CLI.
- Examples are local and synthetic by design; real scheduler/container/remote
  examples remain later-version work.
- Deferred reliability and executor behavior is documented but intentionally
  not implemented in this phase.
