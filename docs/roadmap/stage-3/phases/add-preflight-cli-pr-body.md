## Summary

This PR implements Phase 2 of v3 local diagnostics.

It adds `loom preflight CONFIG` with compact text output, JSON result envelopes,
`--strict`, optional `--run-uri`, and repeatable `--check GROUP` selection. The
command reuses the Phase 1 diagnostics runner and reports failed diagnostics as
a result payload rather than a persisted report.

It also reuses diagnostics from `loom run` before execution. Fresh runs now
allocate the implicit local run URI once before preflight and pass that same URI
to execution. Resume keeps the existing `store.open_run()` validation path and
does not run the fresh-run path-availability check against an existing run
directory.

## Acceptance Criteria

- [x] Users can run explicit local preflight before execution.
- [x] `--strict` fails when warning diagnostics are present.
- [x] `--check` limits diagnostics to selected groups and rejects unknown
  groups through CLI error formatting.
- [x] `--run-uri` enables run-path checks; omitting it still runs general
  readiness checks.
- [x] Text output includes aggregate and per-check status, check ID, and
  message.
- [x] JSON output uses existing envelope conventions with a stable diagnostics
  payload.
- [x] `loom run` reuses diagnostics without duplicating check logic in CLI code.
- [x] Default `loom run` URI allocation is deterministic and shared by preflight
  and execution.
- [x] Preflight warnings or failures do not create run-store records.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default isolated suite passed with 532 passed, 13 skipped, and 5 deselected; config-extra passed with 389 passed and 547 deselected; uv build produced sdist and wheel artifacts. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md` with all reported suites passing. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 47 | 0 | 0 | 1 | 0 |
| unit | passed | 436 | 0 | 0 | 1 | 0 |
| contract | passed | 40 | 0 | 0 | 2 | 0 |
| integration | passed | 9 | 0 | 0 | 6 | 5 |
| e2e | passed | 15 | 0 | 0 | 0 | 0 |
| config-extra | passed | 389 | 0 | 0 | 0 | 547 |
| Overall | passed | 936 | 0 | 0 | 10 | 552 |

## Risks / Follow-Ups

- Preflight remains local-only, best-effort, and non-persistent by design.
- `loom run` uses a minimal preflight subset; later runtime/resource or
  remote-store checks remain future work.
- Phase 3 owns `loom status` and `loom logs`; Phase 4 owns artifact inspection
  and the full diagnostic workflow evidence.
