## Summary

- Persist selected reliability policy facts at the stage-attempt boundary so
  ordinary runs expose the policy selected for an executed attempt.
- Add read-only reliability summaries to diagnostics and existing CLI surfaces:
  `loom status` reports compact stage reliability facts, while
  `loom backend inspect` reports reliability counts and keeps raw authoritative
  records in JSON.
- Finalize Stage 19 feature docs for reliability inspection, status/backend
  presentation, store/read-model facts, and Stage 20 event plus Stage 21
  cleanup/retention deferrals.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py tests/unit/loom/diagnostics/test_backend_diagnostics.py tests/unit/loom/cli/test_status_logs.py tests/unit/loom/cli/test_backend.py` | Passed, `55 passed` |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package tests/contracts tests/unit/loom/pipeline tests/unit/loom/diagnostics tests/unit/loom/cli` | Passed, `1343 passed` |
| `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/pipeline tests/integration/diagnostics tests/e2e/test_cli_core.py tests/e2e/test_cli_runs_e2e.py` | Passed, `174 passed` |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: package `102`, unit `1276`, contract `256`, integration `159`, e2e `43`, config-extra `447` |

## Assumptions And Risks

- Inspection remains read-only. This phase does not add retry, cleanup,
  retention, event-sink, notification, or provider-specific commands.
- Status text intentionally stays compact. Full reliability records are
  available through JSON diagnostics/read models.
