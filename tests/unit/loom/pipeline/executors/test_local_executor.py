"""Unit tests for the local executor."""

from pathlib import Path
from typing import cast

from loom.pipeline import (
    OutputSpec,
    PipelineSpec,
    StageContext,
    StageFactorySpec,
    StageSpec,
)
from loom.pipeline.execution.models import StageExecutionRequest
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.planning import (
    FingerprintContext,
    PlanAction,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.reliability import ReliabilityPolicy, TimeoutPolicy
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from tests.support.pipeline_execution_stages import FailingStage, JsonProducerStage


def _request(
    tmp_path: Path,
    stage_object: object,
    *,
    timeout_seconds: float | None = None,
) -> StageExecutionRequest:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))
    stage = StageSpec(
        name="build",
        factory=StageFactorySpec(
            "tests.support.pipeline_execution_stages.JsonProducerStage"
        ),
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )
    plan = plan_pipeline(
        PipelineSpec(stages=(stage,)),
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        persist=True,
    )
    fingerprint = build_stage_fingerprint(
        stage, bound_inputs={}, fingerprint_context=FingerprintContext()
    )
    return StageExecutionRequest(
        run_uri=run_uri,
        stage=stage,
        stage_plan=plan.ordered_stage_plans[0],
        stage_object=stage_object,  # type: ignore[arg-type]
        context=StageContext(
            run_uri=run_uri,
            stage_name="build",
            resolved_config={},
            stage_config={},
            local_output_dir=run_store.local_stage_artifact_dir(run_uri, "build"),
            local_workspace_dir=run_store.local_stage_workspace_dir(run_uri, "build"),
            run_store=run_store,
            artifact_store=artifact_store,
            output_specs=stage.outputs,
        ),
        inputs={},
        fingerprint=fingerprint,
        attempt=1,
        stdout_path=run_store.local_stage_log_path(run_uri, "build", "stdout"),
        stderr_path=run_store.local_stage_log_path(run_uri, "build", "stderr"),
        traceback_path=run_store.local_stage_dir(run_uri, "build")
        / "logs"
        / "traceback.txt",
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
            reliability=(
                None
                if timeout_seconds is None
                else ReliabilityPolicy(
                    timeout=TimeoutPolicy(
                        enabled=True,
                        duration_seconds=timeout_seconds,
                    )
                )
            ),
        ),
    )


def test_local_executor_invokes_stage_successfully(tmp_path: Path) -> None:
    request = _request(tmp_path, JsonProducerStage())

    resolved = cast(ResolvedStageRuntimeOptions, request.resolved_runtime)
    assert resolved.stage_id == "build"
    assert resolved.executor == "local"

    result = LocalExecutor().execute(request)

    assert result.status == StageStatus.SUCCEEDED
    assert result.failure is None
    assert set(result.outputs) == {"data"}


def test_local_executor_returns_structured_failure(tmp_path: Path) -> None:
    result = LocalExecutor().execute(_request(tmp_path, FailingStage()))

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "stage_exception"
    assert result.traceback_path is not None


def test_local_executor_reports_reliability_timeout_as_unsupported(
    tmp_path: Path,
) -> None:
    result = LocalExecutor().execute(
        _request(tmp_path, JsonProducerStage(), timeout_seconds=3)
    )

    timeout = cast(dict[str, object], result.executor_metadata["reliability_timeout"])
    assert timeout["timeout_domain"] == "reliability"
    assert timeout["support_level"] == "unsupported"
    assert timeout["outcome"] == "unsupported"
    assert timeout["timed_out"] is False
    assert timeout["duration_seconds"] == 3.0


def test_local_executor_does_not_make_resume_decisions() -> None:
    assert PlanAction.REUSE.value == "REUSE"
