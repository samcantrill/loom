## Summary

This PR closes the Phase 5 operational mutation paths by moving CLI workers,
submitted jobs, prepared-run continuation, and SLURM helper paths onto the
authority-backed runtime store.

SLURM live submission now fails before scheduler submission when the selected
authority backend cannot prove live submitted-worker semantics. Dry-run scripts,
manifests, logs, and worker handoff files remain local materialization
artifacts rather than lifecycle authority.

## Changes

- Routed `loom stage run`, `loom stage-job run`, `loom prepared-run continue`,
  SLURM dry-run/live preparation, cancellation, and scheduler status helpers
  through authority-backed run-store construction.
- Threaded authority attempt, lease, owner, and fencing metadata through
  submitted stage-job and worker paths.
- Added live SLURM authority admission that rejects unsupported transitional
  authority profiles before fake or real `sbatch` submission.
- Updated worker finalization to validate authority metadata before execution
  when the store supports fenced stage-job authority.
- Updated tests, fixtures, and public examples so runtime mutation uses
  authority-backed stores while local files remain artifact/materialization
  surfaces.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| package | 57 passed, 1 skipped |
| unit | 837 passed, 1 skipped |
| contract | 108 passed, 2 skipped |
| integration | 90 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1134 deselected |

## Assumptions And Risks

- The transitional SQLite-backed authority remains insufficient for live
  multi-host submitted workers, so live SLURM submission is intentionally
  fail-closed until the later service/database backend phases.
- Local SLURM manifests and generated scripts are still persisted for
  inspection and submission evidence, but submitted-operation records remain
  the lifecycle path.
