"""Unit tests for StageContext."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.context import ProcessContainmentOwner, StageContext
from loom.pipeline.early_stopping import EarlyStopSignal
from loom.pipeline.errors import PipelineValidationError
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.serialization import PlainData


def test_context_normalizes_paths_and_mappings() -> None:
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config={"pipeline": {"name": "x"}},
        stage_config={"v": 1},
        provenance={"git": {"sha": "123"}},
        metadata={"note": "ok"},
    )
    pipeline_config = cast(dict[str, PlainData], context.resolved_config["pipeline"])
    assert pipeline_config["name"] == "x"


def test_context_process_containment_owner_defaults_to_stage_and_is_immutable() -> None:
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config={},
        stage_config={},
    )

    assert context.process_containment_owner is ProcessContainmentOwner.STAGE
    with pytest.raises(AttributeError):
        context.process_containment_owner = ProcessContainmentOwner.OUTER_BOUNDARY  # type: ignore[misc]


def test_process_containment_owner_has_exactly_two_public_values() -> None:
    assert tuple(ProcessContainmentOwner) == (
        ProcessContainmentOwner.STAGE,
        ProcessContainmentOwner.OUTER_BOUNDARY,
    )
    assert ProcessContainmentOwner.STAGE.value == "stage"
    assert ProcessContainmentOwner.OUTER_BOUNDARY.value == "outer_boundary"


def test_context_process_containment_owner_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        StageContext(
            "run-1",
            "build",
            {},
            {},
            {},
            {},
            {},
            None,
            None,
            None,
            None,
            ProcessContainmentOwner.OUTER_BOUNDARY,  # type: ignore[reportCallIssue]  # Deliberately invalid positional owner.
        )


def test_context_requires_exact_process_containment_owner_enum() -> None:
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config={},
        stage_config={},
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
    )

    assert context.process_containment_owner is ProcessContainmentOwner.OUTER_BOUNDARY
    for invalid_value in ("stage", object()):
        with pytest.raises(PipelineValidationError, match="process_containment_owner"):
            StageContext(
                run_uri="run-1",
                stage_name="build",
                resolved_config={},
                stage_config={},
                process_containment_owner=cast(ProcessContainmentOwner, invalid_value),
            )


def test_context_freezes_nested_mappings_and_inputs() -> None:
    resolved: Any = {"pipeline": {"name": "x"}}
    inputs: dict[str, ArtifactRef] = {}
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config=resolved,
        stage_config={},
        inputs=inputs,
    )

    resolved["pipeline"]["name"] = "changed"
    inputs["late"] = cast(ArtifactRef, object())

    assert cast(Any, context.resolved_config["pipeline"])["name"] == "x"
    assert "late" not in context.inputs
    with pytest.raises(TypeError):
        cast(dict[str, object], context.resolved_config["pipeline"])["name"] = "no"
    with pytest.raises(TypeError):
        cast(dict[str, ArtifactRef], context.inputs)["late"] = cast(
            ArtifactRef, object()
        )


def test_context_rejects_non_plain_data_config() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_uri="run-1",
            stage_name="build",
            resolved_config=cast(dict[str, PlainData], {0: "bad-key"}),
            stage_config={},
        )


def test_context_requires_identity_strings() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_uri="",
            stage_name="build",
            resolved_config={},
            stage_config={},
        )


def test_context_stop_early_raises_typed_signal() -> None:
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config={},
        stage_config={},
    )

    with pytest.raises(EarlyStopSignal) as exc_info:
        context.stop_early("enough evidence", detail={"score": 1})

    signal = exc_info.value
    assert signal.message == "enough evidence"
    assert signal.detail == {"score": 1}
    reason = signal.to_lifecycle_reason()
    assert reason.code == "early_stop"
    assert reason.message == "enough evidence"
    assert reason.detail == {"score": 1}


def test_context_stop_early_rejects_non_plain_detail() -> None:
    context = StageContext(
        run_uri="run-1",
        stage_name="build",
        resolved_config={},
        stage_config={},
    )

    with pytest.raises(ValueError, match="plain data"):
        context.stop_early(
            "bad detail", detail=cast(dict[str, PlainData], {"x": object()})
        )


def test_context_helpers_save_and_register_declared_outputs(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))
    context = StageContext(
        run_uri=run_uri,
        stage_name="build",
        resolved_config={},
        stage_config={},
        local_output_dir=run_store.local_stage_artifact_dir(run_uri, "build"),
        local_workspace_dir=run_store.local_stage_workspace_dir(run_uri, "build"),
        artifact_store=artifact_store,
        output_specs={
            "data": OutputSpec(artifact_type="json", codec_key="json.v1"),
            "report": OutputSpec(artifact_type="text", codec_key="text.v1"),
        },
    )

    assert context.local_output_path("data", suffix=".json").name == "data.json"
    workspace_path = context.local_workspace_path("tmp", "work.txt")
    workspace_path.write_text("workspace only", encoding="utf-8")
    assert workspace_path.name == "work.txt"
    ref = context.save_artifact(
        "data",
        {"ok": True},
        artifact_type="json",
        codec_key="json.v1",
    )
    report_path = context.local_output_path("report", suffix=".txt")
    report_path.write_text("published", encoding="utf-8")
    report_ref = context.register_local_artifact(
        "report",
        report_path,
        artifact_type="text",
        codec_key="text.v1",
    )

    assert ref.producer_stage == "build"
    assert artifact_store.exists(ref)
    assert report_ref.producer_stage == "build"
    assert artifact_store.exists(report_ref)


def test_context_helpers_reject_missing_runtime_services(tmp_path: Path) -> None:
    context = StageContext(
        run_uri="run1",
        stage_name="build",
        resolved_config={},
        stage_config={},
        output_specs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )

    with pytest.raises(PipelineValidationError, match="local_output_dir"):
        context.local_output_path("data")
    with pytest.raises(PipelineValidationError, match="artifact_store"):
        context.save_artifact("data", {}, artifact_type="json", codec_key="json.v1")
    with pytest.raises(PipelineValidationError, match="artifact_store"):
        context.register_artifact(
            "data",
            "artifact.bin",
            artifact_type="json",
            codec_key="json.v1",
        )
    with pytest.raises(PipelineValidationError, match="local_workspace_dir"):
        context.local_workspace_path("tmp")
    with pytest.raises(PipelineValidationError, match="not declared"):
        context.local_output_path("other")
    with pytest.raises(PipelineValidationError, match="not available"):
        context.load_input("missing")
    with pytest.raises(PipelineValidationError, match="not declared"):
        context.save_artifact("other", {}, artifact_type="json", codec_key="json.v1")
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_uri="run-1",
            stage_name="",
            resolved_config={},
            stage_config={},
        )


def test_context_load_input(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    saved = artifact_store.save(
        {"value": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    context = StageContext(
        run_uri="run1",
        stage_name="build",
        resolved_config={},
        stage_config={},
        inputs={"data": saved},
        artifact_store=artifact_store,
    )

    assert context.load_input("data") == {"value": 1}
