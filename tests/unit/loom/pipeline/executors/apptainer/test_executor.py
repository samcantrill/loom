"""Unit tests for the Apptainer executor."""

from __future__ import annotations

from collections.abc import Callable, Sequence
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
from loom.pipeline.executors.apptainer import (
    ApptainerCommandResult,
    ApptainerExecCommand,
    ApptainerExecutor,
    SingularityExecutor,
)
from loom.pipeline.planning import (
    FingerprintContext,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.serialization import PlainData
from tests.support.pipeline_execution_stages import JsonProducerStage


pytestmark = pytest.mark.unit


class RecordingApptainerRunner:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        callback: Callable[[ApptainerExecCommand], None] | None = None,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.callback = callback
        self.calls: list[ApptainerExecCommand] = []

    def require(self, command: str) -> None:
        assert command
        return None

    def run(
        self,
        command: ApptainerExecCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        self.calls.append(command)
        if self.callback is not None:
            self.callback(command)
        return ApptainerCommandResult(
            command=command.argv[0],
            argv=command.argv,
            redacted_argv=cast(Sequence[str], command.redacted_argv),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            timeout_seconds=timeout_seconds,
        )

    def version(self, *_args: object, **_kwargs: object) -> ApptainerCommandResult:
        return ApptainerCommandResult(
            command="apptainer",
            argv=("apptainer", "--version"),
            redacted_argv=("apptainer", "--version"),
            returncode=0,
        )


class RaisingApptainerRunner(RecordingApptainerRunner):
    def run(
        self,
        command: ApptainerExecCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        self.calls.append(command)
        raise RuntimeError("TOKEN=secret")


def _request(
    tmp_path: Path,
    *,
    executor_name: str = "apptainer",
    adapter_options: dict[str, PlainData] | None = None,
    resources: ResourceRequest | None = None,
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
        stage,
        bound_inputs={},
        fingerprint_context=FingerprintContext(),
    )
    resolved_runtime = ResolvedStageRuntimeOptions(
        stage_id="build",
        executor=executor_name,
        resources=resources or ResourceRequest(),
        adapter_options=(
            adapter_options
            if adapter_options is not None
            else _adapter_options(store, run_uri)
        ),
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
        resolved_runtime=resolved_runtime,
    )
    return store, run_uri, request


def _adapter_options(store: LocalRunStore, run_uri: str) -> dict[str, PlainData]:
    return {
        "container": {
            "image": {"reference": "analysis.sif"},
            "workdir": str(store.local_run_dir(run_uri)),
            "mounts": [],
            "environment": {
                "variables": {"MODE": "test", "TOKEN": "secret"},
                "required_host_variables": ["HOME"],
            },
        },
        "apptainer": {"cleanenv": True, "nv": True},
    }


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build/data",
        uri="file:///tmp/build-data.json",
        artifact_type="json",
        codec_key="json.v1",
        producer_stage="build",
    )


def _worker_success(
    run_uri: str, *, executor_name: str = "apptainer"
) -> StageWorkerResult:
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        status=StageStatus.SUCCEEDED,
        started_at="2020-01-01T00:00:01Z",
        finished_at="2020-01-01T00:00:02Z",
        executor_name=executor_name,
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
        executor_name="apptainer",
        outputs={},
        failure=failure,
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        traceback_path="/tmp/traceback.txt",
        exit_code=1,
    )


def test_apptainer_executor_reads_successful_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_result(command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )
        assert command.argv[:4] == ("apptainer", "exec", "--cleanenv", "--nv")

    runner = RecordingApptainerRunner(stdout='{"ok": true}\n', callback=write_result)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=runner,
        python_executable="/usr/bin/python",
    ).execute(request)

    assert result.status == StageStatus.SUCCEEDED
    assert result.outputs == {"data": _artifact()}
    assert result.executor_name == "apptainer"
    assert result.executor_metadata["returncode"] == 0
    assert result.executor_metadata["stdout"] == '{"ok": true}\n'
    worker_start = runner.calls[0].argv.index("analysis.sif") + 1
    assert runner.calls[0].argv[worker_start : worker_start + 7] == (
        "/usr/bin/python",
        "-c",
        "from loom.cli.main import main; raise SystemExit(main())",
        "stage",
        "run",
        "--run-uri",
        run_uri,
    )


def test_apptainer_executor_adds_path_binds_and_redacts_metadata(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_result(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )

    runner = RecordingApptainerRunner(callback=write_result)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=runner,
    ).execute(request)

    argv = runner.calls[0].argv
    bind_args = [argv[index + 1] for index, item in enumerate(argv) if item == "--bind"]
    assert any(str(store.local_run_dir(run_uri)) in item for item in bind_args)
    assert any(str(store.local_artifact_root(run_uri)) in item for item in bind_args)
    assert "--env" in argv
    assert "TOKEN=secret" in argv
    assert "secret" not in repr(result.executor_metadata)
    assert "TOKEN=[redacted]" in repr(runner.calls[0].redacted_argv)
    path_kinds = {
        cast(dict[str, object], item)["kind"]
        for item in cast(list[object], result.executor_metadata["path_parity"])
    }
    assert "mount" in path_kinds


