"""Integration checks for recipe-aware configuration composition."""

from pathlib import Path

from loom.config import RecipeCatalog, compose_config
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
    nested = pipeline["nested"]
    assert nested["value"] == "override"
    assert pipeline["stage"] == "override"
    assert pipeline["root"] == "/tmp"

    redacted_pipeline = composed.redacted["pipeline"]
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
        "  value: ${paths.root}\n"
        "paths:\n"
        "  root: /tmp\n",
        encoding="utf-8",
    )
    overlay.write_text("pipeline:\n  marker: ${paths.root}-overlay\n", encoding="utf-8")

    composed = compose_config(base, overlays=(overlay,), recipe_catalog=catalog)

    assert composed.resolved["pipeline"]["value"] == "/tmp-overlay:/tmp"
    assert composed.recipe_manifest[0]["name"] == "downstream"
    assert composed.recipe_manifest[0]["path"] == "pipeline"


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
    assert first.resolved["pipeline"]["value"] != second.resolved["pipeline"]["value"]


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
    assert isinstance(composed.resolved["target"], dict)
    assert composed.resolved["target"]["_target_"] == "tests.support.config_samples:concat"
