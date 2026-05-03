"""Contract tests for extension-style recipe implementations."""

from typing import Any, cast

from loom.config.recipes import Recipe, RecipeCatalog
from loom.config.recipes.expansion import expand_recipes
from tests.support.config_samples import ArgumentRecipe, DownstreamRecipe, NestedOutputRecipe, function_recipe, nested_output_recipe


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
