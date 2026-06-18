# Summary

- Adds explicit bundle export materialization through `RunBundleExportOptions(materialize_payloads=True)` and a supplied `ArtifactStoreBackendPayloadHandler`.
- Keeps metadata-only bundle export/import as the default, with no implicit downloads, no provider SDKs, and no catalog or CLI scope changes.
- Preserves materialization operation evidence in bundle manifest and payload-reference extensions, including original source URIs for materialized refs.
- Adds a cheap artifact-backend materialization readiness preflight check that verifies payload-handler protocol support without calling payload operations.

# Tests

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit/loom/runs tests/unit/loom/diagnostics tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_run_bundle_import_contract.py tests/contracts/test_cli_runs_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/integration/pipeline/test_run_bundle_export_inspect.py tests/integration/pipeline/test_run_bundle_import.py tests/integration/diagnostics/test_cli_preflight.py tests/integration/diagnostics/test_diagnostics_preflight_integration.py` | passed, 131 tests, 2 skipped |
| `make validate-pr` | passed: Ruff, Pyright, default suite `1695 passed, 26 skipped, 18 deselected`, config-extra `440 passed, 1732 deselected`, build |
| `make test-summary` | passed: package `97 passed, 1 skipped`; unit `1186 passed, 7 skipped, 1 deselected`; contract `241 passed, 2 skipped`; integration `156 passed, 8 skipped, 13 deselected`; e2e `43 passed, 2 deselected`; config-extra `440 passed, 1732 deselected` |

# Assumptions And Risks

- Real backend adapters, credentials, retry/timeout policy, cleanup, catalog projection changes, and CLI materialization flags remain out of scope.
- Materialization is fail-closed: exports error when an opt-in materialization request lacks a valid payload handler, is unsupported, fails, or returns an invalid result.
- Phase 5 owns final no-backend user-facing handles and docs/API hardening.
