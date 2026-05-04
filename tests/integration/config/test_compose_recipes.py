"""Integration coverage for recipe nesting and interpolation behavior."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config, compose_config_with_catalog, register_recipe
import loom.config.api as config_api
from loom.config.errors import UnknownRecipeError
from tests.support.config_samples import DownstreamRecipe, nested_argument_recipe, composed_output_recipe, argument_recipe


def test_nested_recipe_expansion_path_and_manifest(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("outer", nested_argument_recipe)
    catalog.register("dataclass", DownstreamRecipe)

    base.write_text("name: base\npipeline:\n  _recipe_: outer\n  value: root\n", encoding="utf-8")
    composed = compose_config(base, recipe_catalog=catalog)

    pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    outer = cast(dict[str, Any], pipeline["outer"])
    inner = cast(dict[str, Any], outer["inner"])
    assert outer["value"] == "root"
    assert inner["value"] == "seeded:root-inner"
    assert composed.recipe_manifest[0]["name"] == "outer"
    assert composed.recipe_manifest[1]["name"] == "dataclass"
    assert composed.recipe_manifest[1]["path"] == "pipeline.outer.inner"


def test_recipe_output_final_interpolation(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("compose", composed_output_recipe)
    catalog.register("dataclass", DownstreamRecipe)

    base.write_text("name: base\nvalue: root\npipeline:\n  _recipe_: compose\n  value: ${value}\n", encoding="utf-8")
    composed = compose_config(base, recipe_catalog=catalog)

    pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    nested = cast(dict[str, Any], pipeline["nested"])
    assert pipeline["resolved"] == "root-resolved"
    assert nested["value"] == "nested:root-child"


def test_unknown_recipe_rejected_in_integration_shape(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"

    base.write_text("name: base\npipeline:\n  _recipe_: missing\n  value: one\n", encoding="utf-8")
    with pytest.raises(UnknownRecipeError):
        compose_config(base, recipe_catalog=RecipeCatalog())


def test_compose_config_with_catalog_isolated_from_global_recipe_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base.yaml"

    base.write_text("name: base\npipeline:\n  _recipe_: arg\n  value: one\n", encoding="utf-8")
    monkeypatch.setattr(config_api, "__default_recipe_catalog", RecipeCatalog())

    register_recipe("arg", argument_recipe)

    with pytest.raises(UnknownRecipeError):
        compose_config_with_catalog(base, recipe_catalog=RecipeCatalog())

    explicit_catalog = RecipeCatalog()
    explicit_catalog.register("arg", argument_recipe)
    composed = compose_config_with_catalog(base, recipe_catalog=explicit_catalog)
    assert composed.resolved["pipeline"] == {"value": "one:0"}
