## Summary

Adds Phase 3 of Stage 21 cleanup and retention:

- `execute_cleanup` with required `CleanupDeleteIntent`
- local-only deletion for selected targets after execution-time safety rechecks
- cleanup result fact persistence before event projection
- compact cleanup report/result audit event projection helpers
- optional `RuntimeEventDispatcher` support where sink failures remain observe-only

This intentionally excludes CLI commands, collection GC, preflight warnings, remote deletion, and whole-run deletion.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed |

Suite evidence from `build/test-summary.md`:

| Suite | Result |
| --- | --- |
| package | 107 passed, 1 skipped |
| unit | 1384 passed, 7 skipped, 1 deselected |
| contract | 271 passed, 2 skipped |
| integration | 167 passed, 8 skipped, 13 deselected |
| e2e | 44 passed, 2 deselected |
| config-extra | 449 passed, 3 skipped, 1982 deselected |

## Assumptions And Risks

- Deletion remains local-filesystem only and relies on trusted managed roots plus existing cleanup safety checks.
- Result facts are the durable evidence source; event projection happens only after result fact append.
- Event sink failures are recorded through existing observer-failure paths and do not fail cleanup.
