## Summary

- Rejects recursive YAML aliases during config loading before directive
  scanning can recurse indefinitely.
- Raises structured `ConfigLoadError` context for the alias-cycle case using the
  Phase 2 `non_plain_data` code.
- Adds a regression test for a self-referential YAML alias and records the
  post-merge blocker-resolution evidence in the Phase 2 artifact.

## Validation

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/unit/loom/config/test_load.py tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py tests/unit/loom/config/test_compose.py` | Passed, 29 tests |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed, wrote `build/test-summary.md` |

## Notes

- Scope is limited to the post-merge Phase 2 recursive YAML alias blocker.
- No Phase 3 behavior, includes, overlays, overrides, schema validation,
  resolver execution, recipes, persistence, CLI, or pipeline changes are
  included.
