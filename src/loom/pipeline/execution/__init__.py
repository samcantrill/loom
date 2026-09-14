"""Pipeline execution API."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.pipeline.execution.errors import (
        LifecycleError,
        OutputValidationError,
        ParallelExecutionUnsupportedError,
        PipelineExecutionError,
        PlanExecutionError,
        RunRequestError,
        StageReportedFailure,
        StageExecutionRuntimeError,
    )
    from loom.pipeline.execution.models import (
        ExecutionFailure,
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
    from loom.pipeline.execution.services import RuntimeServices
    from loom.pipeline.execution.resource_admission import (
        ResourceAdmissionDecision,
        ResourceAdmissionError,
        ResourceAdmissionRequest,
        ResourceAdmissionStatus,
        ResourceLimitReconciliationResult,
        ResourceLimitReconciliationStatus,
        ResourceLeaseRequest,
        acquire_resource_admission,
        reconcile_resource_limits,
        release_resource_admission,
        resource_requests_from_runtime,
    )
    from loom.pipeline.execution.authority_adapter import (
        create_authority_backed_serial_run_store,
    )
    from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
    from loom.pipeline.execution.stage_worker import StageWorkerStateError


def __getattr__(name: str) -> object:
    if name in {
        "ExecutionFailure",
        "LifecycleError",
        "OutputValidationError",
        "ParallelExecutionUnsupportedError",
        "PipelineExecutionError",
        "PlanExecutionError",
        "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
        "PREPARED_RUN_SCHEMA_VERSION",
        "PreparedRunPayloadError",
        "PreparedRunRecord",
        "RunRequestError",
        "StageReportedFailure",
        "RuntimeServices",
        "ResourceAdmissionDecision",
        "ResourceAdmissionError",
        "ResourceAdmissionRequest",
        "ResourceAdmissionStatus",
        "ResourceLimitReconciliationResult",
        "ResourceLimitReconciliationStatus",
        "ResourceLeaseRequest",
        "StageExecutionRequest",
        "StageExecutionResult",
        "StageExecutionRuntimeError",
        "StageRunResult",
        "StageWorkerRequest",
        "StageWorkerResult",
        "StageWorkerStateError",
        "create_authority_backed_serial_run_store",
        "acquire_resource_admission",
        "prepare_stage_attempt",
        "reconcile_resource_limits",
        "redact_executor_metadata",
        "release_resource_admission",
        "resource_requests_from_runtime",
        "validate_stage_outputs",
    }:
        from loom.pipeline.execution.errors import (
            LifecycleError,
            OutputValidationError,
            ParallelExecutionUnsupportedError,
            PipelineExecutionError,
            PlanExecutionError,
            RunRequestError,
            StageReportedFailure,
            StageExecutionRuntimeError,
        )
        from loom.pipeline.execution.models import (
            ExecutionFailure,
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
        from loom.pipeline.execution.services import RuntimeServices
        from loom.pipeline.execution.resource_admission import (
            ResourceAdmissionDecision,
            ResourceAdmissionError,
            ResourceAdmissionRequest,
            ResourceAdmissionStatus,
            ResourceLimitReconciliationResult,
            ResourceLimitReconciliationStatus,
            ResourceLeaseRequest,
            acquire_resource_admission,
            reconcile_resource_limits,
            release_resource_admission,
            resource_requests_from_runtime,
        )
        from loom.pipeline.execution.authority_adapter import (
            create_authority_backed_serial_run_store,
        )
        from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
        from loom.pipeline.execution.stage_worker import StageWorkerStateError

        return {
            "ExecutionFailure": ExecutionFailure,
            "LifecycleError": LifecycleError,
            "OutputValidationError": OutputValidationError,
            "ParallelExecutionUnsupportedError": ParallelExecutionUnsupportedError,
            "PipelineExecutionError": PipelineExecutionError,
            "PlanExecutionError": PlanExecutionError,
            "PREPARED_RUN_CONTINUATION_WHOLE_RUN": PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            "PREPARED_RUN_SCHEMA_VERSION": PREPARED_RUN_SCHEMA_VERSION,
            "PreparedRunPayloadError": PreparedRunPayloadError,
            "PreparedRunRecord": PreparedRunRecord,
            "RunRequestError": RunRequestError,
            "StageReportedFailure": StageReportedFailure,
            "RuntimeServices": RuntimeServices,
            "ResourceAdmissionDecision": ResourceAdmissionDecision,
            "ResourceAdmissionError": ResourceAdmissionError,
            "ResourceAdmissionRequest": ResourceAdmissionRequest,
            "ResourceAdmissionStatus": ResourceAdmissionStatus,
            "ResourceLimitReconciliationResult": ResourceLimitReconciliationResult,
            "ResourceLimitReconciliationStatus": ResourceLimitReconciliationStatus,
            "ResourceLeaseRequest": ResourceLeaseRequest,
            "StageExecutionRequest": StageExecutionRequest,
            "StageExecutionResult": StageExecutionResult,
            "StageExecutionRuntimeError": StageExecutionRuntimeError,
            "StageRunResult": StageRunResult,
            "StageWorkerRequest": StageWorkerRequest,
            "StageWorkerResult": StageWorkerResult,
            "StageWorkerStateError": StageWorkerStateError,
            "create_authority_backed_serial_run_store": create_authority_backed_serial_run_store,
            "acquire_resource_admission": acquire_resource_admission,
            "prepare_stage_attempt": prepare_stage_attempt,
            "reconcile_resource_limits": reconcile_resource_limits,
            "redact_executor_metadata": redact_executor_metadata,
            "release_resource_admission": release_resource_admission,
            "resource_requests_from_runtime": resource_requests_from_runtime,
            "validate_stage_outputs": validate_stage_outputs,
        }[name]
    raise AttributeError(f"module 'loom.pipeline.execution' has no attribute {name!r}")


__all__ = [
    "ExecutionFailure",
    "LifecycleError",
    "OutputValidationError",
    "ParallelExecutionUnsupportedError",
    "PipelineExecutionError",
    "PlanExecutionError",
    "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
    "PREPARED_RUN_SCHEMA_VERSION",
    "PreparedRunPayloadError",
    "PreparedRunRecord",
    "RunRequestError",
    "StageReportedFailure",
    "RuntimeServices",
    "ResourceAdmissionDecision",
    "ResourceAdmissionError",
    "ResourceAdmissionRequest",
    "ResourceAdmissionStatus",
    "ResourceLimitReconciliationResult",
    "ResourceLimitReconciliationStatus",
    "ResourceLeaseRequest",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageExecutionRuntimeError",
    "StageRunResult",
    "StageWorkerRequest",
    "StageWorkerResult",
    "StageWorkerStateError",
    "acquire_resource_admission",
    "create_authority_backed_serial_run_store",
    "prepare_stage_attempt",
    "reconcile_resource_limits",
    "redact_executor_metadata",
    "release_resource_admission",
    "resource_requests_from_runtime",
    "validate_stage_outputs",
]
