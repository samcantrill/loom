## Summary

This PR adds `SQLitePerRunAuthorityStore`, the first concrete run-local authority backend behind the Phase 1 `PerRunAuthorityStore` contract. The backend uses Python's standard-library SQLite driver, keeps its database and schema private inside the run root, and persists guarded run/stage state, attempts, leases, submitted operations, output commits, artifact facts, cleanup candidates, audit evidence, recovery facts, revisions, and snapshots for one run.

The implementation preserves Phase 2 boundaries: it does not wire the serial runner to the backend, flip public defaults, add CLI/read-model/catalog integration, implement workspace or sweep coordination, publish a SQL schema contract, migrate old runs, or change Phase 1 protocols and read models.

## Acceptance Criteria

- [x] SQLite satisfies the per-run authority contract through Phase 1 models.
- [x] Run-local database placement, private schema checks, and loud unsupported-schema diagnostics are implemented.
- [x] Guarded transitions, monotonic attempts, active lease fencing, submitted operations, atomic output commits, recovery scans, and revisioned snapshots are persisted transactionally.
- [x] Package, unit, contract, and integration coverage exercises import boundaries, schema policy, conformance behavior, concurrency, portability, leases, commits, and recovery.

## Implementation Notes

- Added `src/loom/pipeline/stores/sqlite_authority.py` with `SQLitePerRunAuthorityStore`; the root `loom.pipeline.stores` package remains import-light and does not import `sqlite3`.
- Uses a private run-root database with schema metadata tied to `AUTHORITY_SCHEMA_VERSION`; missing, invalid, older, newer, or incomplete active-state schemas fail through authority schema diagnostics rather than being silently migrated or repaired.
- Uses short SQLite write transactions for revision bumps and guarded state changes, including run/stage transitions, attempt allocation, controller/stage leases, submitted-operation persistence, audit events, cleanup candidates, recovery scans, and snapshots.
- Enforces active stage lease ownership with owner and fencing-token checks; expired, released, failed, stale, and foreign leases are rejected for renewal/release/failure and output commits.
- Records successful stage output commits atomically with the active lease, attempt id, fencing token, output commit, artifact facts, terminal stage status, backend revision, and lease release.
- Reconstructs returned Phase 1 records from the current `run_uri`, so ordinary local run-root movement keeps the authority database openable without treating absolute paths as identity.
- Documents SQLite's local/same-host limits and unsupported cross-run, shared-filesystem, multi-host, remote-authority, and global-counter capabilities in `docs/features/run-store.md`.

New tests implemented:

- Package coverage keeps store exports stable and verifies `loom.pipeline.stores` does not import `sqlite3`.
- Unit coverage checks schema policy, incomplete existing schemas, capability declarations, revision advancement, lease fencing, expired lease rejection, audit sequence evidence, and output-commit guards.
- Contract coverage runs the per-run authority conformance behavior against both the in-memory store and SQLite.
- Integration coverage checks concurrent attempt allocation, lease fencing across store instances, run-root movement portability, submitted-operation reconstruction, recovery scans, and revisioned snapshots.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Recorded in phase notes after implementation refinement: Ruff, Pyright, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` at `2026-05-09T15:30:43+00:00`; overall 1437 passed, 0 failed, 0 errors, 11 skipped, 1035 deselected in 129.75s. |
| GitHub checks | Not run | PR was not opened in this expanded-path draft pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 56 | 0 | 0 | 1 | 0 | 7.74s |
| unit | passed | 774 | 0 | 0 | 1 | 0 | 16.66s |
| contract | passed | 86 | 0 | 0 | 2 | 0 | 4.11s |
| integration | passed | 68 | 0 | 0 | 7 | 10 | 53.14s |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 15.61s |
| config-extra | passed | 416 | 0 | 0 | 0 | 1024 | 32.49s |
| Overall | passed | 1437 | 0 | 0 | 11 | 1035 | 129.75s |

## Risks / Follow-Ups

- SQLite authority is intentionally local or same-host only; stronger shared-filesystem, multi-host, remote, and high write-concurrency semantics remain future backend work.
- V9 schema policy is loud-fail only. Future schema changes need explicit migration design rather than implicit repair or downgrade behavior.
- Runner integration, public default/read-path flips, backend diagnostics CLI, materialization helpers, bounded parallel execution, and workspace/sweep coordination are deferred to later v9 phases.
