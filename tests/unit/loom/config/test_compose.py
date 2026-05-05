"""Unit tests for public compose_config behavior."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config, compose_config_with_catalog, register_recipe
from loom.config.errors import ConfigLoadError
from loom.config.errors import ConfigValidationError, UnknownRecipeError
import loom.config.api as config_api
from tests.support.config_samples import argument_recipe


def test_compose_base_overlay_override_flow(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    overlay2 = tmp_path / "overlay2.yaml"

    base.write_text("name: base\npipeline:\n  stage: base\n  paths:\n    root: /tmp/base\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  stage: overlay\n", encoding="utf-8")
    overlay2.write_text("pipeline:\n  result: ${pipeline.stage}-done\n", encoding="utf-8")

    result = compose_config(base, overlays=[overlay, overlay2], overrides=("+pipeline.extra=1", "+pipeline.paths.child=child"))

    assert result.resolved["name"] == "base"
    pipeline = result.resolved["pipeline"]
    assert isinstance(pipeline, dict)
    paths = pipeline["paths"]
    assert isinstance(paths, dict)
    assert pipeline["stage"] == "overlay"
    assert pipeline["result"] == "overlay-done"
    assert paths["child"] == "child"
    assert pipeline["extra"] == 1
    assert result.recipe_manifest == ()
    assert result.provenance.schema_version == 1
    assert result.provenance.config_path == str(base.resolve())
    assert [source.kind for source in result.provenance.sources] == ["base", "overlay", "overlay"]


def test_compose_preserves_include_replace_keys(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: demo\npipeline: {}\n_include_: true\n_replace_: true\n", encoding="utf-8")
    result = compose_config(base)
    assert result.resolved["_include_"] is True
    assert result.resolved["_replace_"] is True


def test_compose_rejects_copy_directive_in_config(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: demo\npipeline: {}\n_copy_: true\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)
    assert exc.value.context is not None
    assert exc.value.context.code == "unsupported_directive"
    assert exc.value.context.config_path == "$._copy_"


def test_compose_expands_recipe_key(tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: demo\npipeline:\n  _recipe_: arg\n  value: one\n", encoding="utf-8")
    catalog = RecipeCatalog()
    catalog.register("arg", argument_recipe)
    composed = compose_config(path, recipe_catalog=catalog)

    assert composed.recipe_manifest
    assert composed.resolved["pipeline"] == {"value": "one:0"}
    assert composed.recipe_manifest[0]["name"] == "arg"
    assert composed.recipe_manifest[0]["path"] == "pipeline"


def test_compose_rejects_recipe_catalog() -> None:
    with pytest.raises(ConfigValidationError):
        compose_config("does-not-exist.yaml", recipe_catalog=cast(Any, object()))


def test_compose_config_with_catalog_rejects_recipe_catalog() -> None:
    with pytest.raises(ConfigValidationError):
        compose_config_with_catalog("does-not-exist.yaml", recipe_catalog=cast(Any, object()))


def test_compose_rejects_none_overlays() -> None:
    with pytest.raises(ConfigValidationError):
        compose_config(Path("/tmp/base.yaml"), overlays=cast(Any, None))


def test_compose_rejects_none_overrides(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline: {}\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        compose_config(base, overrides=cast(Any, None))


def test_compose_config_uses_global_catalog_when_recipe_catalog_not_provided(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: demo\npipeline:\n  _recipe_: arg\n  value: one\n", encoding="utf-8")
    monkeypatch.setattr(config_api, "__default_recipe_catalog", RecipeCatalog())

    register_recipe("arg", argument_recipe)
    composed = compose_config(path)

    assert composed.resolved["pipeline"] == {"value": "one:0"}
    assert composed.recipe_manifest[0]["name"] == "arg"


def test_compose_config_with_catalog_uses_explicit_catalog_and_ignores_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: demo\npipeline:\n  _recipe_: arg\n  value: one\n", encoding="utf-8")
    monkeypatch.setattr(config_api, "__default_recipe_catalog", RecipeCatalog())

    register_recipe("arg", argument_recipe)

    with pytest.raises(UnknownRecipeError):
        compose_config(path, recipe_catalog=RecipeCatalog())

    with pytest.raises(UnknownRecipeError):
        compose_config_with_catalog(path, recipe_catalog=RecipeCatalog())

    catalog = RecipeCatalog()
    catalog.register("arg", argument_recipe)
    composed = compose_config_with_catalog(path, recipe_catalog=catalog)
    assert composed.resolved["pipeline"] == {"value": "one:0"}
    assert composed.recipe_manifest[0]["name"] == "arg"
