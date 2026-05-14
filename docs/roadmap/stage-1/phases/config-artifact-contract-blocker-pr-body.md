## Summary

- Normalizes `CompositionManifest.recipe_manifest` during construction through
  the same plain-data path used by serialization.
- Rejects nested non-plain recipe manifest payloads with
  `ConfigProvenanceError` at construction time.
- Records the user-authorized blocker-resolution pass in the Phase 1 artifact.

## Validation

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/config/test_config_artifacts.py` | Passed, 9 tests |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_config_artifact_contract.py` | Passed, 6 tests |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed, wrote `build/test-summary.md` |

## Notes

- Scope is limited to the post-merge Phase 1 artifact-contract blocker.
- No Phase 2 behavior, include loading, override semantics, resolver behavior,
  persistence, or CLI work is included.
