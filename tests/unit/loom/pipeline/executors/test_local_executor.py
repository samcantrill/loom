"""Unit tests for the local executor."""

from pathlib import Path
import json
from dataclasses import replace
from typing import Any, cast

from loom.pipeline import (
    OutputSpec,
    PipelineSpec,
    StageContext,
    StageFactorySpec,
    StageSpec,
)
from loom.pipeline.execution import StageReportedFailure
from loom.diagnostics import render_diagnostic_failure
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


def test_local_executor_failure_is_portable_without_its_traceback_file(
    tmp_path: Path,
) -> None:
    class NestedFailureStage:
        def run(self, context: StageContext, inputs: object) -> object:
            del context, inputs
            try:
                raise FileNotFoundError("missing /worker/dataset/input.json")
            except FileNotFoundError as cause:
                cause.add_note("Configure the dataset root for the selected worker.")
                raise RuntimeError("training stage input preparation failed") from cause

    result = LocalExecutor().execute(_request(tmp_path, NestedFailureStage()))

    assert result.status is StageStatus.FAILED
    assert result.failure is not None
    assert result.traceback_path is not None
    Path(result.traceback_path).unlink()
    rendered = render_diagnostic_failure(result.failure.details["diagnostic_failure"])
    assert "training stage input preparation failed" in rendered
    assert "missing /worker/dataset/input.json" in rendered
    assert "Configure the dataset root" in str(result.failure.details["traceback"])


def test_local_executor_preserves_reported_failure_without_traceback(
    tmp_path: Path,
) -> None:
    class ReportedFailureStage:
        def run(self, context: StageContext, inputs: object) -> object:
            del context, inputs
            raise StageReportedFailure({"schema": "domain.failure.v1", "value": [1]})

    result = LocalExecutor().execute(_request(tmp_path, ReportedFailureStage()))

    assert result.status is StageStatus.FAILED
    assert result.traceback_path is None
    assert result.failure is not None
    assert result.failure.message == "stage reported a domain failure"
    assert (
        result.failure.exception_type == "loom.pipeline.execution.StageReportedFailure"
    )
    assert result.failure.details == {
        "domain_failure": {"schema": "domain.failure.v1", "value": (1,)}
    }


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


def test_local_stage_and_result_share_admitted_request_view_before_stage_work(
    tmp_path: Path,
) -> None:
    seen = []

    class InspectingStage:
        def run(self, context: StageContext, inputs: object) -> object:
            seen.append(context.metadata["execution_request"])
            return {}

    request = _request(tmp_path, InspectingStage())
    runtime = ResolvedStageRuntimeOptions(
        stage_id="build",
        resources={"entries": {"cpu": {"kind": "cpu", "amount": 4}}},
        resource_policy={"enforce": []},
    )
    request = replace(request, resolved_runtime=runtime)
    result = LocalExecutor().execute(request)
    assert result.status is StageStatus.SUCCEEDED
    assert len(seen) == 1
    assert seen[0]["resolved_runtime"]["resources"]["entries"]["cpu"]["amount"] == 4
    public = cast(dict[str, Any], result.to_safe_metadata())
    assert public["executor_metadata"]["request"] == request.to_safe_metadata()
    assert public["executor_metadata"]["execution_kind"] == "in_process"
    assert public["executor_metadata"]["command"] is None
    assert public["status"] == StageStatus.SUCCEEDED.value
    assert str(tmp_path) not in json.dumps(public)
    assert "execution_request" not in request.context.metadata


def test_early_stop_retains_requested_resources_and_safe_execution_view(
    tmp_path: Path,
) -> None:
    class EarlyStoppingStage:
        def run(self, context: StageContext, inputs: object) -> object:
            context.stop_early("enough evidence")

    request = replace(
        _request(tmp_path, EarlyStoppingStage()),
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            resources={"entries": {"cpu": {"kind": "cpu", "amount": 4}}},
            resource_policy={"enforce": []},
        ),
    )
    result = LocalExecutor().execute(request)
    assert result.status is StageStatus.CANCELLED
    assert result.failure is None
    public = cast(dict[str, Any], result.to_safe_metadata())
    assert public["executor_metadata"]["request"] == request.to_safe_metadata()
    assert public["executor_metadata"]["execution_kind"] == "in_process"
    assert public["executor_metadata"]["command"] is None
    assert str(tmp_path) not in json.dumps(public)
