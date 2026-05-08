## Summary

Finishes v7 SLURM live operations with final preflight hardening, skipped-by-default real-cluster acceptance coverage, and updated user-facing guidance for live submit/status/cancel workflows.

This keeps default validation cluster-free while documenting and testing how maintainers can opt into real SLURM coverage.

## Acceptance Criteria

- [x] Preflight exposes stable checks for optional SLURM commands, active submitted work, and writable generated paths.
- [x] Fake-command coverage exercises live submit, scheduler-aware status, cancellation, and artifact-safe metadata.
- [x] Real SLURM acceptance tests are marked, skipped by default, and explicitly gated by environment variables.
- [x] SLURM, preflight, CLI, testing, and example docs describe the implemented v7 surface.

## Implementation Notes

- Added stable preflight IDs for `squeue`, `sacct`, `scancel`, active submitted-operation detection, and generated-path writability.
- Added an e2e fake-runner flow that submits an afterok run, queries scheduler-aware status, cancels submitted jobs, and asserts a secret resolver value is not persisted in run artifacts.
- Added `tests/slurm_acceptance/` with explicit `LOOM_RUN_SLURM_ACCEPTANCE=1` and `LOOM_SLURM_ACCEPTANCE_ROOT` gating.
- Added `examples/execution/slurm-live/` as a manual cluster template for live submit, status, cancel, and site-specific SLURM options.

New tests implemented:

- Unit and contract coverage for new preflight IDs and outcomes.
- E2E fake-command submit/status/cancel flow with artifact-safety assertion.
- Opt-in real SLURM acceptance cases for single-job success, afterok dependency success, and sleeping-job cancellation.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default suite 915 passed / 17 skipped / 14 deselected; config-extra 413 passed / 943 deselected; build succeeded. |
| `make test-summary` | Passed | Overall 1353 passed / 11 skipped / 954 deselected across package, unit, contract, integration, e2e, and config-extra. |
| `uv run pytest tests/slurm_acceptance -m slurm` | Passed by skip gate | 3 tests collected and skipped because real SLURM acceptance env vars were not set. |
| GitHub checks | Passed | PR #94 checks passed before the final phase-artifact metadata update. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 52 | 0 | 0 | 1 | 0 | 53 |
| unit | passed | 734 | 0 | 0 | 1 | 0 | 735 |
| contract | passed | 73 | 0 | 0 | 2 | 0 | 75 |
| integration | passed | 45 | 0 | 0 | 7 | 10 | 52 |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 36 |
| config-extra | passed | 413 | 0 | 0 | 0 | 943 | 413 |
| Overall | passed | 1353 | 0 | 0 | 11 | 954 | 1364 |

## Risks / Follow-Ups

- Real SLURM acceptance remains opt-in and was not executed against this local environment.
- Exact submitted-operation selectors, cleanup commands, retries, controller mode, job arrays, remote stores, and containers remain deferred.
