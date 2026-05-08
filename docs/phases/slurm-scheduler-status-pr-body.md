## Summary

- Adds `loom status RUN_URI --jobs` for scheduler-aware inspection of the latest submitted SLURM operation.
- Implements SLURM status parsing and precedence across final run/store state, `sacct`, `squeue`, and persisted manifest/snapshot fallback.
- Persists artifact-safe scheduler snapshots in the live manifest and compact latest status metadata in submitted-operation backend metadata without rewriting core run or stage statuses.
- Reports job IDs, scheduler state, exit code, dependency/log paths, backend metadata, and warnings for uncertainty, stale data, conflicts, dependency blocking, and worker-never-started cases.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed: default 895 passed / 17 skipped / 10 deselected; config-extra 412 passed / 920 deselected; build succeeded |
| `make test-summary` | Passed: package 52 passed / 1 skipped; unit 724 passed / 1 skipped; contract 69 passed / 2 skipped; integration 43 passed / 7 skipped / 10 deselected; e2e 32 passed; config-extra 412 passed / 920 deselected |
| Targeted Phase 5 slice | Passed: 90 SLURM/status tests |
| Package import/API slice | Passed: 35 tests |

## Notes

- Ordinary `loom status RUN_URI` remains scheduler-free.
- Status inspection is read-only for core run/stage state; it only appends backend-owned status metadata.
- Real-cluster status acceptance remains deferred to Phase 7.
