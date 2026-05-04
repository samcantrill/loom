"""Unit tests for direct resume checks."""

from dataclasses import replace
from pathlib import Path

import pytest

from loom.io import uri_to_path
from loom.pipeline import OutputSpec, StageFactorySpec, StageSpec, StageStatus, StageStatusRecord
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
        factory=StageFactorySpec(target_path="project.Build", init={}),
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
    artifact_store = LocalArtifactStore(run_store.local_artifact_root("run1"))
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


def test_direct_resume_flags_legacy_v1_fingerprints_as_policy_changed(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status("run1", "build", _status("run1"))
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(
        "run1",
        "build",
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "policy_name": "loom.stage.v1",
            "policy_version": 1,
            "fingerprint": "sha256:" + "9" * 64,
            "payload": {
                "schema_version": 1,
                "policy_name": "loom.stage.v1",
                "policy_version": 1,
                "stage_name": "build",
                "target_path": "project.Build",
                "stage_config": {},
                "declared_inputs": {},
                "bound_inputs": {},
                "declared_outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                        "schema_version": None,
                        "metadata": {},
                    }
                },
                "python_version": "3.12.0",
                "loom_version": "0.1.0",
                "git": {},
                "dependencies": {},
                "extra": {},
            },
            "inputs_summary": {
                "stage_name": "build",
                "factory_target": "project.Build",
                "input_names": [],
                "output_names": ["data"],
            },
        },
        attempt=1,
    )
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

    assert result.base_action == PlanAction.STALE
    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.FINGERPRINT_POLICY_CHANGED


def test_direct_resume_marks_running_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        StageStatusRecord(
            run_id="run1",
            stage_name="build",
            status=StageStatus.RUNNING,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
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
    assert result.check.reasons[0].code == PlanReasonCode.PRIOR_STATUS_RUNNING


def test_direct_resume_marks_failed_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        StageStatusRecord(
            run_id="run1",
            stage_name="build",
            status=StageStatus.FAILED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
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
    assert result.check.reasons[0].code == PlanReasonCode.PRIOR_STATUS_NOT_SUCCEEDED


def test_direct_resume_does_not_reuse_missing_artifact(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
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


def test_direct_resume_marks_missing_outputs_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    run_store.write_stage_status(
        "run1",
        "build",
        StageStatusRecord(
            run_id="run1",
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
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
    assert result.check.reasons[0].code == PlanReasonCode.MISSING_OUTPUTS


def test_direct_resume_refuses_corrupt_outputs_json(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        StageStatusRecord(
            run_id="run1",
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_fingerprint("run1", "build", current.to_dict(), attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    with pytest.raises(ResumeStateError, match="corrupt"):
        # Corrupt the persisted output document, then attempt resume.
        atomic_path = run_store.local_stage_dir("run1", "build") / "outputs.json"
        atomic_path.write_text("[\"bad\"]", encoding="utf-8")

        check_stage_resume(
            stage,
            run_id="run1",
            run_store=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_rejects_corrupt_prior_fingerprint(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        StageStatusRecord(
            run_id="run1",
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(
        "run1", "build", {"schema_version": "bad"}, attempt=1
    )

    with pytest.raises(ResumeStateError, match="malformed prior fingerprint"):
        check_stage_resume(
            stage,
            run_id="run1",
            run_store=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_checks_artifact_checksum(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        _status("run1"),
    )
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint("run1", "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index("run1", {"build.data": output})

    path = artifact_store.local_path(output)
    path.write_text("corrupted", encoding="utf-8")
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
    assert result.check.reasons[0].code == PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH


def test_direct_resume_flags_artifact_index_conflict(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(
        "run1",
        "build",
        _status("run1"),
    )
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint("run1", "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index("run1", {"build.data": replace(output, artifact_id="build.other")})

    with pytest.raises(ResumeStateError, match="artifact index conflict for build.data"):
        check_stage_resume(
            stage,
            run_id="run1",
            run_store=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_raises_on_corrupt_prior_state(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    (run_store.local_stage_dir("run1", "build") / "status.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_store.local_stage_dir("run1", "build") / "status.json").write_text(
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
