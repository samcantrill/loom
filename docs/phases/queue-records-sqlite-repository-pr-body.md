## Summary

Implements Phase 5 by adding the first `loom.queue` package, versioned queue records, a private FIFO selector, and the built-in SQLite queue repository. The new records cover pools, queues, run intent, launch contracts, queue items, claims, dispatch handles, cancellation records, audit events, and recovery records.

The SQLite repository persists canonical queue item JSON alongside indexed FIFO columns and audit events. It supports enqueue/idempotency, FIFO claim, dispatch-handle persistence, terminal completion, cancellation, recovery scans, and restart-safe reads without importing authority private storage, queue service code, launch adapters, or config extras.

## Acceptance Criteria

- [x] Queue DB persists and recovers queue state across restart.
- [x] Records are versioned and reject unsafe or unknown fields.
- [x] Repository operations support enqueue, claim, dispatch-handle persistence, terminal completion, cancellation, and recovery scans.
- [x] Launch-contract records preserve drift-detection and delegated-verification fields without redefining queue item schema.

## Implementation Notes

- Added dependency-light public exports under `loom.queue`.
- Added strict `to_dict(...)` and `from_dict(...)` model contracts with schema-version and unknown-field validation.
- Added one-queue-per-pool topology validation and a private FIFO selection helper.
- Added `SQLiteQueueRepository` with schema metadata, WAL best effort, queue item JSON storage, FIFO indexes, audit events, and schema-version guard behavior.
- Kept service/client/controller, launch adapters, authority leasing, queue config loading, CLI, retries, priorities, and multi-queue policy out of scope.

New tests implemented:

- Package import/export and lightweight import-boundary coverage for `loom.queue`.
- Unit coverage for model serialization, validation, topology rules, cancellation evidence slots, and FIFO selection.
- Contract coverage for public queue record and repository operation shapes.
- Integration coverage for SQLite persistence, FIFO claim, dispatch, completion, cancellation, recovery scans, restart recovery, conflict handling, and schema guard behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 5 pytest | Passed | 61 passed across package, queue unit, queue contract, and SQLite repository integration tests. |
| Targeted Ruff/Pyright | Passed | New queue package and targeted tests passed. |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness passed with 1391 passed, 19 skipped, 14 deselected; config-extra passed with 434 passed, 1421 deselected; build passed. |
| `make test-summary` | Passed | Overall 1852 passed, 12 skipped, 1433 deselected. |
| GitHub checks | Pending | To be recorded after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 72 | 0 | 0 | 1 | 0 |
| unit | passed | 1004 | 0 | 0 | 1 | 0 |
| contract | passed | 162 | 0 | 0 | 2 | 0 |
| integration | passed | 140 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 434 | 0 | 0 | 0 | 1421 |

## Risks / Follow-Ups

- Queue service/client/controller behavior intentionally starts in Phase 6.
- Managed resource leasing and local dispatch intentionally start in Phase 7.
- Delegated SLURM dispatch and adapter proof semantics intentionally start in Phase 8.
