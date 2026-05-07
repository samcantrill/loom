"""Unit tests for the subprocess executor."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline import (
    OutputSpec,
    PipelineSpec,
    StageContext,
    StageFactorySpec,
    StageSpec,
)
from loom.pipeline.execution import (
    ExecutionFailure,
    StageExecutionRequest,
    StageWorkerResult,
)
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_RESULT_SCHEMA_VERSION,
)
from loom.pipeline.executors import (
    SubprocessExecutor,
    SubprocessRunResult,
)
from loom.pipeline.executors.subprocess import build_stage_worker_command
from loom.pipeline.planning import FingerprintContext, build_stage_fingerprint, plan_pipeline
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from tests.support.pipeline_execution_stages import JsonProducerStage


def _request(tmp_path: Path) -> tuple[LocalRunStore, str, StageExecutionRequest]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    artifact_store = LocalArtifactStore(store.local_artifact_root(run_uri))
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
        run_store=store,
        artifact_store=artifact_store,
        persist=True,
    )
    fingerprint = build_stage_fingerprint(
        stage, bound_inputs={}, fingerprint_context=FingerprintContext()
    )
    request = StageExecutionRequest(
        run_uri=run_uri,
        stage=stage,
        stage_plan=plan.ordered_stage_plans[0],
        stage_object=JsonProducerStage(),
        context=StageContext(
            run_uri=run_uri,
            stage_name="build",
            resolved_config={},
            stage_config={},
            local_output_dir=store.local_stage_artifact_dir(run_uri, "build"),
            local_workspace_dir=store.local_stage_workspace_dir(run_uri, "build"),
            run_store=store,
            artifact_store=artifact_store,
            output_specs=stage.outputs,
        ),
        inputs={},
        fingerprint=fingerprint,
        attempt=1,
        stdout_path=store.local_stage_log_path(run_uri, "build", "stdout"),
        stderr_path=store.local_stage_log_path(run_uri, "build", "stderr"),
        traceback_path=store.local_stage_dir(run_uri, "build")
        / "logs"
        / "traceback.txt",
    )
    return store, run_uri, request


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build/data",
        uri="file:///tmp/build-data.json",
        artifact_type="json",
        codec_key="json.v1",
        producer_stage="build",
    )


def _worker_success(run_uri: str) -> StageWorkerResult:
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        status=StageStatus.SUCCEEDED,
        started_at="2020-01-01T00:00:01Z",
        finished_at="2020-01-01T00:00:02Z",
        executor_name="subprocess",
        outputs={"data": _artifact()},
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        exit_code=0,
    )


def _worker_failure(run_uri: str) -> StageWorkerResult:
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:02Z",
        executor="local",
        failure_type="stage_exception",
        message="stage failed intentionally",
        exception_type="builtins.RuntimeError",
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        traceback_path="/tmp/traceback.txt",
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        status=StageStatus.FAILED,
        started_at="2020-01-01T00:00:01Z",
        finished_at="2020-01-01T00:00:02Z",
        executor_name="subprocess",
        outputs={},
        failure=failure,
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        traceback_path="/tmp/traceback.txt",
        exit_code=1,
    )


def test_build_stage_worker_command_uses_current_worker_cli() -> None:
    command = build_stage_worker_command(
        python_executable="/usr/bin/python",
        run_uri="file:///runs/demo",
        stage_name="build",
        attempt=3,
    )

    assert command[:3] == (
        "/usr/bin/python",
        "-c",
        "from loom.cli.main import main; raise SystemExit(main())",
    )
    assert command[3:] == (
        "stage",
        "run",
        "--run-uri",
        "file:///runs/demo",
        "--stage",
        "build",
        "--attempt",
        "3",
        "--format",
        "json",
    )


def test_subprocess_executor_reads_successful_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> SubprocessRunResult:
        calls.append(tuple(command))
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )
        return SubprocessRunResult(returncode=0, stdout='{"ok": true}\n')

    result = SubprocessExecutor(
        run_store=store,
        python_executable="/usr/bin/python",
        process_runner=runner,
    ).execute(request)

    assert result.status == StageStatus.SUCCEEDED
    assert result.outputs == {"data": _artifact()}
    assert result.executor_name == "subprocess"
    assert result.executor_metadata["returncode"] == 0
    assert calls[0][0] == "/usr/bin/python"


def test_subprocess_executor_missing_result_is_failure(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = SubprocessExecutor(
        run_store=store,
        process_runner=lambda _command: SubprocessRunResult(returncode=1),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.message == "subprocess worker result is missing"
    assert result.failure.exit_code == 1


def test_subprocess_executor_process_failure_overrides_structured_success(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(_command: Sequence[str]) -> SubprocessRunResult:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )
        return SubprocessRunResult(returncode=2, stderr="worker wrapper failed")

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.message == "subprocess worker reported success but process failed"
    assert result.failure.exit_code == 2
    assert result.outputs == {}


def test_subprocess_executor_preserves_signal_metadata(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = SubprocessExecutor(
        run_store=store,
        process_runner=lambda _command: SubprocessRunResult(returncode=-15),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.exit_code is None
    assert result.failure.signal == 15
    assert result.executor_metadata["signal"] == 15


def test_subprocess_executor_wraps_failed_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(_command: Sequence[str]) -> SubprocessRunResult:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_failure(run_uri).to_dict(),
            attempt=1,
        )
        return SubprocessRunResult(returncode=1)

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.executor == "subprocess"
    assert failure.failure_type == "stage_exception"
    assert failure.message == "stage failed intentionally"
    assert failure.exit_code == 1
    assert failure.details["worker_status"] == "FAILED"
