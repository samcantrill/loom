"""Unit tests for recipe argument pre-resolution and expansion."""

from typing import Any, cast

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
from loom.serialization import PlainData
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


def test_expand_preserves_argument_resolver_expressions() -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)

    resolved_args = resolve_recipe_argument_interpolation(
        {"pipeline": {"_recipe_": "argument", "value": "${oc.env:PHASE9_RECIPE_VALUE}"}},
    )
    expanded, manifest = expand_recipes(resolved_args, catalog=catalog)
    record = cast(dict[str, Any], manifest[0])

    assert expanded["pipeline"] == {"value": "${oc.env:PHASE9_RECIPE_VALUE}"}
    assert record["arguments"]["value"] == "${oc.env:PHASE9_RECIPE_VALUE}"


def test_expand_nested_recipe_order_and_paths() -> None:
    catalog = RecipeCatalog()
    catalog.register("outer", nested_argument_recipe)
    catalog.register("dataclass", DownstreamRecipe)

    config = {"pipeline": {"_recipe_": "outer", "value": "hello"}}
    expanded, manifest = expand_recipes(cast(dict[str, PlainData], config), catalog=catalog)

    assert expanded["pipeline"] == {"outer": {"value": "hello", "inner": {"value": "seeded:hello-inner"}}}
    assert [entry["name"] for entry in manifest] == ["outer", "dataclass"]
    assert manifest[0]["path"] == "pipeline"
    assert manifest[0]["name"] == "outer"
    assert manifest[1]["path"] == "pipeline.outer.inner"
    assert manifest[1]["name"] == "dataclass"


@pytest.mark.parametrize("reserved_key", ["_target_", "_args_", "_partial_", "_inject_"])
def test_expand_rejects_reserved_keys_in_recipe_block(reserved_key: str) -> None:
    catalog = RecipeCatalog()
    catalog.register("argument", ArgumentRecipe)

    with pytest.raises(ReservedConfigKeyError) as exc:
        expand_recipes({"x": {"_recipe_": "argument", reserved_key: "bad", "value": "x"}}, catalog=catalog)
    assert f"Reserved key {reserved_key!r} is not allowed in recipe blocks" in str(exc.value)


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


def test_pre_resolution_rejects_nested_recipe_inside_arguments_before_interpolation() -> None:
    with pytest.raises(RecipeExpansionError):
        resolve_recipe_argument_interpolation(
            {
                "x": {
                    "_recipe_": "argument",
                    "value": {"inner": {"_recipe_": "argument", "value": "${missing}"}},
                },
            }
        )


def test_expand_rejects_resolver_expression_in_output_key() -> None:
    catalog = RecipeCatalog()

    def output_with_resolver_key(prefix: str) -> dict[str, str]:
        return {f"${{{prefix}}}": "value"}

    catalog.register("resolver-key", output_with_resolver_key)
    with pytest.raises(InvalidRecipeOutputError) as exc:
        expand_recipes({"x": {"_recipe_": "resolver-key", "prefix": "value"}}, catalog=catalog)
    context = exc.value.context
    assert context is not None
    assert context.code == "recipe_output_resolver_shaped_key"
    assert context.config_path == "x"
    assert context.details is not None
    assert context.details["stage"] == "recipe_expansion"


def test_expand_rejects_resolver_argument_used_as_output_key() -> None:
    catalog = RecipeCatalog()

    def output_key_from_argument(prefix: str) -> dict[str, str]:
        return {prefix: "value"}

    catalog.register("argument-key", output_key_from_argument)
    resolved_args = resolve_recipe_argument_interpolation(
        {"x": {"_recipe_": "argument-key", "prefix": "${oc.env:PHASE9_RECIPE_KEY}"}}
    )

    with pytest.raises(InvalidRecipeOutputError):
        expand_recipes(resolved_args, catalog=catalog)


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
    pipeline = cast(dict[str, Any], resolved["pipeline"])
    nested = cast(dict[str, Any], pipeline["nested"])
    assert pipeline["value"] == "one"
    assert nested["value"] == "nested:one-child"
    assert pipeline["resolved"] == "one-resolved"
