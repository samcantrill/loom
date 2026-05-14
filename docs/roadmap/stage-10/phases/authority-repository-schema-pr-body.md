## Summary

This PR adds the private SQLite repository foundation for the authority service. It initializes `authority.sqlite3` under an explicit service state directory, persists schema version and service generation metadata, returns typed repository identity facts, and classifies missing, older, newer, and corrupt repositories with structured compatibility failures.

The repository remains an implementation detail below the service boundary. `loom.authority` stays lightweight, does not import `sqlite3` or the private repository module, and no run or stage lifecycle behavior is introduced in this phase.

## Acceptance Criteria

- [x] A private SQLite repository can be initialized under an explicit service state directory.
- [x] Schema version and service generation facts are persisted and readable.
- [x] Transactions are explicit and covered for commit and rollback behavior.
- [x] Repository compatibility failures are structured for later protocol/server mapping.
- [x] Public package roots do not expose or eagerly import the private repository.

## Implementation Notes

- Added `src/loom/authority/_repository.py` with schema constants, repository identity records, compatibility failure records, SQLite connection setup, schema bootstrap, and explicit write transactions.
- Kept repository symbols private to the module rather than exporting them from `loom.authority`.
- Preserved Phase 4 boundaries by avoiding FastAPI route wiring, run lifecycle tables, stage lifecycle tables, supervisor registry behavior, and runtime factory adoption.

New tests implemented:

- Package import-boundary tests for `loom.authority` privacy and lightweight imports.
- Unit tests for compatibility failure serialization, generation tokens, database name validation, identity serialization, and missing database handling.
- Contract tests proving compatibility failure codes map into existing protocol rejection envelopes.
- Integration tests for file-backed initialization/reopen behavior, transaction commit/rollback, missing DB, newer schema, older schema, corrupt DB, and incomplete metadata.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1218 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1247 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Overall 1664 passed, 12 skipped, 1258 deselected. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 65 | 0 | 0 | 1 | 0 | 66 | 13.88s |
| unit | passed | 895 | 0 | 0 | 1 | 0 | 896 | 47.42s |
| contract | passed | 135 | 0 | 0 | 2 | 0 | 137 | 14.76s |
| integration | passed | 110 | 0 | 0 | 8 | 10 | 118 | 63.91s |
| e2e | passed | 39 | 0 | 0 | 0 | 1 | 39 | 36.55s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1247 | 420 | 64.77s |
| Overall | passed | 1664 | 0 | 0 | 12 | 1258 | 1676 | 241.30s |

## Risks / Follow-Ups

- The repository currently stores only schema and identity metadata; run lifecycle tables are intentionally left for Phase 5.
- Compatibility-to-HTTP mapping is intentionally deferred until the FastAPI mutation and readiness phases.
