"""Top-level config validation and recipe detection."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData

from .errors import ConfigValidationError, UnsupportedRecipeError


def validate_top_level_fields(config: Mapping[str, PlainData]) -> dict[str, PlainData]:
    name = config.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigValidationError("Top-level config validation failed: name must be a non-empty string")

    pipeline = config.get("pipeline")
    if not isinstance(pipeline, Mapping):
        raise ConfigValidationError("Top-level config validation failed: pipeline must be a mapping")

    schema_version = config.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        raise ConfigValidationError("Top-level config validation failed: schema_version must be 1 when provided")

    validated = dict(config)
    validated.setdefault("schema_version", 1)
    return validated


def validate_no_recipe_keys(config: Mapping[str, PlainData], *, path: str = "$") -> None:
    _check_no_recipe(config, path=path)


def _check_no_recipe(value: object, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}[{key!r}]"
            if key == "_recipe_":
                raise UnsupportedRecipeError(
                    f"_recipe_ is not supported in Phase 4 at {child_path}; Phase 5 handles recipe expansion"
                )
            _check_no_recipe(child, path=child_path)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_recipe(child, path=f"{path}[{index}]")
