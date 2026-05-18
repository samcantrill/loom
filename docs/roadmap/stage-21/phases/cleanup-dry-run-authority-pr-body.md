## Summary

Adds Phase 2 of Stage 21 cleanup and retention:

- side-effect-free cleanup dry-run planning over authoritative cleanup candidates
- explicit cleanup report/result facts with append/list authority contracts
- SQLite, service, repository, HTTP client, in-memory, and execution adapter plumbing for cleanup facts
- diagnostics inspection visibility for cleanup reports and results

Default cleanup planning remains read-only. Durable dry-run evidence is recorded only through the explicit report-recording API.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed |

Suite evidence from `build/test-summary.md`:

| Suite | Result |
| --- | --- |
| package | 107 passed, 1 skipped |
| unit | 1378 passed, 7 skipped, 1 deselected |
| contract | 270 passed, 2 skipped |
| integration | 166 passed, 8 skipped, 13 deselected |
| e2e | 44 passed, 2 deselected |
| config-extra | 449 passed, 3 skipped, 1974 deselected |

## Assumptions And Risks

- Cleanup result facts are introduced as append/list scaffolding for Phase 3; Phase 2 does not produce mutating cleanup results.
- Managed-root discovery stays caller-provided and conservative.
- This PR intentionally excludes deletion, event projection, CLI commands, collection GC, and retention preflight behavior.
