"""Integration coverage for recipe nesting and interpolation behavior."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config, compose_config_with_catalog, register_recipe
import loom.config.api as config_api
from loom.config.errors import InvalidRecipeOutputError, UnknownRecipeError
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


def test_compose_preserves_authored_resolver_argument_in_recipe_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("argument", argument_recipe)
    monkeypatch.setenv("PHASE9_RECIPE_VALUE", "runtime-value")

    base.write_text(
        "name: base\npipeline:\n  _recipe_: argument\n  value: ${oc.env:PHASE9_RECIPE_VALUE}\n",
        encoding="utf-8",
    )

    composed = compose_config(base, recipe_catalog=catalog)

    manifest = cast(dict[str, Any], composed.recipe_manifest[0])
    assert manifest["arguments"]["value"] == "${oc.env:PHASE9_RECIPE_VALUE}"
    assert composed.resolved["pipeline"] == {"value": "runtime-value:0"}


def test_compose_recipe_resolver_arguments_keep_default_artifacts_env_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("argument", argument_recipe)
    base.write_text(
        "name: base\npipeline:\n  _recipe_: argument\n  value: ${oc.env:PHASE4_RECIPE_VALUE}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE4_RECIPE_VALUE", "recipe-runtime-one")
    first = compose_config(base, recipe_catalog=catalog)
    monkeypatch.setenv("PHASE4_RECIPE_VALUE", "recipe-runtime-two")
    second = compose_config(base, recipe_catalog=catalog)

    assert first.resolved["pipeline"] == {"value": "recipe-runtime-one:0"}
    assert second.resolved["pipeline"] == {"value": "recipe-runtime-two:0"}
    assert first.recipe_manifest == second.recipe_manifest
    manifest = cast(dict[str, Any], first.recipe_manifest[0])
    assert manifest["arguments"]["value"] == "${oc.env:PHASE4_RECIPE_VALUE}"
    assert first.manifest.to_dict()["recipe_manifest"] == [manifest]
    manifest_metadata = cast(dict[str, Any], first.manifest.to_dict()["metadata"])
    provenance_metadata = cast(dict[str, Any], first.provenance.metadata)
    fingerprint_metadata = cast(dict[str, Any], first.fingerprint_records[0].metadata)
    assert cast(list[dict[str, Any]], manifest_metadata["recipe_manifest"])[0]["arguments"][
        "value"
    ] == "${oc.env:PHASE4_RECIPE_VALUE}"
    assert cast(list[dict[str, Any]], provenance_metadata["recipe_manifest"])[0]["arguments"][
        "value"
    ] == "${oc.env:PHASE4_RECIPE_VALUE}"
    assert cast(list[dict[str, Any]], fingerprint_metadata["recipe_manifest"])[0]["arguments"][
        "value"
    ] == "${oc.env:PHASE4_RECIPE_VALUE}"
    assert first.fingerprint == second.fingerprint
    assert first.provenance.artifact_fingerprint == second.provenance.artifact_fingerprint
    assert first.provenance.metadata["fingerprint"] == second.provenance.metadata["fingerprint"]
    assert first.manifest.to_dict() == second.manifest.to_dict()
    assert [record.to_dict() for record in first.fingerprint_records] == [
        record.to_dict() for record in second.fingerprint_records
    ]

    serialized = json.dumps(
        {
            "recipe_manifest": first.recipe_manifest,
            "provenance": first.provenance.to_dict(),
            "manifest": first.manifest.to_dict(),
            "fingerprint_records": [record.to_dict() for record in first.fingerprint_records],
        },
        sort_keys=True,
    )
    assert "recipe-runtime-one" not in serialized
    assert "recipe-runtime-two" not in serialized


def test_unknown_recipe_rejected_in_integration_shape(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"

    base.write_text("name: base\npipeline:\n  _recipe_: missing\n  value: one\n", encoding="utf-8")
    with pytest.raises(UnknownRecipeError):
        compose_config(base, recipe_catalog=RecipeCatalog())


def test_compose_rejects_resolver_expression_in_recipe_output_key(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()

    def output_with_resolver_key(prefix: str) -> dict[str, str]:
        return {f"${{{prefix}}}": "value"}

    catalog.register("resolver-key", output_with_resolver_key)
    base.write_text(
        "name: base\npipeline:\n  _recipe_: resolver-key\n  prefix: value\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidRecipeOutputError):
        compose_config(base, recipe_catalog=catalog)


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
