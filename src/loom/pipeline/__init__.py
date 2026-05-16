"""Pipeline package."""

from typing import TYPE_CHECKING

from loom.pipeline.errors import (
    InputBindingError,
    PipelineCycleError,
    PipelineGraphError,
    PipelineSpecError,
    PipelineValidationError,
    RuntimeResourceError,
    StageContractError,
    StatusSerializationError,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest, parse_resource_request
from loom.pipeline.runtime import (
    CONTINUE_INDEPENDENT_FAILURE_POLICY,
    DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY,
    DEFAULT_FAILURE_POLICY,
    DEFAULT_MAX_PARALLEL_STAGES,
    RUNTIME_CONFIG_SECTION,
    RUNTIME_METADATA_SCHEMA_VERSION,
    RUNTIME_PROFILES_CONFIG_SECTION,
    CapabilityDiagnostic,
    CapabilitySeverity,
    CapabilityValidationResult,
    ExecutionOptions,
    ExecutorDescriptor,
    ExecutorDescriptorRegistry,
    ParallelExecutionOptions,
    RunEnvironmentRequest,
    RunOptions,
    ResolvedStageRuntimeOptions,
    ResourceCapability,
    ResourceEnforcementExpectation,
    ResourceSupportLevel,
    RuntimeConfigSections,
    RuntimeMetadata,
    RuntimeProfile,
    RuntimeProfileCollection,
    RuntimeKind,
    RuntimeRequest,
    StageEnvironmentRequest,
    StageRuntimeOptions,
    build_runtime_metadata,
    merge_config_run_options,
    merge_run_options,
    parallel_execution_options,
    parse_run_options,
    parse_runtime_config_sections,
    parse_runtime_profile,
    parse_runtime_profiles,
    parse_runtime_request,
    resolve_executor_descriptor,
    resolve_run_runtime,
    select_runtime_profile,
    validate_executor_capabilities,
    validate_stage_runtime_options,
)
from loom.pipeline.specs import (
    PipelineSpec,
    StageFactorySpec,
    StageSpec,
    OutputSpec,
    parse_pipeline_config,
)
from loom.pipeline.validation import (
    PipelineTargetCheckResult,
    PipelineValidationResult,
    check_pipeline_stage_targets,
    validate_pipeline_config,
)
from loom.pipeline.stage import Stage
from loom.pipeline.submitted import (
    SubmittedOperationError,
    SubmittedOperationRecord,
    SubmittedOperationState,
    is_active_submitted_operation,
    is_terminal_submitted_operation,
)
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.status import parse_run_status, parse_stage_status

if TYPE_CHECKING:
    from loom.pipeline.context import StageContext
    from loom.pipeline.execution import PipelineRunner, RunRequest, RunResult


def __getattr__(name: str) -> object:
    if name == "StageContext":
        from loom.pipeline.context import StageContext as _StageContext

        return _StageContext
    if name in {"PipelineRunner", "RunRequest", "RunResult"}:
        from loom.pipeline import execution

        return getattr(execution, name)
    raise AttributeError(f"module 'loom.pipeline' has no attribute {name!r}")


__all__ = [
    "OutputSpec",
    "StageFactorySpec",
    "StageSpec",
    "PipelineSpec",
    "parse_pipeline_config",
    "PipelineValidationResult",
    "PipelineTargetCheckResult",
    "validate_pipeline_config",
    "check_pipeline_stage_targets",
    "Stage",
    "StageContext",
    "RunStatus",
    "StageStatus",
    "RunStatusRecord",
    "StageStatusRecord",
    "parse_run_status",
    "parse_stage_status",
    "SubmittedOperationError",
    "SubmittedOperationRecord",
    "SubmittedOperationState",
    "is_active_submitted_operation",
    "is_terminal_submitted_operation",
    "PipelineValidationError",
    "PipelineSpecError",
    "RuntimeResourceError",
    "InputBindingError",
    "PipelineGraphError",
    "PipelineCycleError",
    "StageContractError",
    "StatusSerializationError",
    "PipelineRunner",
    "RunRequest",
    "RunResult",
    "ResourceRequest",
    "ResourceEntry",
    "parse_resource_request",
    "DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY",
    "CONTINUE_INDEPENDENT_FAILURE_POLICY",
    "DEFAULT_FAILURE_POLICY",
    "DEFAULT_MAX_PARALLEL_STAGES",
    "RUNTIME_CONFIG_SECTION",
    "RUNTIME_METADATA_SCHEMA_VERSION",
    "RUNTIME_PROFILES_CONFIG_SECTION",
    "CapabilityDiagnostic",
    "CapabilitySeverity",
    "CapabilityValidationResult",
    "ExecutionOptions",
    "ExecutorDescriptor",
    "ExecutorDescriptorRegistry",
    "ParallelExecutionOptions",
    "RunEnvironmentRequest",
    "RunOptions",
    "ResolvedStageRuntimeOptions",
    "ResourceCapability",
    "ResourceEnforcementExpectation",
    "ResourceSupportLevel",
    "RuntimeConfigSections",
    "RuntimeMetadata",
    "RuntimeProfile",
    "RuntimeProfileCollection",
    "RuntimeKind",
    "RuntimeRequest",
    "StageEnvironmentRequest",
    "StageRuntimeOptions",
    "build_runtime_metadata",
    "merge_config_run_options",
    "merge_run_options",
    "parallel_execution_options",
    "parse_run_options",
    "parse_runtime_config_sections",
    "parse_runtime_profile",
    "parse_runtime_profiles",
    "parse_runtime_request",
    "resolve_executor_descriptor",
    "resolve_run_runtime",
    "select_runtime_profile",
    "validate_executor_capabilities",
    "validate_stage_runtime_options",
]
