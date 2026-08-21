"""Unit tests for the subprocess executor."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

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
from loom.pipeline.planning import (
    FingerprintContext,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.reliability import ReliabilityPolicy, TimeoutPolicy
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
)
from loom.serialization import PlainData
from tests.support.pipeline_execution_stages import JsonProducerStage


def _request(
    tmp_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> tuple[LocalRunStore, str, StageExecutionRequest]:
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
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="subprocess",
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


def test_build_stage_worker_command_propagates_authority_config() -> None:
    command = build_stage_worker_command(
        python_executable="/usr/bin/python",
        run_uri="file:///runs/demo",
        stage_name="build",
        attempt=3,
        authority_config=AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            endpoint="http://authority.test",
            workspace_id="workspace-a",
            reference_id="worker-authority",
        ),
    )

    assert command[command.index("--authority-backend") + 1] == "managed_service"
    assert command[command.index("--authority-profile") + 1] == "managed_service"
    assert command[command.index("--authority-endpoint") + 1] == "http://authority.test"
    assert command[command.index("--authority-workspace") + 1] == "workspace-a"
    assert command[command.index("--authority-reference") + 1] == "worker-authority"
    assert command[-2:] == ("--format", "json")


def test_build_stage_worker_command_propagates_only_explicit_plugin_selectors() -> None:
    command = build_stage_worker_command(
        python_executable="/usr/bin/python",
        run_uri="file:///runs/demo",
        stage_name="build",
        attempt=3,
        plugin_selectors=(
            "loom.codecs:stage28.tagged-json.v1",
            "loom.resource_validators:stage28.device",
        ),
    )

    assert command[-6:] == (
        "--plugin",
        "loom.codecs:stage28.tagged-json.v1",
        "--plugin",
        "loom.resource_validators:stage28.device",
        "--format",
        "json",
    )


def test_subprocess_executor_reads_successful_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
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


def test_subprocess_executor_uses_result_facet_and_request_authority_args(
    tmp_path: Path,
) -> None:
    _store, run_uri, request = _request(tmp_path)
    request = replace(
        request,
        worker_authority_cli_args=("--authority-reference", "worker-authority"),
    )
    calls: list[tuple[str, ...]] = []

    class ResultOnlyStore:
        def read_stage_worker_result(
            self, run_uri: str, stage_name: str, *, attempt: int
        ) -> dict[str, PlainData] | None:
            assert (run_uri, stage_name, attempt) == (request.run_uri, "build", 1)
            return _worker_success(run_uri).to_dict()

    result = SubprocessExecutor(
        worker_results=ResultOnlyStore(),
        process_runner=lambda command, *, timeout_seconds=None: (
            calls.append(tuple(command)) or SubprocessRunResult(returncode=0)
        ),
    ).execute(request)

    assert result.status is StageStatus.SUCCEEDED
    assert calls[0][calls[0].index("--authority-reference") + 1] == "worker-authority"


def test_subprocess_executor_passes_reliability_timeout_to_process_runner(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(tmp_path, timeout_seconds=2.5)
    observed_timeout: list[float | None] = []

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command
        observed_timeout.append(timeout_seconds)
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )
        return SubprocessRunResult(returncode=0)

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    timeout = cast(dict[str, object], result.executor_metadata["reliability_timeout"])
    assert observed_timeout == [2.5]
    assert timeout["timeout_domain"] == "reliability"
    assert timeout["support_level"] == "enforced"
    assert timeout["outcome"] == "enforced"
    assert timeout["duration_seconds"] == 2.5


def test_subprocess_executor_timeout_expired_is_structured_failure(
    tmp_path: Path,
) -> None:
    store, _run_uri, request = _request(tmp_path, timeout_seconds=0.25)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        raise subprocess.TimeoutExpired(
            cmd=tuple(command),
            timeout=cast(float, timeout_seconds),
            output="partial stdout",
            stderr="partial stderr",
        )

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    timeout = cast(dict[str, object], result.executor_metadata["reliability_timeout"])
    assert failure.message == "subprocess worker exceeded reliability timeout"
    assert failure.details["timeout_expired"] is True
    assert timeout["timed_out"] is True
    assert timeout["outcome"] == "timed_out"
    assert timeout["support_level"] == "enforced"
    assert timeout["duration_seconds"] == 0.25


def test_subprocess_executor_missing_result_is_failure(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = SubprocessExecutor(
        run_store=store,
        process_runner=lambda command, *, timeout_seconds=None: SubprocessRunResult(
            returncode=1
        ),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.message == "subprocess worker result is missing"
    assert result.failure.exit_code == 1


def test_subprocess_executor_invalid_worker_result_is_failure(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
        store.write_stage_worker_result(
            run_uri,
            "build",
            {"schema_version": STAGE_WORKER_RESULT_SCHEMA_VERSION},
            attempt=1,
        )
        return SubprocessRunResult(returncode=0)

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message.startswith("subprocess worker result is invalid")
    assert failure.details["result"] == "invalid"
    assert failure.exit_code == 0


@pytest.mark.parametrize(
    ("field", "value", "expected_message", "detail_key"),
    (
        (
            "run_uri",
            "file:///tmp/other-run",
            "subprocess worker result run_uri does not match request",
            "result_run_uri",
        ),
        (
            "stage_name",
            "other",
            "subprocess worker result stage does not match request",
            "result_stage",
        ),
        (
            "attempt",
            2,
            "subprocess worker result attempt does not match request",
            "result_attempt",
        ),
    ),
)
def test_subprocess_executor_rejects_mismatched_worker_result_identity(
    tmp_path: Path,
    field: str,
    value: object,
    expected_message: str,
    detail_key: str,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
        worker_result = _worker_success(run_uri).to_dict()
        worker_result[field] = cast(PlainData, value)
        store.write_stage_worker_result(run_uri, "build", worker_result, attempt=1)
        return SubprocessRunResult(returncode=0)

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == expected_message
    assert failure.details[detail_key] == value


def test_subprocess_executor_process_failure_overrides_structured_success(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
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
    assert (
        result.failure.message
        == "subprocess worker reported success but process failed"
    )
    assert result.failure.exit_code == 2
    assert result.outputs == {}


def test_subprocess_executor_launch_error_is_structured_failure(
    tmp_path: Path,
) -> None:
    store, _run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
        raise OSError("worker command missing")

    result = SubprocessExecutor(run_store=store, process_runner=runner).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == "subprocess worker launch failed: worker command missing"
    assert failure.details["launch_error"] == "worker command missing"
    assert "OSError" in cast(str, failure.executor_metadata["launch_error"])


def test_subprocess_executor_preserves_signal_metadata(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = SubprocessExecutor(
        run_store=store,
        process_runner=lambda command, *, timeout_seconds=None: SubprocessRunResult(
            returncode=-15
        ),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    assert result.failure is not None
    assert result.failure.exit_code is None
    assert result.failure.signal == 15
    assert result.executor_metadata["signal"] == 15


def test_subprocess_executor_redacts_command_metadata(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )
        return SubprocessRunResult(returncode=0)

    result = SubprocessExecutor(
        run_store=store,
        python_executable="python --token=secret",
        process_runner=runner,
    ).execute(request)

    command = cast(list[object], result.executor_metadata["command"])
    assert command[0] == "[redacted]"
    assert "--token=secret" not in str(result.executor_metadata)


def test_subprocess_executor_wraps_failed_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def runner(
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SubprocessRunResult:
        del command, timeout_seconds
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
