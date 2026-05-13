## Summary

- Added `SlurmQueueDispatchAdapter` for delegated queue dispatch through existing fakeable SLURM command runners.
- Persisted external SLURM job handles, first downstream status-read evidence, delegated handoff facts, and conservative launch-verification reports.
- Extended active queue inspection with a handoff-complete signal so foreground drain can stop after durable delegated handoff while daemon-style dispatch can continue to later queued delegated work.
- Added delegated SLURM cancellation evidence, missing-authority diagnostics, status read-model output, and docs clarifying that SLURM-pending delegated work does not hold Loom leases by default.

## Tests

| Suite | Evidence |
| --- | --- |
| Targeted Phase 8 pytest | `55 passed` |
| Targeted Ruff | passed |
| Targeted Pyright | `0 errors` |
| `make validate-pr` | passed: Ruff, Pyright, default harness, config-extra harness, build |
| `make test-summary` package | `75 passed, 1 skipped` |
| `make test-summary` unit | `1030 passed, 1 skipped, 1 deselected` |
| `make test-summary` contract | `167 passed, 2 skipped` |
| `make test-summary` integration | `145 passed, 8 skipped, 11 deselected` |
| `make test-summary` e2e | `40 passed, 2 deselected` |
| `make test-summary` config-extra | `436 passed, 1460 deselected` |

## Assumptions And Risks

- Delegated SLURM launch snapshots use trusted `script_path` data and optional dependency job IDs; bundle transport and SSH submit hosts remain deferred.
- Missing authority-run visibility is reported as diagnostic evidence and does not block durable delegated handoff.
- `scancel` failures are recorded as unknown cancellation outcomes rather than proven remote termination.
