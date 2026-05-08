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
    from loom.pipeline.execution.prepared_run import (
        PREPARED_RUN_CONTINUATION_WHOLE_RUN,
        PREPARED_RUN_SCHEMA_VERSION,
        PreparedRunPayloadError,
        PreparedRunRecord,
    )
    from loom.pipeline.execution.models import redact_executor_metadata
    from loom.pipeline.execution.outputs import validate_stage_outputs
    from loom.pipeline.execution.runner import PipelineRunner, run_pipeline
    from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
    from loom.pipeline.execution.stage_worker import (
        StageWorkerRunRequest,
        StageWorkerStateError,
        infer_stage_worker_attempt,
        reconstruct_stage_execution_request,
        run_stage_worker,
    )


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
        "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
        "PREPARED_RUN_SCHEMA_VERSION",
        "PreparedRunPayloadError",
        "PreparedRunRecord",
        "RunRequest",
        "RunRequestError",
        "RunResult",
        "StageExecutionRequest",
        "StageExecutionResult",
        "StageExecutionRuntimeError",
        "StageRunResult",
        "StageWorkerRunRequest",
        "StageWorkerRequest",
        "StageWorkerResult",
        "StageWorkerStateError",
        "infer_stage_worker_attempt",
        "prepare_stage_attempt",
        "reconstruct_stage_execution_request",
        "redact_executor_metadata",
        "run_stage_worker",
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
        from loom.pipeline.execution.prepared_run import (
            PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            PREPARED_RUN_SCHEMA_VERSION,
            PreparedRunPayloadError,
            PreparedRunRecord,
        )
        from loom.pipeline.execution.runner import PipelineRunner, run_pipeline
        from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
        from loom.pipeline.execution.stage_worker import (
            StageWorkerRunRequest,
            StageWorkerStateError,
            infer_stage_worker_attempt,
            reconstruct_stage_execution_request,
            run_stage_worker,
        )

        return {
            "ConfigSnapshotInputs": ConfigSnapshotInputs,
            "ExecutionFailure": ExecutionFailure,
            "FailurePolicy": FailurePolicy,
            "LifecycleError": LifecycleError,
            "OutputValidationError": OutputValidationError,
            "PipelineExecutionError": PipelineExecutionError,
            "PipelineRunner": PipelineRunner,
            "PlanExecutionError": PlanExecutionError,
            "PREPARED_RUN_CONTINUATION_WHOLE_RUN": PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            "PREPARED_RUN_SCHEMA_VERSION": PREPARED_RUN_SCHEMA_VERSION,
            "PreparedRunPayloadError": PreparedRunPayloadError,
            "PreparedRunRecord": PreparedRunRecord,
            "RunRequest": RunRequest,
            "RunRequestError": RunRequestError,
            "RunResult": RunResult,
            "StageExecutionRequest": StageExecutionRequest,
            "StageExecutionResult": StageExecutionResult,
            "StageExecutionRuntimeError": StageExecutionRuntimeError,
            "StageRunResult": StageRunResult,
            "StageWorkerRunRequest": StageWorkerRunRequest,
            "StageWorkerRequest": StageWorkerRequest,
            "StageWorkerResult": StageWorkerResult,
            "StageWorkerStateError": StageWorkerStateError,
            "infer_stage_worker_attempt": infer_stage_worker_attempt,
            "prepare_stage_attempt": prepare_stage_attempt,
            "reconstruct_stage_execution_request": reconstruct_stage_execution_request,
            "redact_executor_metadata": redact_executor_metadata,
            "run_stage_worker": run_stage_worker,
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
    "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
    "PREPARED_RUN_SCHEMA_VERSION",
    "PreparedRunPayloadError",
    "PreparedRunRecord",
    "RunRequest",
    "RunRequestError",
    "RunResult",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageExecutionRuntimeError",
    "StageRunResult",
    "StageWorkerRunRequest",
    "StageWorkerRequest",
    "StageWorkerResult",
    "StageWorkerStateError",
    "infer_stage_worker_attempt",
    "prepare_stage_attempt",
    "reconstruct_stage_execution_request",
    "redact_executor_metadata",
    "run_stage_worker",
    "run_pipeline",
    "validate_stage_outputs",
]
