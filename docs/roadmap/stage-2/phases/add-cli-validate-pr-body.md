# CLI Core - Phase 3: Validate Command

## Summary

Adds `loom validate` as the first behavior-bearing v2 CLI command:

- Static-by-default config composition plus pipeline validation.
- Optional `--check-targets` consent boundary for trusted target construction.
- Pipeline-owned validation and stage-target facades.
- Config-owned generic `_target_` check facade.
- Text and JSON validate output with top-level warnings.
- JSON error warning propagation when target checks fail after emitting the opt-in warning.

## Scope Notes

- `loom validate` does not execute stages, allocate run URIs, write run state, or create validation report files.
- Default validate does not construct project targets.
- Stage factory targets are checked through pipeline-owned construction semantics; remaining generic `_target_` blocks are checked through config-owned instantiation semantics.

## Validation

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit/loom/cli tests/unit/loom/config/test_target_checks.py tests/unit/loom/pipeline/test_pipeline_validation.py tests/package/test_import_boundaries.py tests/package/test_config_api.py tests/package/test_pipeline_api.py -q` | Passed, 52 passed, 1 skipped |
| `uv run --extra config pytest tests/integration/config/test_cli_validate.py -q` | Passed, 3 passed |
| `uv run ruff check .` | Passed |
| `uv run --extra config pyright` | Passed, 0 errors |
| `make validate-pr` | Passed |
| `make test-summary` | Passed, overall 865 passed, 9 skipped, 497 deselected |

## Risks

- `--check-targets` intentionally runs trusted project constructors and discards the constructed objects.
- Generic config target checks skip pipeline stage factory paths because those targets require pipeline-owned `factory.init` construction semantics.