def test_singularity_executor_defaults_command_to_singularity(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(
        tmp_path,
        executor_name="singularity",
        adapter_options={
            "container": {
                "image": {"reference": "analysis.sif"},
                "workdir": str(tmp_path / "runs" / "run1"),
            },
            "apptainer": {"cleanenv": False},
        },
    )

    def write_result(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri, executor_name="singularity").to_dict(),
            attempt=1,
        )

    runner = RecordingApptainerRunner(callback=write_result)

    result = SingularityExecutor(
        run_store=store,
        apptainer_command_runner=runner,
    ).execute(request)

    assert result.status == StageStatus.SUCCEEDED
    assert result.executor_name == "singularity"
    assert runner.calls[0].argv[:2] == ("singularity", "exec")
    assert "--cleanenv" not in runner.calls[0].argv
    assert result.executor_metadata["selected_command"] == "singularity"


def test_apptainer_executor_projects_resource_intent_to_metadata(
    tmp_path: Path,
) -> None:
    resources = ResourceRequest(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
            "gpu": ResourceEntry(kind="gpu", amount=1),
        }
    )
    store, run_uri, request = _request(tmp_path, resources=resources)

    def write_result(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(callback=write_result),
    ).execute(request)

    container = cast(dict[str, object], result.executor_metadata["container"])
    resource_meta = cast(dict[str, object], container["resources"])
    entries = cast(dict[str, object], resource_meta["entries"])
    assert set(entries) == {"cpu", "gpu", "memory"}


def test_apptainer_executor_missing_container_options_is_failure(
    tmp_path: Path,
) -> None:
    store, _run_uri, request = _request(tmp_path, adapter_options={})

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == (
        "apptainer worker setup failed: apptainer container adapter options are missing"
    )
    assert failure.details["setup_error"] == (
        "apptainer container adapter options are missing"
    )


def test_apptainer_executor_requires_writable_run_mount(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    run_path = str(store.local_run_dir(run_uri))
    adapter_options: dict[str, PlainData] = {
        "container": {
            "image": {"reference": "analysis.sif"},
            "mounts": [{"source": run_path, "target": run_path, "mode": "ro"}],
        }
    }
    store, _run_uri, request = _request(tmp_path, adapter_options=adapter_options)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == (
        "apptainer worker setup failed: "
        "apptainer required path-parity mount must be read-write"
    )
    assert failure.details["mode"] == "ro"


def test_apptainer_executor_missing_result_is_failure(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(returncode=1),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == "apptainer worker result is missing"
    assert failure.exit_code == 1


def test_apptainer_executor_invalid_worker_result_is_failure(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_invalid(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            {"schema_version": STAGE_WORKER_RESULT_SCHEMA_VERSION},
            attempt=1,
        )

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(callback=write_invalid),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message.startswith("apptainer worker result is invalid")
    assert failure.details["result"] == "invalid"
    assert failure.exit_code == 0


@pytest.mark.parametrize(
    ("field", "value", "expected_message", "detail_key"),
    (
        (
            "run_uri",
            "file:///tmp/other-run",
            "apptainer worker result run_uri does not match request",
            "result_run_uri",
        ),
        (
            "stage_name",
            "other",
            "apptainer worker result stage does not match request",
            "result_stage",
        ),
        (
            "attempt",
            2,
            "apptainer worker result attempt does not match request",
            "result_attempt",
        ),
    ),
)
def test_apptainer_executor_rejects_mismatched_worker_result_identity(
    tmp_path: Path,
    field: str,
    value: object,
    expected_message: str,
    detail_key: str,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_mismatch(_command: ApptainerExecCommand) -> None:
        worker_result = _worker_success(run_uri).to_dict()
        worker_result[field] = cast(PlainData, value)
        store.write_stage_worker_result(run_uri, "build", worker_result, attempt=1)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(callback=write_mismatch),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == expected_message
    assert failure.details[detail_key] == value


def test_apptainer_executor_process_failure_overrides_structured_success(
    tmp_path: Path,
) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_result(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_success(run_uri).to_dict(),
            attempt=1,
        )

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(
            returncode=2,
            stderr="apptainer wrapper failed",
            callback=write_result,
        ),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == "apptainer worker reported success but process failed"
    assert failure.exit_code == 2
    assert result.outputs == {}


def test_apptainer_executor_launch_error_is_structured_and_redacted(
    tmp_path: Path,
) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RaisingApptainerRunner(),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.message == "apptainer worker launch failed: builtins.RuntimeError"
    assert failure.details["launch_error"] == "builtins.RuntimeError"
    assert "secret" not in repr(failure.to_dict())


def test_apptainer_executor_preserves_signal_metadata(tmp_path: Path) -> None:
    store, _run_uri, request = _request(tmp_path)

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(returncode=-15),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.exit_code is None
    assert failure.signal == 15
    assert result.executor_metadata["signal"] == 15


def test_apptainer_executor_wraps_failed_worker_result(tmp_path: Path) -> None:
    store, run_uri, request = _request(tmp_path)

    def write_failure(_command: ApptainerExecCommand) -> None:
        store.write_stage_worker_result(
            run_uri,
            "build",
            _worker_failure(run_uri).to_dict(),
            attempt=1,
        )

    result = ApptainerExecutor(
        run_store=store,
        apptainer_command_runner=RecordingApptainerRunner(
            returncode=1,
            callback=write_failure,
        ),
    ).execute(request)

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.executor == "apptainer"
    assert failure.failure_type == "stage_exception"
    assert failure.message == "stage failed intentionally"
    assert failure.exit_code == 1
    assert failure.details["worker_status"] == "FAILED"
