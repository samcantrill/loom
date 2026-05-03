"""Unit tests for recipe argument pre-resolution and expansion."""

import pytest

from loom.config.errors import (
    InvalidRecipeOutputError,
    RecipeExpansionError,
    ReservedConfigKeyError,
    UnknownRecipeError,
)
from loom.config.recipes import RecipeCatalog
from loom.config.recipes.expansion import expand_recipes, resolve_recipe_argument_interpolation
from loom.config.interpolation import resolve_interpolation
from tests.support.config_samples import ArgumentRecipe, DownstreamRecipe, nested_argument_recipe, composed_output_recipe


def test_expand_recipe_arguments_with_interpolation() -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)

    config = {"value": "base", "pipeline": {"_recipe_": "argument", "value": "${value}"}}
    resolved_args = resolve_recipe_argument_interpolation(config)
    expanded, manifest = expand_recipes(resolved_args, catalog=catalog)

    assert expanded["pipeline"] == {"value": "base"}
    assert len(manifest) == 1
    assert manifest[0]["name"] == "argument"
    assert manifest[0]["path"] == "pipeline"


def test_expand_nested_recipe_order_and_paths() -> None:
    catalog = RecipeCatalog()
    catalog.register("outer", nested_argument_recipe)
    catalog.register("dataclass", DownstreamRecipe)

    config = {"pipeline": {"_recipe_": "outer", "value": "hello"}}
    expanded, manifest = expand_recipes(config, catalog=catalog)

    assert expanded["pipeline"] == {"outer": {"value": "hello", "inner": {"value": "seeded:hello-inner"}}}
    assert [entry["name"] for entry in manifest] == ["outer", "dataclass"]
    assert manifest[0]["path"] == "pipeline"
    assert manifest[0]["name"] == "outer"
    assert manifest[1]["path"] == "pipeline.outer.inner"
    assert manifest[1]["name"] == "dataclass"


def test_expand_rejects_reserved_keys_in_recipe_block() -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)

    with pytest.raises(ReservedConfigKeyError) as exc:
        expand_recipes({"x": {"_recipe_": "argument", "_target_": "bad", "value": "x"}}, catalog=catalog)
    assert "Reserved key '_target_' is not allowed in recipe blocks" in str(exc.value)


def test_expand_rejects_nested_recipe_inside_arguments() -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)

    with pytest.raises(RecipeExpansionError):
        expand_recipes(
            {
                "x": {
                    "_recipe_": "argument",
                    "value": {"inner": {"_recipe_": "argument", "value": "x"}},
                },
            },
            catalog=catalog,
        )


def test_expand_unknown_recipe() -> None:
    catalog = RecipeCatalog()
    with pytest.raises(UnknownRecipeError):
        expand_recipes({"x": {"_recipe_": "missing", "value": "x"}}, catalog=catalog)


def test_expand_fails_non_mapping_output() -> None:
    catalog = RecipeCatalog()

    def returns_scalar(value: str) -> str:
        del value
        return "bad"

    catalog.register("bad", returns_scalar)
    with pytest.raises(InvalidRecipeOutputError):
        expand_recipes({"x": {"_recipe_": "bad", "value": "x"}}, catalog=catalog)


def test_expand_fails_plain_data_violation() -> None:
    catalog = RecipeCatalog()

    def returns_bytes(value: str) -> dict[str, object]:
        del value
        return {"value": b"bytes"}

    catalog.register("bad", returns_bytes)
    with pytest.raises(InvalidRecipeOutputError):
        expand_recipes({"x": {"_recipe_": "bad", "value": "x"}}, catalog=catalog)


def test_expand_handles_final_interpolation_for_output() -> None:
    catalog = RecipeCatalog()
    catalog.register("compose", composed_output_recipe)
    catalog.register("dataclass", DownstreamRecipe)

    config = {"value": "one", "pipeline": {"_recipe_": "compose", "value": "${value}"}}
    resolved_args = resolve_recipe_argument_interpolation(config)
    expanded, _ = expand_recipes(resolved_args, catalog=catalog)
    resolved = resolve_interpolation(expanded, path="$")
    assert resolved["pipeline"]["value"] == "one"
    assert resolved["pipeline"]["nested"]["value"] == "nested:one-child"
    assert resolved["pipeline"]["resolved"] == "one-resolved"
