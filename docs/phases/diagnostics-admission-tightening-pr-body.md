## Summary

Implements the Phase 3 `v10-post` diagnostics, coordination, and resource-admission tightening needed before queue status and managed pools depend on these contracts. The patch adds a non-mutating resource-limit read path through workspace coordination stores and authority service routing, plus a read-only reconciliation helper for managed-pool validation.

Resource admission now keeps the existing `admitted`, `rejected`, and `blocked` outcomes while adding machine-readable `reason_code` and `reason_context` fields. Diagnostics coverage locks the distinct offline-evidence and deferred-finalization source labels already used by preflight policy output.

## Acceptance Criteria

- [x] Read-only surfaces clearly distinguish authoritative, local, deferred, and offline sources.
- [x] Resource admission preserves `admitted`, `rejected`, and `blocked` outcomes with machine-readable reasons.
- [x] Coordination mutation remains authority-owned; managed-pool validation can read/reconcile limits without calling `set_resource_limit(...)`.

## Implementation Notes

- Added `WorkspaceCoordinationStore.read_resource_limit(...)` and propagated it through SQLite coordination, service coordination, authority repository, mutation service, FastAPI mutation routes, and `AuthorityClient`.
- Reused `ConcurrencyCounter` for resource-limit reads so the read path carries counter name, active usage, configured limit, and revision without a new protocol result field.
- Added `reconcile_resource_limits(...)` with `success`, `mismatch`, `missing_limit`, and `unavailable_authority` outcomes for future managed-pool preflight and dispatch validation.
- Kept resource-limit provisioning out of scope; queue phases still must not mutate authority resource limits.

New tests implemented:

- Source-label regression coverage for offline-first and deferred-finalization preflight policy details.
- Unit coverage for admission reason codes and resource-limit reconciliation outcomes.
- Contract and integration coverage for non-mutating resource-limit reads across in-memory, SQLite, service, and authority HTTP paths.
- Package API contract updates for the new public route constant and reconciliation helper.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness passed with 1369 passed, 19 skipped, 14 deselected; config-extra passed with 434 passed, 1399 deselected; build passed. |
| `make test-summary` | Passed | Overall 1830 passed, 12 skipped, 1411 deselected. |
| GitHub checks | Pending | To be recorded after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 70 | 0 | 0 | 1 | 0 |
| unit | passed | 997 | 0 | 0 | 1 | 0 |
| contract | passed | 157 | 0 | 0 | 2 | 0 |
| integration | passed | 132 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 434 | 0 | 0 | 0 | 1399 |

## Risks / Follow-Ups

- Resource-limit reconciliation intentionally validates finite pre-provisioned limits only; later provisioning policy remains a separate roadmap concern.
- Main queue managed-pool work should use the new read/reconcile surface and must continue to avoid authority-side limit mutation.
