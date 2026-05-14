## Summary

- Added a shared SLURM live authority guard and require a service-profile authority-backed run store before live submission, scheduler status persistence, or submitted-job cancellation mutation.
- Record authority mutation-source metadata on live SLURM submitted-operation state, status snapshots, and cancellation snapshots.
- Tightened live-worker admission so the `direct_database` deployment profile is rejected instead of being treated as a live submitted-worker authority.
- Updated SLURM unit, integration, and e2e fixtures to use deterministic authority-backed stores for live mutation paths and to prove local stores fail closed.
- Extended dry-run command assertions so single-job and afterok handoffs preserve explicit authority arguments.

## Test Evidence

| Suite | Result |
| --- | --- |
| Focused Ruff | passed |
| Focused Pyright | passed |
| Focused SLURM unit/integration tests | passed, 100 tests in 6.29s |
| Focused optional-config SLURM e2e tests | passed outside the restricted sandbox, 14 tests in 11.05s |
| `make validate-pr` | passed; Ruff, Pyright, default suite, config-extra suite, and package build completed |
| `make test-summary` package | passed, 69 passed, 1 skipped |
| `make test-summary` unit | passed, 954 passed, 1 skipped |
| `make test-summary` contract | passed, 146 passed, 2 skipped |
| `make test-summary` integration | passed, 127 passed, 8 skipped, 10 deselected |
| `make test-summary` e2e | passed, 39 passed, 2 deselected |
| `make test-summary` config-extra | passed, 422 passed, 1338 deselected |

## Assumptions And Risks

- Authority-backed local test stores stand in for service-owned mutation semantics; CLI live admission remains strict and still rejects the default local service fixture for production-style live workers.
- Single-job SLURM submitted commands still target fail-closed prepared-run continuation until a later authoritative replay design exists.
- Broader diagnostics/read-only source-label UX remains Phase 14 scope.
