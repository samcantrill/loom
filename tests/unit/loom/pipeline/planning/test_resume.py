"""Unit tests for direct resume checks."""

from dataclasses import replace
from pathlib import Path

import pytest

from loom.io import uri_to_path
from loom.fingerprints import hash_mapping
from loom.pipeline import (
    OutputSpec,
    StageFactorySpec,
    StageSpec,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    ResumeOptions,
    ResumeStateError,
    StageFingerprintRecord,
    build_stage_fingerprint,
)
from loom.pipeline.planning.resume import check_stage_resume
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _stage() -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(target_path="project.Build", init={}),
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )


def _status(run_uri: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_uri=run_uri,
        stage_name="build",
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _stores(tmp_path: Path) -> tuple[LocalRunStore, LocalArtifactStore, str]:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))
    return run_store, artifact_store, run_uri


def test_direct_resume_requires_positive_prior_state(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.NO_PRIOR_STATUS


def test_direct_resume_reuses_valid_succeeded_outputs(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(run_uri, "build", _status(run_uri))
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index(run_uri, {"build.data": output})

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.REUSE
    assert result.check.outputs == {"data": output}


def test_direct_resume_flags_changed_policy_in_current_format(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    prior = StageFingerprintRecord.create(
        payload=replace(current.payload, policy_version=1),
        algorithm=current.algorithm,
        inputs_summary=current.inputs_summary,
    )
    output = artifact_store.save(
        {"x": 1}, stage_name="build", name="data", artifact_type="json", codec_key="json.v1"
    )
    run_store.write_stage_status(run_uri, "build", _status(run_uri))
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", prior.to_dict(), attempt=1)
    run_store.write_artifact_index(run_uri, {"build.data": output})

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert prior.schema_version == current.schema_version == 2
    assert result.base_action == PlanAction.STALE
    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.FINGERPRINT_POLICY_CHANGED


def test_direct_resume_rejects_retired_fingerprint_without_changes(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    retired = current.to_dict()
    payload = current.payload.to_dict()
    payload["schema_version"] = 1
    retired.update(schema_version=1, payload=payload, fingerprint=hash_mapping(payload))
    run_store.write_stage_status(run_uri, "build", _status(run_uri))
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", retired, attempt=1)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ResumeStateError, match="schema_version must be 2"):
        check_stage_resume(
            stage,
            run_uri=run_uri,
            stage_state=run_store,
            artifact_index=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )

    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_direct_resume_marks_running_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.RUNNING,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.PRIOR_STATUS_RUNNING


def test_direct_resume_marks_submitted_as_non_reusable(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUBMITTED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.status == "SUBMITTED"
    assert result.check.reasons[0].code == PlanReasonCode.PRIOR_STATUS_NOT_SUCCEEDED


def test_direct_resume_marks_failed_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.FAILED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.PRIOR_STATUS_NOT_SUCCEEDED


def test_direct_resume_does_not_reuse_missing_artifact(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
    run_store.write_stage_status(run_uri, "build", _status(run_uri))
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.ARTIFACT_MISSING


def test_direct_resume_marks_missing_outputs_as_stale(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    stage = _stage()
    current = build_stage_fingerprint(stage, bound_inputs={})
    run_store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)

    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )

    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.MISSING_OUTPUTS


def test_direct_resume_refuses_corrupt_outputs_json(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    with pytest.raises(ResumeStateError, match="corrupt"):
        # Corrupt the persisted output document, then attempt resume.
        atomic_path = run_store.local_stage_dir(run_uri, "build") / "outputs.json"
        atomic_path.write_text('["bad"]', encoding="utf-8")

        check_stage_resume(
            stage,
            run_uri=run_uri,
            stage_state=run_store,
            artifact_index=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_rejects_corrupt_prior_fingerprint(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(
        run_uri, "build", {"schema_version": "bad"}, attempt=1
    )

    with pytest.raises(ResumeStateError, match="malformed prior fingerprint"):
        check_stage_resume(
            stage,
            run_uri=run_uri,
            stage_state=run_store,
            artifact_index=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_checks_artifact_checksum(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        _status(run_uri),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index(run_uri, {"build.data": output})

    path = artifact_store.local_path(output)
    path.write_text("corrupted", encoding="utf-8")
    result = check_stage_resume(
        stage,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current,
        resume=ResumeOptions(),
        eligible_to_run=True,
    )
    assert result.final_action == PlanAction.RUN
    assert result.check.reasons[0].code == PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH


def test_direct_resume_flags_artifact_index_conflict(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
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
        run_uri,
        "build",
        _status(run_uri),
    )
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(run_uri, "build", current.to_dict(), attempt=1)
    run_store.write_artifact_index(
        run_uri, {"build.data": replace(output, artifact_id="build.other")}
    )

    with pytest.raises(
        ResumeStateError, match="artifact index conflict for build.data"
    ):
        check_stage_resume(
            stage,
            run_uri=run_uri,
            stage_state=run_store,
            artifact_index=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current,
            resume=ResumeOptions(),
            eligible_to_run=True,
        )


def test_direct_resume_raises_on_corrupt_prior_state(tmp_path: Path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    (run_store.local_stage_dir(run_uri, "build") / "status.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_store.local_stage_dir(run_uri, "build") / "status.json").write_text(
        "{bad json", encoding="utf-8"
    )

    with pytest.raises(ResumeStateError):
        check_stage_resume(
            _stage(),
            run_uri=run_uri,
            stage_state=run_store,
            artifact_index=run_store,
            artifact_store=artifact_store,
            current_fingerprint=build_stage_fingerprint(_stage(), bound_inputs={}),
            resume=ResumeOptions(),
            eligible_to_run=True,
        )
