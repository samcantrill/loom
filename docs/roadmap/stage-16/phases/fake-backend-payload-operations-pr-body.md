# Summary

- Adds explicit artifact-store payload operation contracts: `UPLOAD`/`DOWNLOAD`, strict payload request/result records, and a companion `ArtifactStoreBackendPayloadHandler` protocol.
- Exports the new store-facing names through `loom.pipeline.stores` without changing existing metadata-only backend handler requirements.
- Adds fake object-store and tracking-system contract coverage for upload, download, materialize, checksum verification, read-only unsupported behavior, missing credential diagnostics, checksum mismatch, and redaction.

# Tests

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores/test_artifact_backends.py tests/contracts/test_artifact_store_payload_operations_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py` | passed, 73 tests |
| `uv run pytest tests/contracts/test_artifact_store_backend_contract.py tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_artifact_materialization_contract.py` | passed, 8 tests |
| `git diff --check` | passed |
| Ruff changed-file check | passed |
| Pyright changed-file check | passed, 0 errors |
| `make validate-pr` | passed: Ruff, Pyright, default suite `1691 passed, 26 skipped, 18 deselected`, config-extra `440 passed, 1728 deselected`, build |
| `make test-summary` | passed: package `97 passed, 1 skipped`; unit `1184 passed, 7 skipped, 1 deselected`; contract `239 passed, 2 skipped`; integration `156 passed, 8 skipped, 13 deselected`; e2e `43 passed, 2 deselected`; config-extra `440 passed, 1728 deselected` |

# Assumptions And Risks

- Real backend adapters remain out of scope; fake handlers prove the shared contract shape without optional SDKs.
- Payload-capable handlers opt into the companion protocol, so existing metadata-only backend handlers remain valid.
- Phase 4 owns bundle/preflight integration of these payload operation results.
