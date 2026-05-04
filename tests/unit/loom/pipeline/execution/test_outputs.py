"""Unit tests for execution output validation."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import OutputSpec, StageSpec
from loom.pipeline.execution import OutputValidationError, validate_stage_outputs
from loom.pipeline.stores import LocalArtifactStore


def _stage() -> StageSpec:
    return StageSpec(
        name="build",
        target_path="tests.support.pipeline_execution_stages.JsonProducerStage",
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )


def test_validate_stage_outputs_accepts_declared_artifact(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    ref = store.save(
        {"x": 1},
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )

    assert validate_stage_outputs(
        stage=_stage(), outputs={"data": ref}, artifact_store=store
    ) == {"data": ref}


def test_validate_stage_outputs_rejects_contract_errors(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    ref = store.save(
        "bad",
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="text",
        codec_key="text.v1",
    )

    with pytest.raises(OutputValidationError, match="missing"):
        validate_stage_outputs(stage=_stage(), outputs={}, artifact_store=store)
    with pytest.raises(OutputValidationError, match="undeclared"):
        validate_stage_outputs(
            stage=_stage(), outputs={"data": ref, "extra": ref}, artifact_store=store
        )
    with pytest.raises(OutputValidationError, match="artifact_type"):
        validate_stage_outputs(
            stage=_stage(), outputs={"data": ref}, artifact_store=store
        )


def test_validate_stage_outputs_rejects_non_string_output_names(
    tmp_path: Path,
) -> None:
    store = LocalArtifactStore(tmp_path)
    ref = store.save(
        {"x": 1},
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )

    malformed_outputs = cast(Mapping[str, object], {"data": ref, 1: ref})
    with pytest.raises(OutputValidationError, match="non-empty strings"):
        validate_stage_outputs(
            stage=_stage(),
            outputs=malformed_outputs,
            artifact_store=store,
        )
