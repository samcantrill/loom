## Summary

This phase adds opt-in bounded local parallel stage execution while preserving
serial execution as the default. Python callers can set
`max_parallel_stages` in run execution settings, and `loom run` now accepts
`--max-parallel-stages N` plus `--failure-policy stop-on-first-failure` or
`--failure-policy continue-independent`.

Parallel execution is available only for safe local runs with an authoritative
backend that advertises the required claim, lease, commit, revision, recovery,
consistency, and per-run coordination capabilities. Explicit unsupported
backend, executor, or stdout/stderr-capture combinations fail before launching
workers instead of silently falling back to serial execution.

## Acceptance Criteria

- [x] Default and explicit `max_parallel_stages=1` runs stay serial.
- [x] Explicit bounded parallel runs execute independent static DAG branches
  against the SQLite authority backend.
- [x] Stage success is recorded only after committed outputs and artifact
  facts.
- [x] Failed dependencies block dependents, while `continue-independent` can
  continue unrelated branches.
- [x] Capability, executor, capture, and invalid-policy failures are loud and
  structured.
- [x] Lease renewal and interruption paths avoid marking ambiguous work as
  succeeded.

## Implementation Notes

- Added validated `ParallelExecutionOptions` over durable
  `RunOptions.execution.settings`, including normalization for
  `continue-independent` / `continue_independent`.
- Added CLI run flags that feed the same runtime settings without changing
  existing serial command behavior.
- Added a controller-owned bounded scheduler in `PipelineRunner` using
  deterministic ready-stage selection and `ThreadPoolExecutor` only as local
  worker mechanics.
- Reused authority-backed attempts, stage leases, lease renewal, output
  commits, artifact facts, snapshots, and capability diagnostics as the
  correctness boundary.
- Preserved the existing serial path for omitted or single-stage parallelism
  and rejected explicit parallel requests for unsupported executors, missing
  authority backends, missing backend capabilities, or local stream capture.

New tests implemented:

- Package/API coverage for new runtime and execution exports.
- Unit coverage for option validation, CLI option mapping, capability
  preflight, unsupported parallel combinations, failure-policy validation, and
  serial-path preservation.
- Integration coverage for SQLite-backed parallel DAGs, lease renewal,
  interruption, default stop-on-first-failure behavior, and
  `continue-independent` scheduling.
- E2E CLI smoke coverage for bounded local parallel execution.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Manager-provided post-refine gate: Ruff, Pyright, default harness (`1072 passed, 18 skipped, 14 deselected`), config-extra harness (`420 passed, 1101 deselected`), and `uv build` succeeded. |
| `make test-summary` | Passed | `build/test-summary.md` generated at `2026-05-09T22:57:09+00:00`; overall `1518 passed`, `0 failed`, `0 errors`, `12 skipped`, `1112 deselected`. |
| GitHub checks | Pending | CI starts after the branch is pushed and the PR is opened. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 57 | 0 | 0 | 1 | 0 | 58 | 7.83s |
| unit | passed | 828 | 0 | 0 | 1 | 0 | 829 | 30.02s |
| contract | passed | 93 | 0 | 0 | 2 | 0 | 95 | 4.51s |
| integration | passed | 81 | 0 | 0 | 8 | 10 | 89 | 58.92s |
| e2e | passed | 39 | 0 | 0 | 0 | 1 | 39 | 19.16s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1101 | 420 | 38.84s |
| Overall | passed | 1518 | 0 | 0 | 12 | 1112 | 1530 | 159.28s |

## Risks / Follow-Ups

- Explicit bounded parallelism is limited to safe local in-process execution;
  subprocess and scheduler-backed parallel execution remain out of scope.
- SQLite coordination remains local or same-host only. Distributed
  controllers, retries, speculative execution, dynamic DAG mutation, and
  workspace/sweep coordination remain later work.
- Local stdout/stderr capture is rejected for explicit parallel runs because
  the current capture mode redirects process-global streams.
