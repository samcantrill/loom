"""Docker-backed prepared stage executor."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionRequest,
    StageExecutionResult,
    StageWorkerResult,
    redact_executor_metadata,
)
from loom.pipeline.executors.containers import (
    ContainerMount,
    ContainerMountMode,
    ContainerOptions,
    ContainerPathParitySummary,
    ContainerResourceIntent,
    parse_container_options,
)
from loom.pipeline.executors.errors import ExecutorError
from loom.pipeline.executors.subprocess import build_stage_worker_command
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.runtime.capabilities import DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    AuthorityConfig,
    LegacyRunStore as RunStore,
    LocalRunStorePaths,
)
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from .commands import (
    DockerCommandResult,
    DockerCommandRunner,
    DockerOptions,
    DockerRunCommand,
    SubprocessDockerCommandRunner,
    build_docker_run_command,
)


Clock = Callable[[], str]


@dataclass(frozen=True, slots=True)
class _DockerSetupError(Exception):
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class DockerExecutor:
    """Execute one prepared stage attempt with ``docker run``."""

    name = "docker"
    requires_prepared_worker_request = True

    def __init__(
        self,
        *,
        run_store: RunStore,
        docker_command_runner: DockerCommandRunner | None = None,
        python_executable: str = "python",
        clock: Clock = utc_timestamp,
    ) -> None:
        if not isinstance(run_store, RunStore):
            raise ExecutorError("DockerExecutor requires RunStore")
        if not isinstance(python_executable, str) or not python_executable:
            raise ExecutorError("DockerExecutor.python_executable must be non-empty")
        if docker_command_runner is not None:
            for method in ("run", "require", "version", "image_digest"):
                if not callable(getattr(docker_command_runner, method, None)):
                    raise ExecutorError(
                        f"DockerExecutor.docker_command_runner must provide {method}()"
                    )
        if not callable(clock):
            raise ExecutorError("DockerExecutor.clock must be callable")
        self.run_store = run_store
        self.docker_command_runner = (
            docker_command_runner or SubprocessDockerCommandRunner(clock=clock)
        )
        self.python_executable = python_executable
        self.clock = clock

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        if not isinstance(request, StageExecutionRequest):
            raise ExecutorError("DockerExecutor.execute requires StageExecutionRequest")

        started_at = self.clock()
        try:
            prepared = _prepare_docker_attempt(
                request=request,
                run_store=self.run_store,
                python_executable=self.python_executable,
            )
        except Exception as exc:  # noqa: BLE001 - setup errors become structured failures.
            finished_at = self.clock()
            setup_error = _coerce_setup_error(exc)
            metadata = _setup_metadata(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                setup_error=setup_error,
            )
            failure = _failure(
                request=request,
                failed_at=finished_at,
                message=f"docker worker setup failed: {setup_error.message}",
                exit_code=None,
                signal=None,
                metadata=metadata,
                details={"setup_error": setup_error.message, **dict(setup_error.details)},
            )
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
                metadata=metadata,
            )

        try:
            process = self.docker_command_runner.run(prepared.command)
        except Exception as exc:  # noqa: BLE001 - command-launch errors become structured failures.
            finished_at = self.clock()
            launch_error = _safe_exception_name(exc)
            metadata = _process_metadata(
                command=prepared.command,
                worker_command=prepared.worker_command,
                container=prepared.container,
                path_parity=prepared.path_parity,
                process=None,
                started_at=started_at,
                finished_at=finished_at,
                launch_error=launch_error,
            )
            failure = _failure(
                request=request,
                failed_at=finished_at,
                message=f"docker worker launch failed: {launch_error}",
                exit_code=None,
                signal=None,
                metadata=metadata,
                details={"launch_error": launch_error},
            )
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
                metadata=metadata,
            )

        finished_at = self.clock()
        if not isinstance(process, DockerCommandResult):
            metadata = _process_metadata(
                command=prepared.command,
                worker_command=prepared.worker_command,
                container=prepared.container,
                path_parity=prepared.path_parity,
                process=None,
                started_at=started_at,
                finished_at=finished_at,
                launch_error="invalid DockerCommandRunner result",
            )
            failure = _failure(
                request=request,
                failed_at=finished_at,
                message="docker command runner returned invalid result",
                exit_code=None,
                signal=None,
                metadata=metadata,
                details={"result": "invalid"},
            )
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
                metadata=metadata,
            )

        metadata = _process_metadata(
            command=prepared.command,
            worker_command=prepared.worker_command,
            container=prepared.container,
            path_parity=prepared.path_parity,
            process=process,
            started_at=started_at,
            finished_at=finished_at,
        )
        process_exit_code, process_signal = _process_failure_fields(process.returncode)
        worker_result = _read_worker_result(
            run_store=self.run_store,
            request=request,
            process_metadata=metadata,
            process_exit_code=process_exit_code,
            process_signal=process_signal,
            finished_at=finished_at,
        )
        if isinstance(worker_result, ExecutionFailure):
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=worker_result,
                metadata=metadata,
            )

        conflict = _process_conflict_failure(
            request=request,
            worker_result=worker_result,
            process_returncode=process.returncode,
            process_exit_code=process_exit_code,
            process_signal=process_signal,
            process_metadata=metadata,
            finished_at=finished_at,
        )
        if conflict is not None:
            return _failed_result(
                request=request,
                started_at=worker_result.started_at,
                finished_at=finished_at,
                failure=conflict,
                metadata=metadata,
            )

        if worker_result.status == StageStatus.FAILED:
            failure = _worker_failure(
                request=request,
                worker_result=worker_result,
                process_metadata=metadata,
                process_exit_code=process_exit_code,
                process_signal=process_signal,
            )
            return _failed_result(
                request=request,
                started_at=worker_result.started_at,
                finished_at=worker_result.finished_at,
                failure=failure,
                metadata=metadata,
            )

        if worker_result.status == StageStatus.CANCELLED:
            return StageExecutionResult(
                stage_name=request.stage.name,
                status=StageStatus.CANCELLED,
                outputs={},
                failure=None,
                started_at=worker_result.started_at,
                finished_at=worker_result.finished_at,
                executor_name=self.name,
                attempt=request.attempt,
                stdout_path=worker_result.stdout_path,
                stderr_path=worker_result.stderr_path,
                traceback_path=worker_result.traceback_path,
                executor_metadata={
                    **metadata,
                    **dict(worker_result.executor_metadata),
                },
            )

        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs=worker_result.outputs,
            failure=None,
            started_at=worker_result.started_at,
            finished_at=worker_result.finished_at,
            executor_name=self.name,
            attempt=request.attempt,
            stdout_path=worker_result.stdout_path,
            stderr_path=worker_result.stderr_path,
            traceback_path=worker_result.traceback_path,
            executor_metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class _PreparedDockerAttempt:
    container: ContainerOptions
    path_parity: tuple[ContainerPathParitySummary, ...]
    worker_command: tuple[str, ...]
    command: DockerRunCommand


def _prepare_docker_attempt(
    *,
    request: StageExecutionRequest,
    run_store: RunStore,
    python_executable: str,
) -> _PreparedDockerAttempt:
    runtime = cast(ResolvedStageRuntimeOptions, request.resolved_runtime)
    adapter_options = runtime.adapter_options
    if "container" not in adapter_options:
        raise _DockerSetupError("docker container adapter options are missing")
    container = parse_container_options(adapter_options["container"])
    container = _with_runtime_resources(container=container, runtime=runtime)
    container = _with_required_path_mounts(
        container=container,
        run_store=run_store,
        run_uri=request.run_uri,
    )
    path_parity = container.path_parity_summaries()
    invalid = [summary.to_dict() for summary in path_parity if not summary.ok]
    if invalid:
        raise _DockerSetupError(
            "docker path parity validation failed",
            details={"path_parity": cast(PlainData, invalid)},
        )
    docker_options = DockerOptions.from_dict(adapter_options.get("docker"))
    worker_command = build_stage_worker_command(
        python_executable=python_executable,
        run_uri=request.run_uri,
        stage_name=request.stage.name,
        attempt=request.attempt,
        authority_config=_authority_config(run_store),
    )
    command = build_docker_run_command(
        container_options=container,
        docker_options=docker_options,
        worker_command=worker_command,
    )
    return _PreparedDockerAttempt(
        container=container,
        path_parity=path_parity,
        worker_command=worker_command,
        command=command,
    )


def _with_runtime_resources(
    *,
    container: ContainerOptions,
    runtime: ResolvedStageRuntimeOptions,
) -> ContainerOptions:
    resources = cast(ResourceRequest, runtime.resources)
    container_resources = container.resources
    if resources.entries:
        descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("docker")
        capabilities = {
            kind: descriptor.capability_for(kind) for kind in resources.entries
        }
        container_resources = ContainerResourceIntent.from_runtime(
            resources,
            capabilities,
        )
    return ContainerOptions(
        image=container.image,
        workdir=container.workdir,
        mounts=cast(tuple[ContainerMount, ...], container.mounts),
        environment=container.environment,
        resources=container_resources,
    )


def _with_required_path_mounts(
    *,
    container: ContainerOptions,
    run_store: RunStore,
    run_uri: str,
) -> ContainerOptions:
    if not isinstance(run_store, LocalRunStorePaths):
        raise _DockerSetupError(
            "docker executor requires local run-store path helpers",
            details={"run_store": type(run_store).__name__},
        )

    mounts = list(cast(tuple[ContainerMount, ...], container.mounts))
    for path in (
        _local_store_path(run_store.local_run_dir(run_uri), kind="run_dir"),
        _local_store_path(
            run_store.local_artifact_root(run_uri),
            kind="artifact_root",
        ),
    ):
        if path not in {mount.target for mount in mounts}:
            mounts.append(
                ContainerMount(
                    source=path,
                    target=path,
                    mode=ContainerMountMode.READ_WRITE,
                )
            )
    return ContainerOptions(
        image=container.image,
        workdir=container.workdir,
        mounts=tuple(mounts),
        environment=container.environment,
        resources=container.resources,
    )


def _local_store_path(path: Path, *, kind: str) -> str:
    normalized = Path(path)
    if not normalized.is_absolute():
        raise _DockerSetupError(
            f"docker {kind} path is not absolute",
            details={kind: str(path)},
        )
    return str(normalized)


def _authority_config(run_store: RunStore) -> AuthorityConfig | None:
    raw_config = getattr(run_store, "authority_config", None)
    if isinstance(raw_config, AuthorityConfig):
        return raw_config
    if callable(raw_config):
        value = raw_config()
        if isinstance(value, AuthorityConfig):
            return value
    return None


def _read_worker_result(
    *,
    run_store: RunStore,
    request: StageExecutionRequest,
    process_metadata: dict[str, PlainData],
    process_exit_code: int | None,
    process_signal: int | None,
    finished_at: str,
) -> StageWorkerResult | ExecutionFailure:
    try:
        raw_result = run_store.read_stage_worker_result(
            request.run_uri,
            request.stage.name,
            attempt=request.attempt,
        )
    except Exception as exc:
        return _failure(
            request=request,
            failed_at=finished_at,
            message=f"could not read docker worker result: {exc}",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"read_error": str(exc) or type(exc).__name__},
        )
    if raw_result is None:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker result is missing",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result": "missing"},
        )
    try:
        worker_result = StageWorkerResult.from_dict(raw_result)
    except Exception as exc:
        return _failure(
            request=request,
            failed_at=finished_at,
            message=f"docker worker result is invalid: {exc}",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result": "invalid", "error": str(exc) or type(exc).__name__},
        )
    if worker_result.run_uri != request.run_uri:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker result run_uri does not match request",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result_run_uri": worker_result.run_uri},
        )
    if worker_result.stage_name != request.stage.name:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker result stage does not match request",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result_stage": worker_result.stage_name},
        )
    if worker_result.attempt != request.attempt:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker result attempt does not match request",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result_attempt": worker_result.attempt},
        )
    return worker_result


def _process_conflict_failure(
    *,
    request: StageExecutionRequest,
    worker_result: StageWorkerResult,
    process_returncode: int,
    process_exit_code: int | None,
    process_signal: int | None,
    process_metadata: dict[str, PlainData],
    finished_at: str,
) -> ExecutionFailure | None:
    if worker_result.status == StageStatus.SUCCEEDED and process_returncode != 0:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker reported success but process failed",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"worker_status": worker_result.status.value},
        )
    if worker_result.status == StageStatus.FAILED and process_returncode == 0:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker reported failure but process exited successfully",
            exit_code=None,
            signal=None,
            metadata=process_metadata,
            details={"worker_status": worker_result.status.value},
        )
    if worker_result.status == StageStatus.CANCELLED and process_returncode != 0:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="docker worker reported cancellation but process failed",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"worker_status": worker_result.status.value},
        )
    return None


def _worker_failure(
    *,
    request: StageExecutionRequest,
    worker_result: StageWorkerResult,
    process_metadata: dict[str, PlainData],
    process_exit_code: int | None,
    process_signal: int | None,
) -> ExecutionFailure:
    worker_failure = cast(ExecutionFailure | None, worker_result.failure)
    details: dict[str, PlainData] = {"worker_status": worker_result.status.value}
    if worker_failure is not None:
        details["worker_failure"] = worker_failure.to_dict()
    message = (
        worker_failure.message
        if worker_failure is not None
        else "docker worker failed without failure metadata"
    )
    failure_type = (
        worker_failure.failure_type
        if worker_failure is not None
        else "executor_infrastructure"
    )
    return ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage.name,
        attempt=request.attempt,
        failed_at=worker_result.finished_at,
        executor="docker",
        failure_type=failure_type,
        message=message,
        exception_type=worker_failure.exception_type if worker_failure is not None else None,
        traceback_path=worker_result.traceback_path,
        stdout_path=worker_result.stdout_path,
        stderr_path=worker_result.stderr_path,
        exit_code=process_exit_code if process_signal is None else None,
        signal=process_signal,
        executor_metadata=process_metadata,
        details=details,
    )


def _failure(
    *,
    request: StageExecutionRequest,
    failed_at: str,
    message: str,
    exit_code: int | None,
    signal: int | None,
    metadata: dict[str, PlainData],
    details: dict[str, PlainData] | None = None,
) -> ExecutionFailure:
    return ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage.name,
        attempt=request.attempt,
        failed_at=failed_at,
        executor="docker",
        failure_type="executor_infrastructure",
        message=message,
        stdout_path=str(request.stdout_path),
        stderr_path=str(request.stderr_path),
        traceback_path=str(request.traceback_path),
        exit_code=exit_code if signal is None else None,
        signal=signal,
        executor_metadata=metadata,
        details=details or {},
    )


def _failed_result(
    *,
    request: StageExecutionRequest,
    started_at: str,
    finished_at: str,
    failure: ExecutionFailure,
    metadata: dict[str, PlainData],
) -> StageExecutionResult:
    return StageExecutionResult(
        stage_name=request.stage.name,
        status=StageStatus.FAILED,
        outputs={},
        failure=failure,
        started_at=started_at,
        finished_at=finished_at,
        executor_name="docker",
        attempt=request.attempt,
        stdout_path=failure.stdout_path,
        stderr_path=failure.stderr_path,
        traceback_path=failure.traceback_path,
        executor_metadata=metadata,
    )


def _process_failure_fields(returncode: int) -> tuple[int | None, int | None]:
    if returncode < 0:
        return None, abs(returncode)
    return returncode, None


def _setup_metadata(
    *,
    request: StageExecutionRequest,
    started_at: str,
    finished_at: str,
    setup_error: _DockerSetupError,
) -> dict[str, PlainData]:
    runtime = cast(ResolvedStageRuntimeOptions, request.resolved_runtime)
    metadata: dict[str, PlainData] = {
        "executor": "docker",
        "started_at": started_at,
        "finished_at": finished_at,
        "adapter_namespaces": cast(list[PlainData], sorted(runtime.adapter_options)),
        "setup_error": setup_error.message,
        "details": cast(PlainData, dict(setup_error.details)),
    }
    return redact_executor_metadata(metadata)


def _process_metadata(
    *,
    command: DockerRunCommand,
    worker_command: Sequence[str],
    container: ContainerOptions,
    path_parity: Sequence[ContainerPathParitySummary],
    process: DockerCommandResult | None,
    started_at: str,
    finished_at: str,
    launch_error: str | None = None,
) -> dict[str, PlainData]:
    metadata: dict[str, PlainData] = {
        "executor": "docker",
        "command": cast(list[PlainData], list(_redacted_argv(command))),
        "worker_command": cast(list[PlainData], list(worker_command)),
        "container": container.to_redacted_metadata(),
        "path_parity": cast(
            list[PlainData],
            [summary.to_dict() for summary in path_parity],
        ),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if process is not None:
        exit_code, signal = _process_failure_fields(process.returncode)
        metadata.update(
            {
                "command": cast(list[PlainData], list(process.redacted_argv)),
                "returncode": process.returncode,
                "exit_code": exit_code,
                "signal": signal,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "command_started_at": process.started_at,
                "command_finished_at": process.finished_at,
                "timed_out": process.timed_out,
                "timeout_seconds": process.timeout_seconds,
                "error": process.error,
            }
        )
    if launch_error is not None:
        metadata["launch_error"] = launch_error
    return redact_executor_metadata(metadata)


def _redacted_argv(command: DockerRunCommand) -> Sequence[str]:
    return cast(Sequence[str], command.redacted_argv)


def _coerce_setup_error(exc: BaseException) -> _DockerSetupError:
    if isinstance(exc, _DockerSetupError):
        return exc
    return _DockerSetupError(
        str(exc) or type(exc).__name__,
        details={"exception_type": _safe_exception_name(exc)},
    )


def _safe_exception_name(exc: BaseException) -> str:
    return f"{type(exc).__module__}.{type(exc).__name__}"


__all__ = ["DockerExecutor"]
