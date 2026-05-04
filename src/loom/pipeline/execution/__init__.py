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
    )
    from loom.pipeline.execution.outputs import validate_stage_outputs
    from loom.pipeline.execution.runner import PipelineRunner, run_pipeline


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
        )
        from loom.pipeline.execution.outputs import validate_stage_outputs
        from loom.pipeline.execution.runner import PipelineRunner, run_pipeline

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
    "run_pipeline",
    "validate_stage_outputs",
]
