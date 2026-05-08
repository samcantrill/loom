## Summary

- Enables `loom run --executor slurm-single-job` live submission by preparing the existing v6 single-job artifacts, calling `sbatch --parsable`, and persisting scheduler job identity.
- Adds live SLURM submission result/output contracts plus submitted-operation registry and run `SUBMITTED` status updates.
- Updates preflight and executor descriptors so live single-job submission is supported while `slurm-afterok` live submission remains deferred to Phase 4.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | passed: package 52 passed/1 skipped; unit 714 passed/1 skipped; contract 65 passed/2 skipped; integration 37 passed/7 skipped/9 deselected; e2e 23 passed; config-extra 411 passed/891 deselected |

## Notes

- Real SLURM is not required by the default test suite; fake runners cover scheduler success and failure paths.
- `slurm-afterok` live DAG submission, scheduler-aware status, and cancellation remain out of scope for later v7 phases.
