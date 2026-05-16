# Summary

- Adds explicit `StageAttemptTransactionState` values and backward-compatible transaction serialization for older records without state.
- Records reliability status-detail and transaction facts for prepared, running, staged, committed, failed, cancelled, and commit-failed lifecycle points.
- Adds execution-owned failure classification and embeds the classification fact into durable stage failure details.
- Delegates reliability fact writes through `AuthorityBackedSerialRunStore`, preserving SQLite/service authority facts and falling back to local facts for the current HTTP authority reliability-write gap.

# Tests

| Command | Result |
| --- | --- |
| `uv run pytest tests/package/test_pipeline_reliability_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/reliability/test_reliability_models.py tests/contracts/test_reliability_contract.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/integration/pipeline/test_local_execution_failures.py` | Passed, `94 passed, 1 skipped` |
| `uv run pytest tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/stores` | Passed, `335 passed` |
| `uv run pytest tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py` | Passed, `4 passed, 2 skipped` |
| `make validate-pr` | Passed Ruff, Pyright, default suite (`1791 passed, 26 skipped, 18 deselected`), config-extra (`446 passed, 1828 deselected`), and build |
| `make test-summary` | Passed: package `102`, unit `1259`, contract `256`, integration `159`, e2e `43`, config-extra `446` |

# Assumptions And Risks

- HTTP authority reliability mutation routes remain outside this phase; serial execution records local reliability facts for that adapter until the service route catches up.
- Retry automation and timeout enforcement remain out of scope for Phase 3.
