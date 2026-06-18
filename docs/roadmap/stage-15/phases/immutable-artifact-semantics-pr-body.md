# External Artifact Interface - Phase 3: Immutable Artifact Semantics

## Summary

- Added `loom.pipeline.stores.immutable_artifacts` for metadata-only external
  declaration and published-record validation.
- Added fail-closed capability admission and explicit immutable artifact lookup
  helpers over the Phase 1 records and Phase 2 backend handler contract.
- Added validation-policy comparison and conversion helpers that project
  external/published records into compatible `ArtifactRef` metadata without
  payload movement.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_immutable_artifacts.py tests/contracts/test_immutable_artifact_semantics_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py` | 68 passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom tests/unit/loom/pipeline/stores tests/contracts` | 1376 passed / 10 skipped |
| `make validate-pr` | passed |
| `make test-summary` | passed: overall 2110 passed / 18 skipped / 1695 deselected |

## Scope Notes

- Lookup remains opt-in through explicit helper calls; planner cache reuse,
  runner wiring, preflight, catalog/bundle preservation, exchange metadata, and
  payload materialization are left to later phases.
- Metadata-only validation does not require credentials, network access, SDKs,
  or payload probes.
- Missing, unknown, and unsupported required capabilities fail closed for
  selected operations.
