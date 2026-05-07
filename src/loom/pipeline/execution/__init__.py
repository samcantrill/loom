"""Pipeline execution API."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.pipeline.execution.errors import (
        LifecycleError,
        OutputValidationError,
        PipelineExecutionError,
        PlanExecutionError,
        RunRequestError,
        StageExecutionRuntimeError,
    )
    from loom.pipeline.execution.models import (
        ConfigSnapshotInputs,
        ExecutionFailure,
        FailurePolicy,
        RunRequest,
        RunResult,
        StageExecutionRequest,
        StageExecutionResult,
        StageRunResult,
        StageWorkerRequest,
        StageWorkerResult,
    )
    from loom.pipeline.execution.models import redact_executor_metadata
    from loom.pipeline.execution.outputs import validate_stage_outputs
    from loom.pipeline.execution.runner import PipelineRunner, run_pipeline
    from loom.pipeline.execution.stage_attempts import prepare_stage_attempt


def __getattr__(name: str) -> object:
    if name in {
        "ConfigSnapshotInputs",
        "ExecutionFailure",
        "FailurePolicy",
        "LifecycleError",
        "OutputValidationError",
        "PipelineExecutionError",
        "PipelineRunner",
        "PlanExecutionError",
        "RunRequest",
        "RunRequestError",
        "RunResult",
        "StageExecutionRequest",
        "StageExecutionResult",
        "StageExecutionRuntimeError",
        "StageRunResult",
        "StageWorkerRequest",
        "StageWorkerResult",
        "prepare_stage_attempt",
        "redact_executor_metadata",
        "run_pipeline",
        "validate_stage_outputs",
    }:
        from loom.pipeline.execution.errors import (
            LifecycleError,
            OutputValidationError,
            PipelineExecutionError,
            PlanExecutionError,
            RunRequestError,
            StageExecutionRuntimeError,
        )
        from loom.pipeline.execution.models import (
            ConfigSnapshotInputs,
            ExecutionFailure,
            FailurePolicy,
            RunRequest,
            RunResult,
            StageExecutionRequest,
            StageExecutionResult,
            StageRunResult,
            StageWorkerRequest,
            StageWorkerResult,
            redact_executor_metadata,
        )
        from loom.pipeline.execution.outputs import validate_stage_outputs
        from loom.pipeline.execution.runner import PipelineRunner, run_pipeline
        from loom.pipeline.execution.stage_attempts import prepare_stage_attempt

        return {
            "ConfigSnapshotInputs": ConfigSnapshotInputs,
            "ExecutionFailure": ExecutionFailure,
            "FailurePolicy": FailurePolicy,
            "LifecycleError": LifecycleError,
            "OutputValidationError": OutputValidationError,
            "PipelineExecutionError": PipelineExecutionError,
            "PipelineRunner": PipelineRunner,
            "PlanExecutionError": PlanExecutionError,
            "RunRequest": RunRequest,
            "RunRequestError": RunRequestError,
            "RunResult": RunResult,
            "StageExecutionRequest": StageExecutionRequest,
            "StageExecutionResult": StageExecutionResult,
            "StageExecutionRuntimeError": StageExecutionRuntimeError,
            "StageRunResult": StageRunResult,
            "StageWorkerRequest": StageWorkerRequest,
            "StageWorkerResult": StageWorkerResult,
            "prepare_stage_attempt": prepare_stage_attempt,
            "redact_executor_metadata": redact_executor_metadata,
            "run_pipeline": run_pipeline,
            "validate_stage_outputs": validate_stage_outputs,
        }[name]
    raise AttributeError(f"module 'loom.pipeline.execution' has no attribute {name!r}")


__all__ = [
    "ConfigSnapshotInputs",
    "ExecutionFailure",
    "FailurePolicy",
    "LifecycleError",
    "OutputValidationError",
    "PipelineExecutionError",
    "PipelineRunner",
    "PlanExecutionError",
    "RunRequest",
    "RunRequestError",
    "RunResult",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageExecutionRuntimeError",
    "StageRunResult",
    "StageWorkerRequest",
    "StageWorkerResult",
    "prepare_stage_attempt",
    "redact_executor_metadata",
    "run_pipeline",
    "validate_stage_outputs",
]
