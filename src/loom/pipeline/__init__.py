"""Pipeline package."""

from typing import TYPE_CHECKING

from loom.pipeline.context import StageContext
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
    ExecutionOptions,
    RunEnvironmentRequest,
    RunOptions,
    RuntimeKind,
    RuntimeRequest,
    StageEnvironmentRequest,
    StageRuntimeOptions,
    parse_run_options,
    parse_runtime_request,
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
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.status import parse_run_status, parse_stage_status

if TYPE_CHECKING:
    from loom.pipeline.execution import PipelineRunner, RunRequest, RunResult


def __getattr__(name: str) -> object:
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
    "ExecutionOptions",
    "RunEnvironmentRequest",
    "RunOptions",
    "RuntimeKind",
    "RuntimeRequest",
    "StageEnvironmentRequest",
    "StageRuntimeOptions",
    "parse_run_options",
    "parse_runtime_request",
    "validate_stage_runtime_options",
]
