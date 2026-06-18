## Summary

- Adds the versioned `stage_15_artifact_summaries` run-exchange extension for
  Stage 15 external, published, location, and unsupported-materialization
  artifact summaries.
- Preserves the extension through metadata-only bundle export, inspect,
  import-record construction, import provenance, and historical local artifact
  indexes without changing the Stage 12 manifest schema.
- Surfaces unsupported remote materialization as warning diagnostics and keeps
  metadata-only export/import from attempting payload downloads, credential
  checks, backend discovery, or optional SDK imports.
- Documents the run-catalog bundle boundary for Stage 15 summaries.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs/test_artifact_metadata.py tests/unit/loom/runs/test_bundle_export.py tests/unit/loom/runs/test_bundle_import.py tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py tests/package/test_runs_api.py` | Passed: 26 passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs tests/unit/loom/cli tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py` | Passed outside sandbox: 172 passed / 4 skipped |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed outside sandbox: Ruff, Pyright, default harness, config-extra harness, and build |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: package 90 passed / 1 skipped; unit 1165 passed / 7 skipped / 1 deselected; contract 227 passed / 2 skipped; integration 156 passed / 8 skipped / 13 deselected; e2e 43 passed / 2 deselected; config-extra 440 passed / 1690 deselected |

## Notes

- Extension-field mapping was selected over a schema revision because existing
  strict Stage 12 extension fields carry the Stage 15 summaries without
  changing archive identity, payload, checksum, or member semantics.
- Imported runs remain historical-only; Stage 16 owns explicit payload
  materialization behavior.
