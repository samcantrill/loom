"""Integration checks for recipe-aware configuration composition."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config
from loom.config.errors import OverrideApplyError
from tests.support.config_samples import DownstreamRecipe, argument_recipe


def test_public_composition_with_overlays_and_overrides(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    overlay2 = tmp_path / "overlay2.yaml"

    base.write_text("name: base\npipeline:\n  root: ${pipeline.paths.root}\n  paths:\n    root: /tmp\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  stage: overlay\n", encoding="utf-8")
    overlay2.write_text("pipeline:\n  nested:\n    value: ${pipeline.stage}\n", encoding="utf-8")

    composed = compose_config(
        config_path=base,
        overlays=(overlay, overlay2),
        overrides=("pipeline.stage=override", "+pipeline.secret_token=sauce"),
    )

    pipeline = composed.resolved["pipeline"]
    assert isinstance(pipeline, dict)
    nested = cast(dict[str, Any], pipeline["nested"])
    assert nested["value"] == "override"
    assert pipeline["stage"] == "override"
    assert pipeline["root"] == "/tmp"

    redacted_pipeline = cast(dict[str, Any], composed.redacted["pipeline"])
    assert redacted_pipeline["secret_token"] == "***REDACTED***"


def test_public_compose_expands_recipes_and_nested_interpolation(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    catalog = RecipeCatalog()
    catalog.register("downstream", DownstreamRecipe)

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  _recipe_: downstream\n"
        "  value: ${paths.cli}\n"
        "paths:\n"
        "  cli: /cli\n"
        "  root: /tmp\n",
        encoding="utf-8",
    )
    overlay.write_text("pipeline:\n  marker: ${paths.root}-overlay\n", encoding="utf-8")

    composed = compose_config(
        base,
        overlays=(overlay,),
        overrides=("pipeline.value=resolved-by-override",),
        recipe_catalog=catalog,
    )

    pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    manifest = cast(dict[str, Any], composed.recipe_manifest[0])
    assert pipeline["value"] == "resolved-by-override"
    assert composed.recipe_manifest[0]["name"] == "downstream"
    assert composed.recipe_manifest[0]["path"] == "pipeline"
    assert manifest["arguments"]["value"] == "/cli"
    assert manifest["arguments"]["marker"] == "/tmp-overlay"


def test_public_compose_rejects_ordinary_override_to_unexpanded_recipe_argument(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()

    def pass_through(value: str) -> dict[str, str]:
        del value
        return {"result": "kept"}

    catalog.register("pass-through", pass_through)

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  _recipe_: pass-through\n"
        "  value: recipe-value\n",
        encoding="utf-8",
    )

    with pytest.raises(OverrideApplyError):
        compose_config(base, recipe_catalog=catalog, overrides=("pipeline.value=changed",))


def test_public_fingerprints_change_with_recipe_manifest(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("arg", argument_recipe)

    base.write_text("name: base\npipeline:\n  _recipe_: arg\n  value: one\n", encoding="utf-8")
    first = compose_config(base, recipe_catalog=catalog)
    catalog.register("arg", argument_recipe, replace=True)
    base.write_text("name: base\npipeline:\n  _recipe_: arg\n  value: two\n", encoding="utf-8")
    second = compose_config(base, recipe_catalog=catalog)

    assert first.fingerprint != second.fingerprint
    first_pipeline = cast(dict[str, Any], first.resolved["pipeline"])
    second_pipeline = cast(dict[str, Any], second.resolved["pipeline"])
    assert first_pipeline["value"] != second_pipeline["value"]


def test_compose_does_not_instantiate_targets(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("downstream", DownstreamRecipe)

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  _recipe_: downstream\n"
        "  value: target\n"
        "\n"
        "target:\n"
        "  _target_: tests.support.config_samples:concat\n"
        "  prefix: no-call\n",
        encoding="utf-8",
    )

    composed = compose_config(base, recipe_catalog=catalog)
    target = composed.resolved["target"]
    assert isinstance(target, dict)
    assert target["_target_"] == "tests.support.config_samples:concat"
