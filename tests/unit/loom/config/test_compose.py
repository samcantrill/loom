"""Unit tests for public compose_config behavior."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import (
    ConfigCompositionInspection,
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
    inspect_config_composition,
    register_recipe,
)
from loom.config.errors import ConfigLoadError
from loom.config.errors import ConfigValidationError, UnknownRecipeError
from loom.config.artifacts import SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION
from loom.config.fingerprints import (
    ARTIFACT_SAFE_FINGERPRINT_LABEL,
    ARTIFACT_SAFE_FINGERPRINT_POLICY,
    compare_config_artifact_fingerprints,
)
from loom.config.api import ComposedConfig
import loom.config.api as config_api
import loom.config.compose as config_compose
from loom.serialization import PlainData
from tests.support.config_samples import argument_recipe


def _model_mapping(config: dict[str, PlainData]) -> dict[str, PlainData]:
    pipeline = config["pipeline"]
    assert isinstance(pipeline, dict)
    model = pipeline["model"]
    assert isinstance(model, dict)
    return cast(dict[str, PlainData], model)


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
    assert result.provenance.schema_version == 2
    assert result.provenance.artifact_fingerprint == result.fingerprint
    assert result.provenance.config_path == str(base.resolve())
    assert [source.kind for source in result.provenance.sources] == ["base", "overlay", "overlay"]


def test_compose_expands_file_includes_and_removes_include_keys(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: demo\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n",
        encoding="utf-8",
    )
    (tmp_path / "included.yaml").write_text(
        "stage: included\n", encoding="utf-8"
    )
    result = compose_config(base)
    model = _model_mapping(result.resolved)
    assert model == {"stage": "included"}
    assert "_include_" not in model


def test_compose_default_raw_snapshot_bundle_is_metadata_only(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n",
        encoding="utf-8",
    )
    included.write_text("value: included\n", encoding="utf-8")

    composed = compose_config(base)

    assert composed.raw_source_snapshots.enabled is False
    assert composed.raw_source_snapshots.payloads == ()
    assert len(composed.raw_source_snapshots.references) == 2
    assert all(reference.availability == "disabled" for reference in composed.raw_source_snapshots.references)
    assert all(reference.reason == "not_requested" for reference in composed.raw_source_snapshots.references)
    assert all(reference.payload_id is None for reference in composed.raw_source_snapshots.references)

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    assert len(manifest_refs) == len(composed.raw_source_snapshots.references)
    assert all(reference["availability"] == "disabled" for reference in manifest_refs)
    assert all(reference["reason"] == "not_requested" for reference in manifest_refs)


def test_compose_with_raw_snapshots_opt_in_reuses_deduped_payloads(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "included.yaml"

    shared = "value: shared\n"
    overlay.write_text(shared, encoding="utf-8")
    included.write_text(shared, encoding="utf-8")
    base.write_text(
        "name: base\npipeline:\n  model:\n    _include_: included.yaml\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay,), include_raw_source_snapshots=True)

    assert composed.raw_source_snapshots.enabled is True
    assert len(composed.raw_source_snapshots.references) == 3
    assert len(composed.raw_source_snapshots.payloads) == 2
    payload = next(payload for payload in composed.raw_source_snapshots.payloads if payload.content == shared)
    assert payload.content == shared
    assert payload.encoding == "utf-8"
    overlay_reference_payload_ids = [
        reference.payload_id
        for reference in composed.raw_source_snapshots.references
        if reference.kind in {"overlay", "include"}
    ]
    assert overlay_reference_payload_ids[0] == overlay_reference_payload_ids[1]

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    assert len(manifest_refs) == 3
    assert manifest_refs[0]["availability"] == "available"
    assert manifest_refs[1]["availability"] == "available"
    assert manifest_refs[2]["availability"] == "available"
    assert manifest_refs[1]["payload_id"] == manifest_refs[2]["payload_id"]
    assert manifest_metadata["raw_source_snapshot_enabled"] is True


def test_compose_with_raw_snapshots_marks_recipe_unavailable(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: demo\n"
        "pipeline:\n"
        "  _recipe_: arg\n"
        "  value: one\n",
        encoding="utf-8",
    )
    catalog = RecipeCatalog()
    catalog.register("arg", argument_recipe)

    composed = compose_config(base, recipe_catalog=catalog, include_raw_source_snapshots=True)

    recipe_refs = [ref for ref in composed.raw_source_snapshots.references if ref.kind == "recipe"]
    assert len(recipe_refs) == 1
    assert recipe_refs[0].availability == "unavailable"
    assert recipe_refs[0].reason == "unsupported_source_kind"
    assert recipe_refs[0].payload_id is None
    assert composed.raw_source_snapshots.enabled is True
    assert len(composed.raw_source_snapshots.payloads) == 1


def test_compose_expands_file_include_with_user_override_ordering(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: demo\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n"
        "    local: base\n",
        encoding="utf-8",
    )
    (tmp_path / "included.yaml").write_text(
        "source: included\n", encoding="utf-8"
    )

    result = compose_config(base, overrides=("pipeline.model.local=override",))
    model = _model_mapping(result.resolved)
    assert model["source"] == "included"
    assert model["local"] == "override"


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
    assert composed.manifest.schema_version == ARTIFACT_SCHEMA_VERSION
    assert composed.manifest.recipe_manifest == composed.recipe_manifest


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


def test_compose_config_staged_path_matches_inspection(tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text(
        "name: demo\n"
        "paths:\n"
        "  root: /tmp/base\n"
        "pipeline:\n"
        "  value: ${paths.root}/value\n",
        encoding="utf-8",
    )

    inspection = inspect_config_composition(path)
    composed = inspection.to_composed_config()
    assert isinstance(inspection, ConfigCompositionInspection)
    stage_names = tuple(stage.name for stage in inspection.stages)
    assert stage_names == (
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

    assert composed == inspection.to_composed_config()
    unresolved_pipeline = cast(dict[str, Any], composed.unresolved["pipeline"])
    resolved_pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    assert unresolved_pipeline["value"] == "${paths.root}/value"
    assert resolved_pipeline["value"] == "/tmp/base/value"
    assert composed.source_artifacts == inspection.source_artifacts
    assert len(composed.source_artifacts) == 1
    assert len(composed.fingerprint_records) == 1
    assert composed.fingerprint_records[0].label == ARTIFACT_SAFE_FINGERPRINT_LABEL
    assert len(composed.manifest.fingerprint_records) == 1
    assert composed.manifest.metadata["source_reference_count"] == len(composed.source_artifacts)
    assert composed.manifest.metadata["fingerprint_record_count"] == len(composed.fingerprint_records)
    assert composed.fingerprint_records[0].metadata["fingerprint_policy"] == ARTIFACT_SAFE_FINGERPRINT_POLICY
    assert composed.fingerprint == composed.fingerprint_records[0].digest
    assert composed.manifest.fingerprint_records == composed.fingerprint_records
    assert composed.fingerprint == composed.manifest.fingerprint_records[0].digest
    assert (
        compare_config_artifact_fingerprints(
            left=composed.fingerprint_records[0],
            right=composed.manifest,
        ).status
        == "match"
    )
    assert (
        compare_config_artifact_fingerprints(
            left=composed.fingerprint_records[0],
            right=composed.manifest.to_dict(),
        ).status
        == "match"
    )


def test_compose_artifact_fingerprints_and_provenance_ignore_runtime_env_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "base.yaml"
    path.write_text(
        "name: demo\n"
        "paths:\n"
        "  root: ${oc.env:PHASE4_UNIT_ROOT}\n"
        "pipeline:\n"
        "  value: ${paths.root}/value\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE4_UNIT_ROOT", "/runtime/unit-one")
    first = compose_config(path)
    monkeypatch.setenv("PHASE4_UNIT_ROOT", "/runtime/unit-two")
    second = compose_config(path)

    first_paths = cast(dict[str, Any], first.resolved["paths"])
    second_paths = cast(dict[str, Any], second.resolved["paths"])
    assert first_paths["root"] == "/runtime/unit-one"
    assert second_paths["root"] == "/runtime/unit-two"
    assert first.fingerprint == second.fingerprint
    assert first.provenance.artifact_fingerprint == second.provenance.artifact_fingerprint
    assert first.provenance.metadata["fingerprint"] == second.provenance.metadata["fingerprint"]
    assert first.manifest.to_dict() == second.manifest.to_dict()
    assert [record.to_dict() for record in first.fingerprint_records] == [
        record.to_dict() for record in second.fingerprint_records
    ]


def test_internal_compose_helper_returns_composed_config(tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: demo\npipeline:\n  value: one\n", encoding="utf-8")

    composed = config_compose.compose_config(path, recipe_catalog=RecipeCatalog())

    assert isinstance(composed, ComposedConfig)
    assert composed.resolved["pipeline"] == {"value": "one"}
