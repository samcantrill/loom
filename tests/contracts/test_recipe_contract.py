"""Contract tests for extension-style recipe implementations."""

import pytest

import importlib
from typing import Any, cast
from types import ModuleType

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config.recipes import Recipe, RecipeCatalog
from loom.config.errors import InvalidRecipeOutputError
from loom.config.recipes.expansion import expand_recipes
from loom.plugins import (
    LOOM_RECIPES_GROUP,
    PluginDuplicateError,
    PluginRecord,
    load_recipe_entry_points,
)
from tests.support.config_samples import ArgumentRecipe, DownstreamRecipe, NestedOutputRecipe, function_recipe, nested_output_recipe


pytestmark = [pytest.mark.contract, pytest.mark.optional_dependency]


def test_downstream_dataclass_recipe_without_base_class_registers() -> None:
    catalog = RecipeCatalog()
    catalog.register("downstream", DownstreamRecipe)
    assert catalog.get("downstream") is DownstreamRecipe
    expanded, manifest = expand_recipes({"pipeline": {"_recipe_": "downstream", "value": "alpha"}}, catalog=catalog)
    pipeline = cast(dict[str, Any], expanded["pipeline"])
    assert pipeline["value"] == "downstream:alpha"
    assert manifest and len(manifest) == 1


def test_typed_recipe_subclass_support_and_validation() -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)
    expanded, manifest = expand_recipes({"pipeline": {"_recipe_": "argument", "value": "x"}}, catalog=catalog)
    assert expanded["pipeline"] == {"value": "x"}
    assert manifest and len(manifest) == 1

    recipe_obj = ArgumentRecipe(value="hello")
    assert isinstance(recipe_obj, Recipe)
    assert recipe_obj.expand() == {"value": "hello"}


def test_function_recipe_support() -> None:
    catalog = RecipeCatalog()
    catalog.register("function", function_recipe)
    expanded, _ = expand_recipes({"pipeline": {"_recipe_": "function", "value": "x", "prefix": "p-", "repeat": 2}}, catalog=catalog)
    assert expanded["pipeline"] == {"value": "p-xp-x"}


def test_structural_recipe_can_be_a_protocol_object() -> None:
    class ProtocolRecipe:
        def __init__(self, value: str) -> None:
            self.value = value

        def expand(self) -> dict[str, object]:
            return {"value": self.value}

    catalog = RecipeCatalog()
    catalog.register("protocol", ProtocolRecipe)
    expanded, _ = expand_recipes({"pipeline": {"_recipe_": "protocol", "value": "v"}}, catalog=catalog)
    assert expanded["pipeline"] == {"value": "v"}


def test_resolver_expression_in_recipe_output_key_is_rejected() -> None:
    catalog = RecipeCatalog()

    def output_with_resolver_key(prefix: str) -> dict[str, str]:
        return {f"${{{prefix}}}": "value"}

    catalog.register("resolver-key", output_with_resolver_key)
    with pytest.raises(InvalidRecipeOutputError):
        expand_recipes({"pipeline": {"_recipe_": "resolver-key", "prefix": "value"}}, catalog=catalog)


def test_contract_recipe_output_can_be_nested_recipe() -> None:
    catalog = RecipeCatalog()
    catalog.register("nested-output", nested_output_recipe)
    catalog.register("downstream", DownstreamRecipe)
    catalog.register("nested-class", NestedOutputRecipe)

    expanded, manifest = expand_recipes(
        {"pipeline": {"_recipe_": "nested-output", "value": "x"}},
        catalog=catalog,
    )
    pipeline = cast(dict[str, Any], expanded["pipeline"])
    outer = cast(dict[str, Any], pipeline["outer"])
    inner = cast(dict[str, Any], outer["inner"])
    assert outer["value"] == "x"
    assert inner["value"] == "nested:x-inner"
    assert manifest[0]["name"] == "nested-output"
    assert manifest[1]["name"] == "downstream"


def test_contract_recipe_adapter_loads_fake_entry_point_into_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = RecipeCatalog()
    record = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="plugin",
        value="loom.plugins.contract_recipe_adapter:recipe",
    )

    module = ModuleType("loom.plugins.contract_recipe_adapter")

    def plugin_recipe(value: str) -> dict[str, str]:
        return {"value": value}

    module.recipe = plugin_recipe
    monkeypatch.setattr(importlib, "import_module", lambda name, package=None: module)

    load_recipe_entry_points(records=(record,), catalog=catalog, strict=True)
    expanded, manifest = expand_recipes(
        {"pipeline": {"_recipe_": "plugin", "value": "from-adapter"}},
        catalog=catalog,
    )

    assert expanded["pipeline"] == {"value": "from-adapter"}
    assert manifest == [{"name": "plugin", "value": {"value": "from-adapter"}}]


def test_contract_recipe_adapter_duplicate_entry_point_names_fail_closed() -> None:
    duplicate_a = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="same",
        value="loom.plugins.contract_recipe_duplicate:first",
    )
    duplicate_b = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="same",
        value="loom.plugins.contract_recipe_duplicate:second",
    )

    with pytest.raises(PluginDuplicateError):
        load_recipe_entry_points((duplicate_a, duplicate_b), RecipeCatalog(), strict=True)
