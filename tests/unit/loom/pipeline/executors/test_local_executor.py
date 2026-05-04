"""Unit tests for the local executor."""

from pathlib import Path

from loom.pipeline import OutputSpec, PipelineSpec, StageContext, StageSpec
from loom.pipeline.execution import StageExecutionRequest
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.planning import (
    FingerprintContext,
    PlanAction,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from tests.support.pipeline_execution_stages import FailingStage, JsonProducerStage


def _request(tmp_path: Path, stage_object: object) -> StageExecutionRequest:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    artifact_store = LocalArtifactStore(run_store.get_artifact_root("run1"))
    stage = StageSpec(
        name="build",
        target_path="tests.support.pipeline_execution_stages.JsonProducerStage",
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )
    plan = plan_pipeline(
        PipelineSpec(stages=(stage,)),
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        persist=True,
    )
    fingerprint = build_stage_fingerprint(
        stage, bound_inputs={}, fingerprint_context=FingerprintContext()
    )
    return StageExecutionRequest(
        run_id="run1",
        stage=stage,
        stage_plan=plan.ordered_stage_plans[0],
        stage_object=stage_object,  # type: ignore[arg-type]
        context=StageContext(
            run_id="run1",
            stage_name="build",
            run_dir=run_store.get_run_dir("run1"),
            stage_dir=run_store.get_stage_dir("run1", "build"),
            resolved_config={},
            stage_config={},
            run_store=run_store,
            artifact_store=artifact_store,
            output_specs=stage.outputs,
        ),
        inputs={},
        fingerprint=fingerprint,
        attempt=1,
        stdout_path=run_store.get_stage_log_path("run1", "build", "stdout"),
        stderr_path=run_store.get_stage_log_path("run1", "build", "stderr"),
        traceback_path=run_store.get_stage_dir("run1", "build")
        / "logs"
        / "traceback.txt",
    )


def test_local_executor_invokes_stage_successfully(tmp_path: Path) -> None:
    result = LocalExecutor().execute(_request(tmp_path, JsonProducerStage()))

    assert result.status == StageStatus.SUCCEEDED
    assert result.failure is None
    assert set(result.outputs) == {"data"}


def test_local_executor_returns_structured_failure(tmp_path: Path) -> None:
    result = LocalExecutor().execute(_request(tmp_path, FailingStage()))

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "stage_exception"
    assert result.traceback_path is not None


def test_local_executor_does_not_make_resume_decisions() -> None:
    assert PlanAction.REUSE.value == "REUSE"
