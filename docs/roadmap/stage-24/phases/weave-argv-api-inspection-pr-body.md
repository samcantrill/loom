## Summary

This completes Stage 24 Phase 3 by exposing the public argv config shorthand helpers for project-specific CLIs. The top-level package adds only `compose_config_from_argv(...)`; `weave.api` exposes the inspection helper, result/warning records, and selected parsed argv records for callers that need detailed diagnostics.

The helpers wrap the Phase 1 parser and Phase 2 scoped-overlay composition path, including `argv=None`, command choices, `allow_unparsed`, recipe catalogs, raw source snapshot opt-in, structured config errors, and helper-local warnings. Warnings remain result-only data and are not persisted into composed configs, manifests, provenance, source artifacts, raw snapshots, fingerprints, or run artifacts.

## Acceptance Criteria

- [x] Public top-level export is limited to `compose_config_from_argv(...)`.
- [x] `weave.api` exposes argv inspection, result/warning records, and selected parsed argv records.
- [x] Public helpers cover command/base parsing, value overrides, scoped overlays, recipes, raw snapshots, unparsed args, warnings, and structured errors.
- [x] Non-argv composition and inspection behavior remains unchanged.
- [x] `docs/features/config.md` documents shipped helper behavior and explicit deferrals.

## Implementation Notes

- Added frozen result/warning records and public wrapper helpers in `packages/weave/src/weave/api.py`.
- Updated lazy top-level exports in `packages/weave/src/weave/__init__.py` for only `compose_config_from_argv`.
- Kept helper warnings local to `ConfigArgvCompositionResult` and `ConfigArgvInspectionResult`.
- Documented project-CLI usage, trailing-slash scoped overlays, lookup rules, inspection/audit behavior, and deferred CLI/Hydra/schema work.

New tests implemented:

- Import/package tests for the narrow top-level surface and detailed `weave.api` exports.
- Unit tests for argv result/warning validation and `argv=None` handling.
- Contract tests for structured error context and argv inspection stage behavior.
- Integration tests for public helper composition, warnings, scoped overlays, recipes, raw snapshots, and unparsed args.
- E2E public API coverage for project-style argv compose/inspect flows.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default pytest, config-extra, weave, weave examples, and builds passed; observed rows included default `1983 passed, 108 deselected`, config-extra `128 passed, 3 skipped, 1986 deselected`, weave `415 passed`, weave examples `8 passed`. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall `2534 passed, 0 failed, 0 errors, 3 skipped, 2088 deselected, 2537 total, 321.14s`. |
| GitHub checks | Pending | PR opened for CI. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 112 | 0 | 0 | 0 | 4 | 112 | 26.69s |
| unit | passed | 1402 | 0 | 0 | 0 | 2 | 1402 | 48.76s |
| contract | passed | 252 | 0 | 0 | 0 | 8 | 252 | 14.03s |
| integration | passed | 170 | 0 | 0 | 0 | 82 | 170 | 47.78s |
| e2e | passed | 47 | 0 | 0 | 0 | 6 | 47 | 43.90s |
| config-extra | passed | 128 | 0 | 0 | 3 | 1986 | 131 | 131.19s |
| weave | passed | 415 | 0 | 0 | 0 | 0 | 415 | 4.81s |
| weave-examples | passed | 8 | 0 | 0 | 0 | 0 | 8 | 3.97s |
| Overall | passed | 2534 | 0 | 0 | 3 | 2088 | 2537 | 321.14s |

## Risks / Follow-Ups

- Warning heuristics are intentionally conservative and may miss some mistaken no-slash overlay intent.
- First-party CLI behavior, Loom CLI integration, Hydra/defaults semantics, persisted argv warning artifacts, and source artifact schema changes remain deferred.
