"""Unit tests for direct resume checks."""

from pathlib import Path

import pytest

from loom.io import uri_to_path
from loom.pipeline import OutputSpec, StageSpec, StageStatus, StageStatusRecord
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    ResumeOptions,
    ResumeStateError,
    build_stage_fingerprint,
)
from loom.pipeline.planning.resume import check_stage_resume
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore


def _stage() -> StageSpec:
    return StageSpec(
        name="build",
        target_path="project.Build",
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )


def _status(run_id: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_id=run_id,
        stage_name="build",
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _stores(tmp_path: Path) -> tuple[LocalRunStore, LocalArtifactStore]:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    artifact_store = LocalArtifactStore(run_store.get_artifact_root("run1"))
    return run_store, artifact_store


def test_direct_resume_requires_positive_prior_state(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})

    result = check_stage_resume(
        stage,
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.NO_PRIOR_STATUS


def test_direct_resume_reuses_valid_succeeded_outputs(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status("run1", "build", _status("run1"))
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint("run1", "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index("run1", {"build.data": output})

    result = check_stage_resume(
        stage,
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.REUSE
    assert result.check.outputs == {"data": output}


def test_direct_resume_does_not_reuse_missing_artifact(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    uri_to_path(output.uri).unlink()
    run_store.write_stage_status("run1", "build", _status("run1"))
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint("run1", "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.ARTIFACT_MISSING


def test_direct_resume_raises_on_corrupt_prior_state(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    (run_store.get_stage_dir("run1", "build") / "status.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_store.get_stage_dir("run1", "build") / "status.json").write_text(
        "{bad json", encoding="utf-8"
    )

    with pytest.raises(ResumeStateError):
        check_stage_resume(
            _stage(),
            run_id="run1",
            run_store=run_store,
            artifact_store=artifact_store,
            current_fingerprint=build_stage_fingerprint(_stage(), bound_inputs={}),
            resume=ResumeOptions(),
            eligible_to_run=True,
        )
