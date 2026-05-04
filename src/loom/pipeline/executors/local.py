"""Local in-process stage executor."""

from __future__ import annotations

import contextlib
import io
import traceback
from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.stage import Stage
from loom.pipeline.status import StageStatus
from loom.timestamps import utc_timestamp
from typing import TYPE_CHECKING, cast

from .errors import LocalExecutorError

if TYPE_CHECKING:
    from loom.pipeline.execution.models import StageExecutionRequest, StageExecutionResult

class LocalExecutor:
    name = "local"

    def __init__(self, *, capture_stdout_stderr: bool = False) -> None:
        if not isinstance(capture_stdout_stderr, bool):
            raise LocalExecutorError("capture_stdout_stderr must be a bool")
        self.capture_stdout_stderr = capture_stdout_stderr

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        from loom.pipeline import execution as _execution
        from loom.pipeline.execution.models import (
            EXECUTION_FAILURE_SCHEMA_VERSION,
            ExecutionFailure,
            StageExecutionRequest,
            StageExecutionResult,
        )

        if not isinstance(request, StageExecutionRequest):
            raise LocalExecutorError(
                "LocalExecutor.execute requires StageExecutionRequest"
            )
        if not isinstance(request.stage_object, Stage):
            raise LocalExecutorError("Stage object does not satisfy the Stage protocol")

        started_at = utc_timestamp()
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            if self.capture_stdout_stderr:
                with (
                    contextlib.redirect_stdout(stdout_buffer),
                    contextlib.redirect_stderr(stderr_buffer),
                ):
                    raw_outputs = request.stage_object.run(
                        request.context, request.inputs
                    )
            else:
                raw_outputs = request.stage_object.run(request.context, request.inputs)
        except Exception as exc:  # noqa: BLE001 - trusted stage failures become structured results.
            finished_at = utc_timestamp()
            traceback_text = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            _execution.logs.write_text_file(request.traceback_path, traceback_text)
            if self.capture_stdout_stderr:
                _execution.logs.write_text_file(
                    request.stdout_path, stdout_buffer.getvalue()
                )
                _execution.logs.write_text_file(
                    request.stderr_path, stderr_buffer.getvalue()
                )
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_id=request.run_id,
                stage_name=request.stage.name,
                attempt=request.attempt,
                failed_at=finished_at,
                executor=self.name,
                failure_type="stage_exception",
                message=str(exc) or type(exc).__name__,
                exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
                traceback_path=str(request.traceback_path),
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
            )
            return StageExecutionResult(
                stage_name=request.stage.name,
                status=StageStatus.FAILED,
                outputs={},
                failure=failure,
                started_at=started_at,
                finished_at=finished_at,
                executor_name=self.name,
                attempt=request.attempt,
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
                traceback_path=str(request.traceback_path),
            )

        finished_at = utc_timestamp()
        if self.capture_stdout_stderr:
            _execution.logs.write_text_file(request.stdout_path, stdout_buffer.getvalue())
            _execution.logs.write_text_file(request.stderr_path, stderr_buffer.getvalue())
        if not isinstance(raw_outputs, Mapping):
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_id=request.run_id,
                stage_name=request.stage.name,
                attempt=request.attempt,
                failed_at=finished_at,
                executor=self.name,
                failure_type="stage_contract",
                message="stage.run() must return a mapping of output names to ArtifactRef values",
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
            )
            return StageExecutionResult(
                stage_name=request.stage.name,
                status=StageStatus.FAILED,
                outputs={},
                failure=failure,
                started_at=started_at,
                finished_at=finished_at,
                executor_name=self.name,
                attempt=request.attempt,
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
            )
        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs=cast(Mapping[str, ArtifactRef], dict(raw_outputs)),
            failure=None,
            started_at=started_at,
            finished_at=finished_at,
            executor_name=self.name,
            attempt=request.attempt,
            stdout_path=str(request.stdout_path),
            stderr_path=str(request.stderr_path),
            executor_metadata={"capture_stdout_stderr": self.capture_stdout_stderr},
        )


__all__ = ["LocalExecutor"]
