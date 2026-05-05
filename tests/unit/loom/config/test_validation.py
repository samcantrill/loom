"""Unit tests for config validation and recipe detection."""

from collections.abc import Mapping
from typing import Any, cast

import pytest

from loom.config.errors import ConfigValidationError, UnsupportedRecipeError
from loom.config.validation import validate_no_recipe_keys, validate_top_level_fields
from loom.serialization import PlainData


def test_validate_top_level_accepts_generic_payloads() -> None:
    validated = validate_top_level_fields({"model": {"name": "demo"}, "pipeline": {"path": "stages"}})
    assert validated["model"] == {"name": "demo"}
    pipeline = cast(dict[str, Any], validated["pipeline"])
    assert pipeline["path"] == "stages"


def test_validate_top_level_preserves_unknown_and_inert_keys() -> None:
    validated = validate_top_level_fields(
        {
            "schema_version": 99,
            "_target_": {"path": "tests.support.config_samples:concat"},
            "experiment": {"name": "demo"},
        },
    )
    assert validated["schema_version"] == 99
    assert validated["_target_"] == {"path": "tests.support.config_samples:concat"}
    assert validated["experiment"] == {"name": "demo"}


def test_validate_top_level_rejects_non_mapping_configs() -> None:
    with pytest.raises(ConfigValidationError, match="expected mapping"):
        validate_top_level_fields(cast(Mapping[str, PlainData], cast(object, [])))


def test_validate_no_recipe_check_remains_present() -> None:
    with pytest.raises(UnsupportedRecipeError):
        validate_no_recipe_keys({"name": "demo", "pipeline": {}, "top": {"_recipe_": {"k": 1}}})
