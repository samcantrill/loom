"""Integration checks for recipe-aware configuration composition."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config, inspect_config_composition, instantiate
from loom.config.errors import ConfigLoadError, OverrideApplyError
from loom.config.fingerprints import compare_config_artifact_fingerprints
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


def test_compose_allows_generic_configs_without_name_or_pipeline(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "experiment:\n"
        "  architecture: transformer\n"
        "  params:\n"
        "    width: 256\n",
        encoding="utf-8",
    )
    composed = compose_config(base)
    assert composed.resolved["experiment"] == {"architecture": "transformer", "params": {"width": 256}}
    assert "schema_version" not in composed.resolved


def test_compose_uses_generic_payload_for_redaction_and_fingerprints(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "experiment:\n"
        "  architecture: transformer\n"
        "  secret_token: keep-private\n"
        "metadata:\n"
        "  owner: project\n",
        encoding="utf-8",
    )

    composed = compose_config(base)

    assert composed.resolved == {
        "experiment": {
            "architecture": "transformer",
            "secret_token": "keep-private",
        },
        "metadata": {
            "owner": "project",
        },
    }
    redacted_experiment = cast(dict[str, Any], composed.redacted["experiment"])
    assert redacted_experiment == {
        "architecture": "transformer",
        "secret_token": "***REDACTED***",
    }
    assert "schema_version" not in composed.redacted
    assert composed.fingerprint == composed.fingerprint_records[0].digest
    assert (
        compare_config_artifact_fingerprints(
            left=composed.fingerprint_records[0],
            right=composed.manifest,
        ).status
        == "match"
    )


def test_compose_keeps_project_scoped_target_nodes_inert(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "dataset:\n"
        "  _target_: tests.support.config_samples:concat\n"
        "  prefix: left\n"
        "  suffix: right\n",
        encoding="utf-8",
    )
    composed = compose_config(base)

    dataset = cast(dict[str, Any], composed.resolved["dataset"])
    assert dataset == {
        "_target_": "tests.support.config_samples:concat",
        "prefix": "left",
        "suffix": "right",
    }


def test_compose_rejects_schema_directive_in_base(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "model:\n"
        "  _schema_: {}\n"
        "  value: from-base\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_directive"
    assert context.source_kind == "base"
    assert context.source_order == 0
    assert context.config_path == "$.model._schema_"
    assert context.directive == "_schema_"
    assert context.expected == "schema declarations from authored files"


def test_compose_rejects_schema_directive_in_overlay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("model:\n  value: from-base\n", encoding="utf-8")
    overlay.write_text("model:\n  _schema_: {}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base, overlays=[overlay])

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_directive"
    assert context.source_kind == "overlay"
    assert context.source_order == 1
    assert context.config_path == "$.model._schema_"
    assert context.directive == "_schema_"
    assert context.expected == "schema declarations from authored files"


def test_compose_rejects_copy_directive_in_overlay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("model:\n  value: from-base\n", encoding="utf-8")
    overlay.write_text("model:\n  _copy_: true\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base, overlays=[overlay])

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_directive"
    assert context.source_kind == "overlay"
    assert context.source_order == 1
    assert context.source_path == str(overlay.resolve())
    assert context.config_path == "$.model._copy_"
    assert context.directive == "_copy_"


def test_public_inspect_vs_compose_consistency_and_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"

    monkeypatch.setenv("PHASE12_PATH_ROOT", "/tmp/phase12")
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE12_PATH_ROOT}\n"
        "pipeline:\n"
        "  value: ${paths.root}/value\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "pipeline:\n"
        "  stage: overlay\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay,), overrides=("+pipeline.extra=true",))
    inspection = inspect_config_composition(base, overlays=(overlay,), overrides=("+pipeline.extra=true",))
    composed_from_inspection = inspection.to_composed_config()

    assert composed == composed_from_inspection
    unresolved_pipeline = cast(dict[str, Any], composed.unresolved["pipeline"])
    resolved_pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    assert unresolved_pipeline["value"] == "${paths.root}/value"
    assert resolved_pipeline["value"] == "/tmp/phase12/value"
    assert tuple(stage.name for stage in inspection.stages) == (
        "source_load",
        "overlay_merge",
        "file_include_expansion",
        "user_composition_overrides",
        "recipe_argument_interpolation",
        "recipe_expansion",
        "ordinary_overrides",
        "resolver_scan",
        "redaction",
        "provenance",
        "fingerprint",
        "artifact_placeholders",
        "runtime_interpolation",
        "validation",
        "composed_config",
    )


def test_public_compose_retains_inert_targets_until_explicit_instantiate(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "dataset:\n"
        "  _target_: tests.support.config_samples:concat\n"
        "  prefix: left\n"
        "  suffix: right\n",
        encoding="utf-8",
    )

    composed = compose_config(base)
    dataset = composed.resolved["dataset"]
    assert isinstance(dataset, dict)
    assert dataset == {
        "_target_": "tests.support.config_samples:concat",
        "prefix": "left",
        "suffix": "right",
    }
    assert instantiate(dataset) == "leftright"
