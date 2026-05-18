## Summary

Implements the Stage 21 cleanup command surface. `loom clean RUN_URI` now previews or deletes selected per-run cleanup candidates, and `loom gc COLLECTION` does candidate-level collection cleanup without deleting whole run directories.

The CLI stays thin: it parses bounded selector flags, prompts or honors `--yes`, builds `CleanupDeleteIntent` records, calls public cleanup APIs, and formats public cleanup report/result records as text or JSON.

## Acceptance Criteria

- [x] `loom clean` defaults to dry-run and requires `--delete` plus confirmation or `--yes` for mutation.
- [x] `loom gc` aggregates candidate cleanup across selected runs and keeps collection paths as discovery inputs only.
- [x] Cleanup CLI JSON output uses plain-data cleanup report/result records.
- [x] Feature docs describe cleanup safety, retention hints, preflight warnings, collection GC, and Stage 21 deferrals.

## Implementation Notes

- Added `src/loom/cli/clean.py`, `src/loom/cli/gc.py`, and shared cleanup CLI selector/confirmation helpers.
- Added bounded selector flags for age, recorded timestamp bounds, candidate kind, reason, retention mode, stage, artifact, tag, and metadata equality.
- Kept cleanup command imports lazy enough that CLI help and direct cleanup CLI imports do not load `loom.pipeline`.
- Updated docs for CLI commands, cleanup safety, retention metadata, cleanup preflight checks, and run-catalog discovery boundaries.

New tests implemented:

- Unit tests for parser wiring, selector conversion, text/JSON output, and command registration.
- Contract tests for cleanup CLI JSON payloads.
- Integration/e2e tests for authority-backed dry-run/delete and collection GC flows over synthetic runs.
- Package import-boundary coverage for cleanup CLI modules.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | passed | Wrote `build/test-summary.md` with suite totals below |
| GitHub checks | pending | To be recorded after PR creation |

### Test Suite Summary

| Suite | Result | Evidence |
| --- | --- | --- |
| package | passed | 108 passed, 1 skipped |
| unit | passed | 1394 passed, 7 skipped, 1 deselected |
| contract | passed | 274 passed, 2 skipped |
| integration | passed | 170 passed, 8 skipped, 13 deselected |
| e2e | passed | 46 passed, 2 deselected |
| config-extra | passed | 449 passed, 3 skipped, 2001 deselected |

## Risks / Follow-Ups

- Whole-run deletion, provider deletion, automatic retention enforcement, arbitrary cleanup query parsing, and cleanup-specific event sink loading remain deferred.
- `loom gc` discovery can grow paging later if collections become large; Stage 21 keeps the orchestration candidate-level and eager.
