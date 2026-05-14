## Summary

This PR adds `SQLitePerRunAuthorityStore`, the first concrete run-local authority backend behind the Phase 1 `PerRunAuthorityStore` contract. The backend uses Python's standard-library SQLite driver, keeps its database and schema private inside the run root, and persists guarded run/stage state, attempts, leases, submitted operations, output commits, artifact facts, audit evidence, revisions, and snapshots for one run, with recovery scans and cleanup-candidate read surfaces.

The implementation preserves Phase 2 boundaries: it does not wire the serial runner to the backend, flip public defaults, add CLI/read-model/catalog integration, implement workspace or sweep coordination, publish a SQL schema contract, migrate old runs, or change Phase 1 protocols and read models.

## Acceptance Criteria

- [x] SQLite satisfies the per-run authority contract through Phase 1 models.
- [x] Run-local database placement, private schema checks, and loud unsupported-schema diagnostics are implemented.
- [x] Guarded transitions, monotonic attempts, active lease fencing, submitted operations, atomic output commits, recovery scans, cleanup-candidate reads, and revisioned snapshots are handled through the SQLite authority backend.
- [x] Package, unit, contract, and integration coverage exercises import boundaries, schema policy, conformance behavior, concurrency, portability, leases, commits, and recovery.

## Implementation Notes

- Added `src/loom/pipeline/stores/sqlite_authority.py` with `SQLitePerRunAuthorityStore`; the root `loom.pipeline.stores` package remains import-light and does not import `sqlite3`.
- Uses a private run-root database with schema metadata tied to `AUTHORITY_SCHEMA_VERSION`; missing, invalid, older, newer, or incomplete active-state schemas fail through authority schema diagnostics rather than being silently migrated or repaired.
- Uses short SQLite write transactions for revision bumps and guarded state changes, including run/stage transitions, attempt allocation, controller/stage leases, submitted-operation persistence, audit events, recovery scans, and snapshots.
- Rejects attempt allocation inside the same write transaction when a stage already has an output commit or is in a terminal stage state, preserving durable commit semantics after stage success.
- Enforces active stage lease ownership with owner and fencing-token checks; expired, released, failed, stale, and foreign leases are rejected for renewal/release/failure and output commits.
- Records successful stage output commits atomically with the active lease, attempt id, fencing token, output commit, artifact facts, terminal stage status, backend revision, and lease release.
- Reconstructs returned Phase 1 records from the current `run_uri`, so ordinary local run-root movement keeps the authority database openable without treating absolute paths as identity.
- Documents SQLite's local/same-host limits and unsupported cross-run, shared-filesystem, multi-host, remote-authority, and global-counter capabilities in `docs/features/run-store.md`.

New tests implemented:

- Package coverage keeps store exports stable and verifies `loom.pipeline.stores` does not import `sqlite3`.
- Unit coverage checks schema policy, incomplete existing schemas, capability declarations, revision advancement, lease fencing, expired lease rejection, audit sequence evidence, output-commit guards, and post-commit/terminal-stage attempt allocation rejection.
- Contract coverage runs the per-run authority conformance behavior against both the in-memory store and SQLite.
- Integration coverage checks concurrent attempt allocation, lease fencing across store instances, run-root movement portability, submitted-operation reconstruction, recovery scans, and revisioned snapshots.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Rerun during blocker-resolution pass; Ruff, Pyright, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` at `2026-05-09T16:00:25+00:00`; overall 1439 passed, 0 failed, 0 errors, 11 skipped, 1037 deselected in 130.10s. |
| GitHub checks | Stale after blocker-resolution commit | Previously completed CI `checks` run passed at `2026-05-09T15:47:10Z`; the pushed blocker-resolution commit requires a fresh GitHub run. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 56 | 0 | 0 | 1 | 0 | 7.67s |
| unit | passed | 776 | 0 | 0 | 1 | 0 | 16.58s |
| contract | passed | 86 | 0 | 0 | 2 | 0 | 4.39s |
| integration | passed | 68 | 0 | 0 | 7 | 10 | 52.94s |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 15.36s |
| config-extra | passed | 416 | 0 | 0 | 0 | 1026 | 33.16s |
| Overall | passed | 1439 | 0 | 0 | 11 | 1037 | 130.10s |

## Risks / Follow-Ups

- SQLite authority is intentionally local or same-host only; stronger shared-filesystem, multi-host, remote, and high write-concurrency semantics remain future backend work.
- V9 schema policy is loud-fail only. Future schema changes need explicit migration design rather than implicit repair or downgrade behavior.
- Runner integration, public default/read-path flips, backend diagnostics CLI, materialization helpers, bounded parallel execution, and workspace/sweep coordination are deferred to later v9 phases.
