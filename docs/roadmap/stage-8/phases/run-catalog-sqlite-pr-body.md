## Summary

Implements the v8 Phase 3 private SQLite sidecar and rebuild path for local run
collections. `RunCatalog.open(path).rebuild()` now direct-scans authoritative
run directories, writes derived catalog state under `.loom_catalog/catalog.sqlite`,
and returns `CatalogIndexResult` with indexed/skipped counts plus scan warnings.

The sidecar remains private and disposable. It stores summary payloads,
filterable facts, stage/artifact/submitted-operation rows, and run freshness
evidence for later current-list refresh work without making SQLite authoritative.

## Acceptance Criteria

- [x] The catalog DB can be created, rebuilt, deleted, and rebuilt again from
  run directories.
- [x] SQLite schema details remain private to `loom.runs._sqlite`.
- [x] Multiple catalog instances can rebuild/read the same sidecar without
  corrupting it in local smoke coverage.
- [x] Rebuild results include warnings for invalid or skipped runs.
- [x] Recoverable corrupt or incompatible DB state is rebuilt without mutating
  run-store truth.

## Implementation Notes

- Added private SQLite storage helpers with schema metadata, best-effort WAL,
  `busy_timeout`, short write transactions, and sidecar-file-only recovery.
- Extended private direct-scan/extraction helpers to carry validated
  `RunFreshnessRecord` evidence for rebuild while preserving public
  `scan_current()` output.
- Added `RunCatalog.rebuild()` as a lazy facade method so `import loom.runs`
  still does not import `sqlite3`.
- Persisted normalized filter facts for the Phase 4 exact-match filter set
  without implementing current listing or query semantics in this phase.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra test harness, and build passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 55 | 0 | 0 | 1 | 0 | 56 | 7.84s |
| unit | passed | 748 | 0 | 0 | 1 | 0 | 749 | 17.53s |
| contract | passed | 73 | 0 | 0 | 2 | 0 | 75 | 2.75s |
| integration | passed | 51 | 0 | 0 | 7 | 10 | 58 | 9.86s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 36 | 16.21s |
| config-extra | passed | 413 | 0 | 0 | 0 | 966 | 413 | 33.59s |

## Risks / Follow-Ups

- `RunCatalog.list()`, refresh-on-read, indexed filtering, comparison, and CLI
  commands remain intentionally deferred to later v8 phases.
- The SQLite schema is private but still an internal compatibility surface for
  Phase 4; future schema changes should keep rebuild recovery straightforward.
- WAL is best-effort and tested through behavior, not platform-specific journal
  files.
