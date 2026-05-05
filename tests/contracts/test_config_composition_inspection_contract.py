"""Contract tests for public composition inspection output."""

from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config import inspect_config_composition

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
        "runtime_interpolation",
        "validation",
        "redaction",
        "provenance",
        "fingerprint",
        "artifact_placeholders",
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
    assert len(inspection.manifest.fingerprint_records) == 2
    assert len(inspection.source_artifacts) == 1
    assert inspection.manifest.metadata["source_reference_count"] == len(inspection.source_artifacts)
    assert inspection.manifest.metadata["fingerprint_record_count"] == len(inspection.fingerprint_records)
