"""Local in-process stage executor."""

from __future__ import annotations

import contextlib
import io
import traceback
from pathlib import Path
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from loom.artifacts import ArtifactRef
from loom.serialization._diagnostic_capture import _capture_exception_details
from loom.pipeline.early_stopping import (
    EarlyStopSignal,
    lifecycle_reason_from_early_stop,
)
from loom.pipeline.execution.errors import StageReportedFailure
from loom.pipeline.reliability import TimeoutOutcome, TimeoutSupportLevel
from loom.pipeline.stage import Stage
from loom.pipeline.status import StageStatus
from loom.timestamps import utc_timestamp

from ._reliability import (
    metadata_with_timeout,
    timeout_metadata,
    timeout_policy_from_request,
)
from .errors import LocalExecutorError

if TYPE_CHECKING:
    from loom.pipeline.execution.models import (
        StageExecutionRequest,
        StageExecutionResult,
    )


class LocalExecutor:
    name = "local"

    def __init__(self, *, capture_stdout_stderr: bool = False) -> None:
        if not isinstance(capture_stdout_stderr, bool):
            raise LocalExecutorError("capture_stdout_stderr must be a bool")
        self.capture_stdout_stderr = capture_stdout_stderr

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        from loom.pipeline.execution.logs import write_text_file
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

        request_metadata = request.to_safe_metadata()
        context = replace(
            request.context,
            artifact_store=request.context._artifact_store,
            output_specs=request.context._output_specs,
            local_output_dir=request.context._local_output_dir,
            local_workspace_dir=request.context._local_workspace_dir,
            metadata={
                **request.context.metadata,
                "execution_request": request_metadata,
            },
        )
        common_metadata = {
            "capture_stdout_stderr": self.capture_stdout_stderr,
            "request": request_metadata,
            "execution_kind": "in_process",
            "command": None,
            "cwd": str(Path.cwd()),
        }
        started_at = utc_timestamp()
        policy = timeout_policy_from_request(request)
        timeout = (
            None
            if policy is None
            else timeout_metadata(
                policy=policy,
                support_level=TimeoutSupportLevel.UNSUPPORTED,
                outcome=TimeoutOutcome.UNSUPPORTED,
                timed_out=False,
                message="local executor cannot safely interrupt in-process stage code",
            )
        )
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            if not (
                request.metadata.get("worker_request")
                or request.metadata.get("resident_worker_request")
            ):
                from loom.pipeline.runtime.metadata import ResolvedStageRuntimeOptions
                from loom.pipeline.runtime.resource_policy import ResourcePolicy
                from loom.pipeline.resources import ResourceRequest

                runtime = request.resolved_runtime
                if isinstance(runtime, ResolvedStageRuntimeOptions):
                    selected = cast(ResourcePolicy, runtime.resource_policy).select(
                        cast(ResourceRequest, runtime.resources).entries
                    )["enforce"]
                    if selected:
                        raise LocalExecutorError(
                            f"native local execution cannot enforce {', '.join(selected)}; "
                            "omit these kinds from resource_policy.enforce or use a supporting execution owner"
                        )
            if self.capture_stdout_stderr:
                with (
                    contextlib.redirect_stdout(stdout_buffer),
                    contextlib.redirect_stderr(stderr_buffer),
                ):
                    raw_outputs = request.stage_object.run(context, request.inputs)
            else:
                raw_outputs = request.stage_object.run(context, request.inputs)
        except EarlyStopSignal as exc:
            finished_at = utc_timestamp()
            if self.capture_stdout_stderr:
                write_text_file(request.stdout_path, stdout_buffer.getvalue())
                write_text_file(request.stderr_path, stderr_buffer.getvalue())
            reason = lifecycle_reason_from_early_stop(exc)
            return StageExecutionResult(
                stage_name=request.stage.name,
                status=StageStatus.CANCELLED,
                outputs={},
                failure=None,
                started_at=started_at,
                finished_at=finished_at,
                executor_name=self.name,
                attempt=request.attempt,
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
                executor_metadata=metadata_with_timeout(
                    {
                        **common_metadata,
                        "lifecycle_reason": reason.to_dict(),
                    },
                    timeout,
                ),
            )
        except StageReportedFailure as exc:
            finished_at = utc_timestamp()
            if self.capture_stdout_stderr:
                write_text_file(request.stdout_path, stdout_buffer.getvalue())
                write_text_file(request.stderr_path, stderr_buffer.getvalue())
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_uri=request.run_uri,
                stage_name=request.stage.name,
                attempt=request.attempt,
                failed_at=finished_at,
                executor=self.name,
                failure_type="stage_exception",
                message="stage reported a domain failure",
                exception_type="loom.pipeline.execution.StageReportedFailure",
                stdout_path=str(request.stdout_path),
                stderr_path=str(request.stderr_path),
                details={"domain_failure": exc.domain_failure},
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
                executor_metadata=metadata_with_timeout(
                    common_metadata,
                    timeout,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - trusted stage failures become structured results.
            finished_at = utc_timestamp()
            traceback_text = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            write_text_file(request.traceback_path, traceback_text)
            if self.capture_stdout_stderr:
                write_text_file(request.stdout_path, stdout_buffer.getvalue())
                write_text_file(request.stderr_path, stderr_buffer.getvalue())
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_uri=request.run_uri,
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
                details=_capture_exception_details(exc, traceback_text=traceback_text),
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
                executor_metadata=metadata_with_timeout(
                    common_metadata,
                    timeout,
                ),
            )

        finished_at = utc_timestamp()
        if self.capture_stdout_stderr:
            write_text_file(request.stdout_path, stdout_buffer.getvalue())
            write_text_file(request.stderr_path, stderr_buffer.getvalue())
        if not isinstance(raw_outputs, Mapping):
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_uri=request.run_uri,
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
                executor_metadata=metadata_with_timeout(
                    common_metadata,
                    timeout,
                ),
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
            executor_metadata=metadata_with_timeout(
                common_metadata,
                timeout,
            ),
        )


__all__ = ["LocalExecutor"]
