## Summary

This PR implements Phase 3 of v3 local diagnostics.

It adds a read-only store-owned inspection facade for discovered stages and
persisted run state, then builds diagnostics summaries and CLI commands on top
of that facade. `loom status RUN_URI` now summarizes local run status, stages,
failures, log path hints, provenance availability, and artifact counts.
`loom logs RUN_URI STAGE` reads bounded stdout/stderr content, supports
`--stream`, `--tail`, `--paths`, and text/JSON output.

The implementation keeps status/log inspection local-only and read-only. It
does not add artifact commands, live log following, scheduler state, or
persisted diagnostics reports.

## Acceptance Criteria

- [x] Successful and failed local runs can be summarized without importing
  project stage modules.
- [x] Status output includes run status, stage summaries, failure details, log
  path hints, provenance availability, and artifact counts.
- [x] Logs output includes resolved paths and bounded content.
- [x] `loom logs --paths` shows availability without reading content.
- [x] Missing stages and missing log content fail clearly.
- [x] Diagnostics/CLI stage discovery uses the store-owned inspection facade.
- [x] JSON output uses stable CLI envelopes and plain-data diagnostics payloads.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default isolated suite passed with 542 passed, 13 skipped, and 9 deselected; config-extra passed with 393 passed and 557 deselected; uv build produced sdist and wheel artifacts. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md` with all reported suites passing. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 48 | 0 | 0 | 1 | 0 |
| unit | passed | 445 | 0 | 0 | 1 | 0 |
| contract | passed | 40 | 0 | 0 | 2 | 0 |
| integration | passed | 9 | 0 | 0 | 6 | 9 |
| e2e | passed | 15 | 0 | 0 | 0 | 0 |
| config-extra | passed | 393 | 0 | 0 | 0 | 557 |
| Overall | passed | 950 | 0 | 0 | 10 | 566 |

## Risks / Follow-Ups

- Log display remains bounded and attempt-agnostic.
- Status is a local persisted-state view, not scheduler or live job state.
- Phase 4 owns artifact inspection and full diagnostic workflow coverage.
