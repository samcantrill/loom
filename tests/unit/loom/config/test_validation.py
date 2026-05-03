"""Unit tests for config validation and recipe detection."""

import pytest

from loom.config.errors import ConfigValidationError, UnsupportedRecipeError
from loom.config.validation import validate_no_recipe_keys, validate_top_level_fields


def test_validate_top_level_requires_name_and_pipeline() -> None:
    with pytest.raises(ConfigValidationError):
        validate_top_level_fields({"name": "demo"})
    with pytest.raises(ConfigValidationError):
        validate_top_level_fields({"pipeline": {}})


def test_validate_schema_version_aware_defaults() -> None:
    validated = validate_top_level_fields({"name": "demo", "pipeline": {}})
    assert validated["name"] == "demo"
    assert validated["pipeline"] == {}
    assert validated["schema_version"] == 1


def test_validate_schema_version_rejects_other_versions() -> None:
    with pytest.raises(ConfigValidationError):
        validate_top_level_fields({"name": "demo", "pipeline": {}, "schema_version": 2})


def test_validate_keeps_unknown_top_level_keys() -> None:
    validated = validate_top_level_fields({"name": "demo", "pipeline": {}, "_target_": {"path": "x"}, "_copy_": 2})
    assert "_target_" in validated
    assert "_copy_" in validated


def test_validate_no_recipe_check_remains_present() -> None:
    with pytest.raises(UnsupportedRecipeError):
        validate_no_recipe_keys({"name": "demo", "pipeline": {}, "top": {"_recipe_": {"k": 1}}})
