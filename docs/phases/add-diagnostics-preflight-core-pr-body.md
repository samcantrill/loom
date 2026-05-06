## Summary

@samcantrill

This PR introduces the Phase 1 local diagnostics foundation: an import-light
`loom.diagnostics` public API with preflight status, severity, group, request,
check result, aggregate result, and plain-data serialization models.

It also adds the non-persistent local preflight runner for config, pipeline,
selectors, `RUN_URI`, artifact store, codec registry, local executor, and
filesystem input checks. The change intentionally does not add CLI commands,
change `loom run`, persist preflight reports, or add status/log/artifact
inspection facades.

## Acceptance Criteria

- [x] Public Python APIs can run full local preflight and selected check groups.
- [x] Results expose stable `PASS`, `WARN`, `FAIL`, and `SKIP` statuses,
  severities, check IDs, messages, details, and plain-data serialization.
- [x] Unknown and empty explicit group selections fail clearly.
- [x] Overall status aggregation is deterministic.
- [x] Missing optional `RUN_URI` skips only run-path-dependent checks.
- [x] No preflight result is written to the run store by default.
- [x] Lower layers do not import `loom.diagnostics`, and diagnostics root import
  remains lightweight.
- [x] `docs/structure.md` documents the diagnostics package boundary.

## Implementation Notes

`src/loom/diagnostics/models.py` defines the public value models, stable local
group names, stable Phase 1 check IDs, request validation, group normalization,
aggregate status rules, and `to_dict()` serialization. The package root exposes
the public API without importing the heavier runner implementation until
`run_preflight()` is called.

`src/loom/diagnostics/preflight.py` runs local best-effort checks through public
lower-layer APIs, caching config, pipeline, and run URI resolution inside the
request context. Run-path checks report `SKIP` when no `RUN_URI` is supplied,
and artifact-store probing constructs local store objects without creating run
documents or directories.

New tests implemented:

- Package tests for public exports, import-light diagnostics root behavior, and
  lower-layer import direction.
- Unit tests for result model validation, plain-data details, check ID
  contracts, aggregation, group selection, missing `RUN_URI` skips, and
  filesystem failures.
- Contract tests for stable status, severity, group, check ID, and serialized
  preflight payload shape.
- Integration tests for full local preflight, selected groups, omitted
  `RUN_URI` behavior, selector validation failures, and no run-store writes.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default isolated suite passed with 523 passed and 13 skipped; config-extra passed with 380 passed and 541 deselected; uv build produced sdist and wheel artifacts. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md` with all reported suites passing. |
| GitHub checks | Pending | PR creation step will start CI after the branch is pushed. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 46 | 0 | 0 | 1 | 0 |
| unit | passed | 429 | 0 | 0 | 1 | 0 |
| contract | passed | 39 | 0 | 0 | 2 | 0 |
| integration | passed | 9 | 0 | 0 | 6 | 0 |
| e2e | passed | 14 | 0 | 0 | 0 | 0 |
| config-extra | passed | 380 | 0 | 0 | 0 | 541 |
| Overall | passed | 917 | 0 | 0 | 10 | 541 |

## Risks / Follow-Ups

- Preflight remains local-only, best-effort, and non-persistent by design.
- Phase 2 owns CLI `loom preflight` wiring and `loom run` reuse.
- Phase 3 and Phase 4 own status/log/artifact inspection surfaces.
