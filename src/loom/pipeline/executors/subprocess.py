"""Subprocess-backed stage executor."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionRequest,
    StageExecutionResult,
    StageWorkerResult,
    redact_executor_metadata,
)
from loom.pipeline.reliability import TimeoutOutcome, TimeoutSupportLevel
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LegacyRunStore as RunStore, StageWorkerResultStore
from loom.pipeline.stores.config import AuthorityConfig, authority_config_to_cli_args
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from ._reliability import (
    metadata_with_timeout,
    timeout_metadata,
    timeout_policy_from_request,
)
from .errors import ExecutorError

WORKER_MAIN_SNIPPET = "from loom.cli.main import main; raise SystemExit(main())"
MAX_CAPTURE_SNIPPET_CHARS = 1000

Clock = Callable[[], str]


class ProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> "SubprocessRunResult": ...


@dataclass(frozen=True, slots=True)
class SubprocessRunResult:
    """Captured result for one worker subprocess invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise ExecutorError("SubprocessRunResult.returncode must be an integer")
        if not isinstance(self.stdout, str):
            raise ExecutorError("SubprocessRunResult.stdout must be a string")
        if not isinstance(self.stderr, str):
            raise ExecutorError("SubprocessRunResult.stderr must be a string")


class SubprocessExecutor:
    """Execute one prepared stage attempt in a worker subprocess."""

    name = "subprocess"
    requires_prepared_worker_request = True

    def __init__(
        self,
        *,
        worker_results: StageWorkerResultStore | None = None,
        run_store: RunStore | None = None,
        python_executable: str | None = None,
        process_runner: ProcessRunner | None = None,
        clock: Clock = utc_timestamp,
    ) -> None:
        if worker_results is None:
            if not isinstance(run_store, RunStore):
                raise ExecutorError("SubprocessExecutor requires worker_results")
            worker_results = run_store
        elif not isinstance(worker_results, StageWorkerResultStore):
            raise ExecutorError(
                "SubprocessExecutor.worker_results must satisfy StageWorkerResultStore"
            )
        if run_store is not None and not isinstance(run_store, RunStore):
            raise ExecutorError("SubprocessExecutor.run_store must satisfy RunStore")
        if python_executable is not None and (
            not isinstance(python_executable, str) or not python_executable
        ):
            raise ExecutorError(
                "SubprocessExecutor.python_executable must be non-empty when set"
            )
        if process_runner is not None and not callable(process_runner):
            raise ExecutorError("SubprocessExecutor.process_runner must be callable")
        if not callable(clock):
            raise ExecutorError("SubprocessExecutor.clock must be callable")
        self.worker_results = worker_results
        self.python_executable = python_executable or sys.executable
        self.process_runner = process_runner or _run_subprocess
        self.clock = clock

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        if not isinstance(request, StageExecutionRequest):
            raise ExecutorError(
                "SubprocessExecutor.execute requires StageExecutionRequest"
            )

        command = build_stage_worker_command(
            python_executable=self.python_executable,
            run_uri=request.run_uri,
            stage_name=request.stage.name,
            attempt=request.attempt,
            authority_cli_args=request.worker_authority_cli_args,
        )
        policy = timeout_policy_from_request(request)
        timeout_seconds = None if policy is None else policy.duration_seconds
        timeout = (
            None
            if policy is None
            else timeout_metadata(
                policy=policy,
                support_level=TimeoutSupportLevel.ENFORCED,
                outcome=TimeoutOutcome.ENFORCED,
                timed_out=False,
            )
        )
        started_at = self.clock()
        try:
            process = self.process_runner(command, timeout_seconds=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            finished_at = self.clock()
            if policy is None:
                timeout = None
            else:
                timeout = timeout_metadata(
                    policy=policy,
                    support_level=TimeoutSupportLevel.ENFORCED,
                    outcome=TimeoutOutcome.TIMED_OUT,
                    timed_out=True,
                    message="subprocess worker exceeded reliability timeout",
                    details=_timeout_expired_details(exc),
                )
            metadata = metadata_with_timeout(
                _process_metadata(
                    command=command,
                    process=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    launch_error="subprocess.TimeoutExpired",
                ),
                timeout,
            )
            failure = _failure(
                request=request,
                failed_at=finished_at,
                message="subprocess worker exceeded reliability timeout",
                exit_code=None,
                signal=None,
                metadata=metadata,
                details={
                    "timeout": dict(timeout) if timeout is not None else {},
                    "timeout_expired": True,
                },
            )
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 - process-launch errors become structured failures.
            finished_at = self.clock()
            metadata = metadata_with_timeout(
                _process_metadata(
                    command=command,
                    process=None,
                    started_at=started_at,
                    finished_at=finished_at,
                    launch_error=f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
                ),
                timeout,
            )
            failure = _failure(
                request=request,
                failed_at=finished_at,
                message=f"subprocess worker launch failed: {exc}",
                exit_code=None,
                signal=None,
                metadata=metadata,
                details={"launch_error": str(exc) or type(exc).__name__},
            )
            return _failed_result(
                request=request,
                started_at=started_at,
                finished_at=finished_at,
                failure=failure,
                metadata=metadata,
            )
        finished_at = self.clock()
        metadata = metadata_with_timeout(
            _process_metadata(
                command=command,
                process=process,
                started_at=started_at,
                finished_at=finished_at,
            ),
            timeout,
        )
        process_exit_code, process_signal = _process_failure_fields(process.returncode)
        worker_result = _read_worker_result(
            worker_results=self.worker_results,
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


def build_stage_worker_command(
    *,
    python_executable: str,
    run_uri: str,
    stage_name: str,
    attempt: int,
    authority_config: AuthorityConfig | None = None,
    authority_cli_args: Sequence[str] = (),
) -> tuple[str, ...]:
    """Return the command used to invoke the durable stage worker."""

    if not isinstance(python_executable, str) or not python_executable:
        raise ExecutorError("python_executable must be a non-empty string")
    if not isinstance(run_uri, str) or not run_uri:
        raise ExecutorError("run_uri must be a non-empty string")
    if not isinstance(stage_name, str) or not stage_name:
        raise ExecutorError("stage_name must be a non-empty string")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise ExecutorError("attempt must be a positive integer")
    command = [
        python_executable,
        "-c",
        WORKER_MAIN_SNIPPET,
        "stage",
        "run",
        "--run-uri",
        run_uri,
        "--stage",
        stage_name,
        "--attempt",
        str(attempt),
    ]
    if authority_cli_args:
        if authority_config is not None:
            raise ExecutorError(
                "authority_config and authority_cli_args cannot both be supplied"
            )
        if not all(isinstance(argument, str) and argument for argument in authority_cli_args):
            raise ExecutorError("authority_cli_args must contain non-empty strings")
        command.extend(authority_cli_args)
    elif authority_config is not None:
        command.extend(authority_config_to_cli_args(authority_config))
    command.extend(("--format", "json"))
    return tuple(command)


def _run_subprocess(
    command: Sequence[str],
    *,
    timeout_seconds: float | None = None,
) -> SubprocessRunResult:
    completed = subprocess.run(
        tuple(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return SubprocessRunResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _read_worker_result(
    *,
    worker_results: StageWorkerResultStore,
    request: StageExecutionRequest,
    process_metadata: dict[str, PlainData],
    process_exit_code: int | None,
    process_signal: int | None,
    finished_at: str,
) -> StageWorkerResult | ExecutionFailure:
    try:
        raw_result = worker_results.read_stage_worker_result(
            request.run_uri,
            request.stage.name,
            attempt=request.attempt,
        )
    except Exception as exc:
        return _failure(
            request=request,
            failed_at=finished_at,
            message=f"could not read subprocess worker result: {exc}",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"read_error": str(exc) or type(exc).__name__},
        )
    if raw_result is None:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker result is missing",
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
            message=f"subprocess worker result is invalid: {exc}",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result": "invalid", "error": str(exc) or type(exc).__name__},
        )
    if worker_result.run_uri != request.run_uri:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker result run_uri does not match request",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result_run_uri": worker_result.run_uri},
        )
    if worker_result.stage_name != request.stage.name:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker result stage does not match request",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"result_stage": worker_result.stage_name},
        )
    if worker_result.attempt != request.attempt:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker result attempt does not match request",
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
            message="subprocess worker reported success but process failed",
            exit_code=process_exit_code,
            signal=process_signal,
            metadata=process_metadata,
            details={"worker_status": worker_result.status.value},
        )
    if worker_result.status == StageStatus.FAILED and process_returncode == 0:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker reported failure but process exited successfully",
            exit_code=None,
            signal=None,
            metadata=process_metadata,
            details={"worker_status": worker_result.status.value},
        )
    if worker_result.status == StageStatus.CANCELLED and process_returncode != 0:
        return _failure(
            request=request,
            failed_at=finished_at,
            message="subprocess worker reported cancellation but process failed",
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
        else "subprocess worker failed without failure metadata"
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
        executor="subprocess",
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
        executor="subprocess",
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
        executor_name="subprocess",
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


def _process_metadata(
    *,
    command: Sequence[str],
    process: SubprocessRunResult | None,
    started_at: str,
    finished_at: str,
    launch_error: str | None = None,
) -> dict[str, PlainData]:
    metadata: dict[str, PlainData] = {
        "executor": "subprocess",
        "command": list(command),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if process is not None:
        exit_code, signal = _process_failure_fields(process.returncode)
        metadata.update(
            {
                "returncode": process.returncode,
                "exit_code": exit_code,
                "signal": signal,
                "stdout": _capture_summary(process.stdout),
                "stderr": _capture_summary(process.stderr),
            }
        )
    if launch_error is not None:
        metadata["launch_error"] = launch_error
    return redact_executor_metadata(metadata)


def _capture_summary(text: str) -> dict[str, PlainData]:
    return {
        "chars": len(text),
        "truncated": len(text) > MAX_CAPTURE_SNIPPET_CHARS,
        "snippet": text[:MAX_CAPTURE_SNIPPET_CHARS],
    }


def _timeout_expired_details(exc: subprocess.TimeoutExpired) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {"timeout_seconds": float(exc.timeout)}
    if exc.stdout is not None:
        details["stdout"] = _capture_summary(_decode_timeout_output(exc.stdout))
    if exc.stderr is not None:
        details["stderr"] = _capture_summary(_decode_timeout_output(exc.stderr))
    return details


def _decode_timeout_output(value: str | bytes | object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = [
    "SubprocessExecutor",
    "SubprocessRunResult",
    "build_stage_worker_command",
]
