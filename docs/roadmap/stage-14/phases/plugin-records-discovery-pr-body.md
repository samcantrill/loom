## Summary

@samcantrill

This PR adds Loom's generic plugin discovery foundation. It introduces an import-light `loom.plugins` package with public plugin group constants, immutable entry point metadata records, duplicate/failure/load result records, plugin-specific errors, deterministic metadata-only listing, and explicit selected loading.

The implementation keeps Phase 1 generic: it does not add recipe or codec registry adapters, CLI commands, preflight wiring, provenance persistence, or future extension loaders. Loading remains caller-selected and trusted-code only, while summaries omit loaded Python objects.

## Acceptance Criteria

- [x] Public plugin group constants and generic discovery records are available from `loom.plugins`.
- [x] Entry point listing is deterministic and metadata-only.
- [x] Explicit loading supports selected records, strict failures, best-effort aggregation, and duplicate detection before target imports.
- [x] Public summaries include safe metadata and omit loaded objects and traceback internals.
- [x] Package, unit, and contract tests cover the new API and import boundaries.

## Implementation Notes

- Added `src/loom/plugins/entrypoints.py` for group constants, `PluginRecord`, `LoadedPlugin`, `PluginDuplicate`, `PluginFailure`, `PluginLoadResult`, deterministic `list_entry_points(...)`, selected `load_entry_points(...)`, and plain summary helpers.
- Added `src/loom/plugins/errors.py` for discovery, invalid entry point, load, duplicate, and registration-context errors with plugin metadata context.
- Exposed the public API from `src/loom/plugins/__init__.py` without re-exporting it from root `loom`.
- Kept discovery dependency-light by using standard-library `importlib.metadata` and fakeable providers for tests.

New tests implemented:

- Package API and import-boundary tests for `loom.plugins`, root import safety, and lower-layer boundaries.
- Unit coverage for constants, deterministic listing, duplicate detection, selected-only loading, strict and best-effort modes, failure summaries, and object omission.
- Contract coverage for metadata-only listing, explicit selected loading, duplicate fail-closed behavior, and future group metadata namespace behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra harness, and build completed successfully. |
| `make test-summary` | Passed | `build/test-summary.md` generated 2026-05-15T02:20:22+00:00 with overall status `passed`. |
| GitHub checks | Passed | PR #156 `checks` workflow completed successfully. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| package | passed | 85 | 0 | 0 | 1 | 0 | 86 | 16.23s | 18% |
| unit | passed | 1099 | 0 | 0 | 7 | 1 | 1106 | 53.64s | 75% |
| contract | passed | 204 | 0 | 0 | 2 | 0 | 206 | 12.17s | 58% |
| integration | passed | 155 | 0 | 0 | 8 | 13 | 163 | 53.35s | 63% |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 | 37.98s | 63% |
| config-extra | passed | 438 | 0 | 0 | 0 | 1595 | 438 | 78.24s | 65% |
| Overall | passed | 2024 | 0 | 0 | 18 | 1611 | 2042 | 251.60s | - |

## Risks / Follow-Ups

- Plugin group names become public metadata contracts.
- Package/version metadata remains best-effort when entry points lack distribution context.
- Recipe and codec registry adapters, CLI/preflight presentation, and future group readiness labels are intentionally deferred to later Stage 14 phases.
