"""Unit tests for StageContext."""

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.context import StageContext
from loom.pipeline.errors import PipelineValidationError
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.serialization import PlainData


def test_context_normalizes_paths_and_mappings() -> None:
    context = StageContext(
        run_id="run-1",
        stage_name="build",
        run_dir=cast(Path, "tmp/run"),
        stage_dir=Path("tmp/run/build"),
        resolved_config={"pipeline": {"name": "x"}},
        stage_config={"v": 1},
        provenance={"git": {"sha": "123"}},
        metadata={"note": "ok"},
    )
    assert context.run_dir == Path("tmp/run")
    assert context.stage_dir == Path("tmp/run/build")
    pipeline_config = cast(dict[str, PlainData], context.resolved_config["pipeline"])
    assert pipeline_config["name"] == "x"


def test_context_rejects_non_plain_data_config() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="run-1",
            stage_name="build",
            run_dir=Path("tmp/run"),
            stage_dir=Path("tmp/run/build"),
            resolved_config=cast(dict[str, PlainData], {0: "bad-key"}),
            stage_config={},
        )


def test_context_requires_identity_strings() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="",
            stage_name="build",
            run_dir=Path("tmp/run"),
            stage_dir=Path("tmp/run/build"),
            resolved_config={},
            stage_config={},
        )


def test_context_helpers_save_and_register_declared_outputs(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    artifact_store = LocalArtifactStore(run_store.local_artifact_root("run1"))
    context = StageContext(
        run_id="run1",
        stage_name="build",
        run_dir=run_store.local_run_dir("run1"),
        stage_dir=run_store.local_stage_dir("run1", "build"),
        resolved_config={},
        stage_config={},
        run_store=run_store,
        artifact_store=artifact_store,
        output_specs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )

    assert context.output_path("data", suffix=".json").name == "data.json"
    ref = context.save_artifact(
        "data",
        {"ok": True},
        artifact_type="json",
        codec_key="json.v1",
    )

    assert ref.producer_stage == "build"
    assert artifact_store.exists(ref)


def test_context_helpers_reject_missing_runtime_services(tmp_path: Path) -> None:
    context = StageContext(
        run_id="run1",
        stage_name="build",
        run_dir=tmp_path,
        stage_dir=tmp_path / "build",
        resolved_config={},
        stage_config={},
        output_specs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )

    with pytest.raises(PipelineValidationError, match="run_store"):
        context.output_path("data")
    with pytest.raises(PipelineValidationError, match="artifact_store"):
        context.save_artifact("data", {}, artifact_type="json", codec_key="json.v1")
    with pytest.raises(PipelineValidationError, match="not declared"):
        context.output_path("other")
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="run-1",
            stage_name="",
            run_dir=Path("tmp/run"),
            stage_dir=Path("tmp/run/build"),
            resolved_config={},
            stage_config={},
        )
