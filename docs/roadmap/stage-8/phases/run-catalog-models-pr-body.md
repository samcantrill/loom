## Summary

Implements the v8 Phase 1 catalog foundation: an import-light public
`loom.runs` namespace with the `RunCatalog` facade, catalog errors, immutable
metadata models, exact-match filter vocabulary, result envelopes, comparison
shapes, and the initial stable catalog warning-code taxonomy.

Adds store-owned run freshness metadata so later catalog reads can validate
derived summaries against authoritative run-store writes without coupling the
runner or executors to a collection catalog database.

## Acceptance Criteria

- [x] `from loom.runs import RunCatalog` and public model imports are stable and
  import-light.
- [x] Public models validate required fields, preserve `run_uri` as canonical
  identity, and serialize to plain JSON-safe data.
- [x] Filter models represent the v8 exact-match filter set.
- [x] Catalog warning models include the required machine-readable codes:
  `invalid_run`, `unreadable_run`, `partial_run`, `actively_changing_run`,
  `disappeared_run`, `unsupported_schema`, `stale_or_corrupt_catalog`, and
  `unrecoverable_catalog_error`.
- [x] Local run-store writes update a store-owned freshness token for
  catalog-relevant metadata changes.
- [x] Store freshness code does not import `loom.runs` or `loom.cli`.
- [x] `docs/structure.md` documents the `loom.runs` boundary.

## Implementation Notes

- Added `src/loom/runs/` with public catalog models, warning/result envelopes,
  placeholder `RunCatalog.open(path)`, and deferred-method catalog errors for
  behavior implemented in later phases.
- Added `RunFreshnessRecord` and `RunFreshnessStore` under
  `loom.pipeline.stores`, plus local `freshness.json` updates through a shared
  `LocalRunStore` helper after catalog-relevant writes.
- Explicitly excluded event append and stage log writes from freshness updates
  because v8 catalog summaries do not derive current facts from event logs or
  log contents.
- Updated package, unit, contract, and integration tests for import boundaries,
  public model serialization, store protocol exports, freshness mutation, and a
  realistic local run-store lifecycle.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra test harness, and build passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 55 | 0 | 0 | 1 | 0 | 56 | 7.92s |
| unit | passed | 741 | 0 | 0 | 1 | 0 | 742 | 17.04s |
| contract | passed | 73 | 0 | 0 | 2 | 0 | 75 | 3.02s |
| integration | passed | 45 | 0 | 0 | 7 | 10 | 52 | 9.09s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 36 | 16.70s |
| config-extra | passed | 413 | 0 | 0 | 0 | 953 | 413 | 32.70s |
| Overall | passed | 1363 | 0 | 0 | 11 | 964 | 1374 | 86.47s |

## Risks / Follow-Ups

- `RunCatalog.list`, direct scan, SQLite rebuild, metadata comparison behavior,
  and CLI commands are intentionally deferred to later v8 phases.
- Freshness correctness depends on catalog-relevant store writes continuing to
  use the shared local-store marker helper.
