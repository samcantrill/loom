"""Top-level config validation and recipe detection."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData

from .errors import ConfigValidationError, UnsupportedRecipeError


def validate_top_level_fields(config: Mapping[str, PlainData]) -> dict[str, PlainData]:
    # Project-owned configs are passed through as opaque payloads at the public
    # compose boundary; this validation only preserves explicit mappings and
    # leaves composition ownership in explicit helpers.
    if not isinstance(config, Mapping):
        raise ConfigValidationError(
            "Top-level config validation failed: expected mapping for composition boundary",
        )

    return dict(config)


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
