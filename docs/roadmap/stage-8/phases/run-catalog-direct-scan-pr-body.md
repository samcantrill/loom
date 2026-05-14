## Summary

Implements the v8 Phase 2 direct-scan path for local run collections. Callers
can now use `RunCatalog.open(path).scan_current()` to receive current
metadata-only run summaries plus machine-readable warnings without requiring a
SQLite sidecar or CLI command.

The implementation keeps direct scan as a private reusable source-of-truth path
for later SQLite rebuilds: discovery lives in `loom.runs._scan`, extraction and
freshness validation live in `loom.runs._extract`, and public imports remain
lightweight.

## Acceptance Criteria

- [x] Python API callers can open a local collection and receive direct-scan
  summaries plus warnings.
- [x] Direct scan does not import project code or load artifact payloads.
- [x] Invalid and partial directories are warnings by default, not whole-query
  failures.
- [x] Runs that change during extraction are retried once and then reported as
  `actively_changing_run` rather than accepted as current.
- [x] Direct scan helpers are private and reusable by later SQLite rebuild
  phases.

## Implementation Notes

- Added `RunCatalog.scan_current()` while leaving `RunCatalog.list()` reserved
  for the later indexed current-list phase.
- Added private local collection discovery that ignores `.loom_catalog` and
  maps invalid, partial, disappeared, unreadable, unsupported-schema, and
  actively-changing conditions into `CatalogWarning` values.
- Added metadata-only extraction from run-store APIs for run status/timestamps,
  user metadata/tags, config and pipeline fingerprints, git commit,
  executor/backend identity, stage status/fingerprints, artifact
  identities/checksums, and submitted-operation summaries.
- Added unit and integration coverage for warning classification, freshness
  retry behavior, public result serialization, and realistic local run summary
  extraction.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra test harness, and build passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 55 | 0 | 0 | 1 | 0 | 56 | 7.70s |
| unit | passed | 743 | 0 | 0 | 1 | 0 | 744 | 17.67s |
| contract | passed | 73 | 0 | 0 | 2 | 0 | 75 | 2.75s |
| integration | passed | 47 | 0 | 0 | 7 | 10 | 54 | 9.55s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 36 | 16.13s |
| config-extra | passed | 413 | 0 | 0 | 0 | 957 | 413 | 33.16s |
| Overall | passed | 1367 | 0 | 0 | 11 | 968 | 1378 | 86.97s |

## Risks / Follow-Ups

- Direct scans may be slow for large collections until the Phase 3 SQLite
  sidecar and rebuild path lands.
- Some optional summary fields remain `None` when authoritative store metadata
  does not expose a usable value.
- `RunCatalog.list()`, SQLite persistence, filters, comparison, and CLI
  commands are intentionally deferred to later v8 phases.
