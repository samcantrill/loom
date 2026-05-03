"""Top-level config validation and recipe detection."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from loom.serialization import PlainData

from .errors import ConfigValidationError, UnsupportedRecipeError


class _TopLevelConfig(BaseModel):
    name: str
    pipeline: dict[str, PlainData]
    schema_version: int = Field(default=1)

    model_config = ConfigDict(extra="allow")

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("schema_version must be 1 when provided")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must be non-empty")
        return value


def validate_top_level_fields(config: Mapping[str, PlainData]) -> dict[str, PlainData]:
    try:
        model = _TopLevelConfig.model_validate(config)
    except ValidationError as exc:
        raise ConfigValidationError("Top-level config validation failed") from exc
    return model.model_dump()


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
