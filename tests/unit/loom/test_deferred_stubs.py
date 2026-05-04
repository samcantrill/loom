"""Unit tests for APIs promoted from deferred Phase 5 stubs."""

import loom.config
import loom.config.api as config_api
import pytest

from tests.support.config_samples import function_recipe


pytestmark = pytest.mark.optional_dependency


def test_phase5_config_apis_are_live(monkeypatch) -> None:
    monkeypatch.setattr(config_api, "__default_recipe_catalog", loom.config.RecipeCatalog())

    assert loom.config.instantiate({"value": ("a", "b")}) == {"value": ["a", "b"]}

    loom.config.register_recipe("unit-live", function_recipe)
    assert config_api._get_default_recipe_catalog().get("unit-live") is function_recipe
