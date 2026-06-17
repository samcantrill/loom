"""Contract tests for public composition inspection output."""

from pathlib import Path
from typing import cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from weave import RecipeCatalog, inspect_config_composition
from weave._argv import parse_config_argv
from weave.compose import _inspect_config_composition_with_argv_scoped_overlays
from weave.fingerprints import ARTIFACT_SAFE_FINGERPRINT_LABEL

pytestmark = [pytest.mark.contract, pytest.mark.optional_dependency]


def test_inspection_shape_and_stage_contract(tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: base\npipeline:\n  value: 1\n", encoding="utf-8")

    inspection = inspect_config_composition(path)

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

    assert inspection.stage("source_load") is not None
    assert inspection.stage("runtime_interpolation") is not None
    assert inspection.stage("composed_config") is not None

    for stage in inspection.stages:
        assert isinstance(stage.name, str)
        assert stage.status == "completed"
        assert isinstance(stage.payload, dict)

    assert inspection.unresolved == inspection.to_composed_config().unresolved
    assert inspection.manifest.source_artifacts == (inspection.source_artifacts)
    assert len(inspection.manifest.fingerprint_records) == 1
    assert inspection.manifest.fingerprint_records[0].label == ARTIFACT_SAFE_FINGERPRINT_LABEL
    assert inspection.fingerprint == inspection.manifest.fingerprint_records[0].digest
    assert len(inspection.source_artifacts) == 1
    assert inspection.manifest.metadata["source_reference_count"] == len(inspection.source_artifacts)
    assert inspection.manifest.metadata["fingerprint_record_count"] == len(inspection.fingerprint_records)


def test_inspection_raw_snapshot_default_bundle_is_metadata_only(tmp_path: Path) -> None:
    path = tmp_path / "base.yaml"
    path.write_text("name: base\npipeline:\n  value: 1\n", encoding="utf-8")

    inspection = inspect_config_composition(path)
    bundle = inspection.raw_source_snapshots

    assert bundle.enabled is False
    assert not bundle.payloads
    assert bundle.references
    manifest_refs = cast(
        list[dict[str, object]],
        cast(dict[str, object], inspection.manifest.to_dict()["metadata"])["raw_source_snapshot_references"],
    )
    provenance_refs = cast(
        list[dict[str, object]],
        cast(dict[str, object], inspection.provenance.to_dict()["metadata"])["raw_source_snapshot_references"],
    )
    assert manifest_refs
    assert provenance_refs == manifest_refs
    assert manifest_refs[0]["availability"] == "disabled"
    assert manifest_refs[0]["reason"] == "not_requested"
    assert manifest_refs[0]["payload_id"] is None



def test_private_argv_scoped_overlay_inspection_stage_is_argv_only(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    overlay = tmp_path / "configs" / "data" / "data_A.yaml"
    overlay.parent.mkdir(parents=True)
    base.write_text("data:\n  value: base\n", encoding="utf-8")
    overlay.write_text("value: overlay\n", encoding="utf-8")

    public_inspection = inspect_config_composition(base)
    parsed = parse_config_argv(["run", str(base), "data/=data_A"], command_choices={"run"})
    argv_inspection = _inspect_config_composition_with_argv_scoped_overlays(
        base,
        recipe_catalog=RecipeCatalog(),
        argv_scoped_overlays=parsed.scoped_overlays,
    )

    public_stage_names = tuple(stage.name for stage in public_inspection.stages)
    argv_stage_names = tuple(stage.name for stage in argv_inspection.stages)
    assert "argv_scoped_overlays" not in public_stage_names
    assert "argv_scoped_overlays" in argv_stage_names
    assert argv_stage_names.index("argv_scoped_overlays") == argv_stage_names.index("file_include_expansion") + 1
    assert argv_stage_names.index("argv_scoped_overlays") < argv_stage_names.index("recipe_argument_interpolation")
