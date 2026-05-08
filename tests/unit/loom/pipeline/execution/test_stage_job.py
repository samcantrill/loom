"""Unit tests for self-finalizing stage-job continuation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import (
    ContinuationStateError,
    StageJobRunRequest,
    UnsupportedContinuationExecutorError,
    prepare_stage_attempt,
    run_stage_job,
)
from loom.pipeline.execution.lifecycle import write_run_status
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions, RunOptions, build_runtime_metadata
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _producer_stage() -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(
            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
        ),
        outputs={"data": OutputSpec(artifact_type="json")},
    )


def _bad_output_stage() -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(
            target_path="tests.support.pipeline_execution_stages.BadOutputStage"
        ),
        outputs={"data": OutputSpec(artifact_type="json")},
    )


def _consumer_stage() -> StageSpec:
    return StageSpec(
        name="consume",
        factory=StageFactorySpec(
            target_path="tests.support.pipeline_execution_stages.TextConsumerStage"
        ),
        inputs={"data": "build.data"},
        outputs={"text": OutputSpec(artifact_type="text", codec_key="text.v1")},
    )


def _prepare_run(
    tmp_path: Path,
    *,
    stages: tuple[StageSpec, ...] | None = None,
) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    spec = PipelineSpec(stages=stages or (_producer_stage(),))
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        build_runtime_metadata(
            RunOptions(run_uri=run_uri, executor="local"),
            stage_ids=spec.stage_names,
        ).to_dict(),
    )
    stage_plan = next(item for item in plan.ordered_stage_plans if item.stage_name == "build")
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=stage_plan,
        resolved_runtime=ResolvedStageRuntimeOptions(stage_id="build", executor="local"),
        executor_name="local",
        clock=lambda: "2020-01-01T00:00:02Z",
    )
    return store, run_uri


def test_stage_job_rejects_recursive_executor_before_user_code(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")

    with pytest.raises(UnsupportedContinuationExecutorError):
        run_stage_job(
            run_store=store,
            request=StageJobRunRequest(
                run_uri="file:///tmp/missing",
                stage_name="build",
                executor="slurm-afterok",
            ),
        )


def test_stage_job_success_finalizes_target_and_run(tmp_path: Path) -> None:
    store, run_uri = _prepare_run(tmp_path)

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.run_status == RunStatus.SUCCEEDED
    assert store.read_stage_outputs(run_uri, "build") is not None
    assert store.read_stage_provenance(run_uri, "build") is not None
    assert store.read_artifact_index(run_uri)
    stage_status = store.read_stage_status(run_uri, "build")
    run_status = store.read_run_status(run_uri)
    assert stage_status is not None
    assert run_status is not None
    assert stage_status.status == StageStatus.SUCCEEDED
    assert run_status.status == RunStatus.SUCCEEDED


def test_stage_job_success_leaves_run_running_when_downstream_pending(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare_run(tmp_path, stages=(_producer_stage(), _consumer_stage()))

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.run_status == RunStatus.RUNNING
    assert store.read_stage_status(run_uri, "consume") is None
    run_status = store.read_run_status(run_uri)
    assert run_status is not None
    assert run_status.status == RunStatus.RUNNING


def test_stage_job_fails_before_user_code_when_prepared_state_missing(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare_run(tmp_path)
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    store.write_stage_status(
        run_uri,
        "build",
        status.__class__(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=status.attempt,
            updated_at=status.updated_at,
        ),
    )

    with pytest.raises(ContinuationStateError) as exc_info:
        run_stage_job(
            run_store=store,
            request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
        )

    assert exc_info.value.code == "execution.stage_job.insufficient_reconstruction_state"


def test_stage_job_records_failed_run_when_output_validation_fails(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare_run(tmp_path, stages=(_bad_output_stage(),))

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
    )

    assert result.status == StageStatus.FAILED
    assert result.run_status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "output_validation"
    stage_status = store.read_stage_status(run_uri, "build")
    run_status = store.read_run_status(run_uri)
    failure = store.read_stage_failure(run_uri, "build")
    assert stage_status is not None
    assert run_status is not None
    assert failure is not None
    assert stage_status.status == StageStatus.FAILED
    assert run_status.status == RunStatus.FAILED
    assert failure["failure_type"] == "output_validation"


def test_stage_job_rejects_worker_request_identity_mismatch_before_running(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare_run(tmp_path)
    raw_request = store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert isinstance(raw_request, dict)
    tampered_request = dict(raw_request)
    tampered_request["run_uri"] = "file:///tmp/other-run"
    store.write_stage_worker_request(run_uri, "build", tampered_request, attempt=1)

    with pytest.raises(ContinuationStateError) as exc_info:
        run_stage_job(
            run_store=store,
            request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
        )

    assert exc_info.value.code == "execution.stage_job.insufficient_reconstruction_state"
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.PENDING
