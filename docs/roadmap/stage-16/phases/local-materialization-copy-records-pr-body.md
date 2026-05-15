## Summary

Implements Stage 16 Phase 2 by adding store-owned local artifact materialization records and copy-only execution. The new `artifact_materialization` store module exposes strict request/result records, derived location/read-model projections, checksum evidence, and fail-closed unsupported results for non-copy local policies.

This keeps artifact refs metadata-only and leaves fake remote backend behavior, bundle/preflight integration, CLI flags, retry policy, and cleanup for later phases.

## Acceptance Criteria

- [x] Local copy materialization succeeds with structured `OperationResult` evidence and derived materialized/staging facts.
- [x] Checksum mismatch fails clearly and does not copy payload bytes.
- [x] Non-copy policies return structured unsupported results without silently falling back to copy.
- [x] Public store exports and import boundaries remain stable.
- [x] Existing materialization read-model integration remains compatible.

## Implementation Notes

- Added `src/loom/pipeline/stores/artifact_materialization.py` with `ArtifactMaterializationRequest`, `ArtifactMaterializationResult`, `LocalMaterializationPolicy`, `materialize_artifact_locally`, and projection helpers.
- Uses `loom.operations` from Phase 1 for operation status, diagnostics, and evidence.
- Supports regular-file copy materialization only. Existing targets require `overwrite=True`; same-source/target, target directories, missing sources, unsupported URI schemes, and checksum mismatches fail closed.
- Projects successful copies into derived `ArtifactLocationSummary(kind=materialized, authority=derived)` and `MaterializedRef(kind=artifact_payload)` values without mutating authority truth.

New tests implemented:

- Unit tests for copy success, checksum evidence, checksum mismatch, missing source, overwrite behavior, unsupported non-copy policies, and derived projections.
- Contract tests for strict request/result wire shapes and unsupported policy results.
- Package/export tests for the new public store names.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py` | Passed | `76 passed` |
| `uv run pytest tests/integration/pipeline/test_artifact_store_split.py tests/integration/pipeline/test_materialization_read_models.py` | Passed | `5 passed` |
| `uv run pytest tests/unit/loom/pipeline/stores/test_store_errors.py tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py` | Passed | `27 passed` |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed |
| `make test-summary` | Passed | Suite summary generated in `build/test-summary.md` |
| GitHub checks | Pending | To be reported after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 97 | 0 | 0 | 1 | 0 |
| unit | passed | 1182 | 0 | 0 | 7 | 1 |
| contract | passed | 235 | 0 | 0 | 2 | 0 |
| integration | passed | 156 | 0 | 0 | 8 | 13 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 |
| config-extra | passed | 440 | 0 | 0 | 0 | 1722 |

## Risks / Follow-Ups

- Directory materialization, hardlink/symlink/reflink/move/cache-promotion policies, fake backend payload operations, bundle/preflight integration, retry policy, and cleanup remain future-phase work.
- The local collision policy is intentionally simple: fail unless `overwrite=True`.
