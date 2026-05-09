## Summary

Implements the v8 Phase 4 current listing API. `RunCatalog.open(path).list()`
now returns `ListRunsResult` after refreshing the private SQLite sidecar from
authoritative run-store metadata during the call, then querying exact-match
filters from the refreshed catalog.

The implementation keeps the correctness guarantee simple: list calls perform a
fresh direct scan, replace derived SQLite rows in a short transaction, then
query by `run_uri`-ordered SQL. This prevents stale rows from being returned
while preserving private SQLite filter behavior.

## Acceptance Criteria

- [x] Public API list calls return current summaries and warnings.
- [x] Returned summaries are validated/refreshed against run-store freshness
  during the read operation.
- [x] Stale, changed, new, deleted, missing-DB, and corrupt-DB cases are
  reconciled before query results are returned.
- [x] Exact-match filters are evaluated through the API and backed by SQLite.
- [x] Ordinary invalid/partial candidates remain nonfatal warnings.
- [x] Multiple catalog instances can list/rebuild without corrupting the
  sidecar in deterministic local smoke coverage.

## Implementation Notes

- Added `RunCatalog.list(filters=...)` with lazy private SQLite loading so
  `import loom.runs` remains import-light.
- Added private current-list helpers for sidecar refresh, SQL filter
  compilation, deterministic summary queries, and filter validation.
- Implemented conjunctive exact-match filters for run status, tag key/value,
  config fingerprint, pipeline fingerprint, git commit, stage status, artifact
  identity/checksum, executor, and backend.
- Added contract, unit, and integration coverage including a lightweight
  1,000-run synthetic fixture for indexed filter behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra test harness, and build passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 55 | 0 | 0 | 1 | 0 | 56 | 6.92s |
| unit | passed | 751 | 0 | 0 | 1 | 0 | 752 | 16.93s |
| contract | passed | 74 | 0 | 0 | 2 | 0 | 76 | 3.05s |
| integration | passed | 57 | 0 | 0 | 7 | 10 | 64 | 52.58s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 36 | 15.39s |
| config-extra | passed | 413 | 0 | 0 | 0 | 976 | 413 | 31.63s |

## Risks / Follow-Ups

- Current listing uses full direct-scan refresh before SQLite filtering. This is
  intentionally correctness-first; targeted incremental refresh remains future
  internal work if list latency becomes unacceptable.
- `RunCatalog.compare()` and CLI commands remain deferred to later v8 phases.
- Public query semantics are intentionally narrow: ANDed exact-match filters
  only, no sort controls, OR groups, range filters, or fuzzy search.
