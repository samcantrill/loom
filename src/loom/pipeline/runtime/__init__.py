"""Runtime request and invocation option public facade."""

from loom.pipeline.runtime._models import (
    RUNTIME_SCHEMA_VERSION,
    RuntimeKind,
    RuntimeRequest,
    parse_runtime_request,
)
from loom.pipeline.runtime.capabilities import (
    DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY,
    CapabilityDiagnostic,
    CapabilitySeverity,
    CapabilityValidationResult,
    ExecutorDescriptor,
    ExecutorDescriptorRegistry,
    ResourceCapability,
    ResourceEnforcementExpectation,
    ResourceSupportLevel,
    resolve_executor_descriptor,
    validate_executor_capabilities,
)
from loom.pipeline.runtime.environment import (
    RunEnvironmentRequest,
    StageEnvironmentRequest,
)
from loom.pipeline.runtime.options import (
    RUN_OPTIONS_SCHEMA_VERSION,
    ExecutionOptions,
    RunOptions,
    StageRuntimeOptions,
    parse_run_options,
    validate_stage_runtime_options,
)
from loom.pipeline.runtime.profiles import (
    RuntimeProfile,
    RuntimeProfileCollection,
    merge_run_options,
    parse_runtime_profile,
    parse_runtime_profiles,
    select_runtime_profile,
)

__all__ = [
    "DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY",
    "RUN_OPTIONS_SCHEMA_VERSION",
    "RUNTIME_SCHEMA_VERSION",
    "CapabilityDiagnostic",
    "CapabilitySeverity",
    "CapabilityValidationResult",
    "ExecutionOptions",
    "ExecutorDescriptor",
    "ExecutorDescriptorRegistry",
    "RunEnvironmentRequest",
    "RunOptions",
    "ResourceCapability",
    "ResourceEnforcementExpectation",
    "ResourceSupportLevel",
    "RuntimeProfile",
    "RuntimeProfileCollection",
    "RuntimeKind",
    "RuntimeRequest",
    "StageEnvironmentRequest",
    "StageRuntimeOptions",
    "merge_run_options",
    "parse_run_options",
    "parse_runtime_profile",
    "parse_runtime_profiles",
    "parse_runtime_request",
    "resolve_executor_descriptor",
    "select_runtime_profile",
    "validate_executor_capabilities",
    "validate_stage_runtime_options",
]
