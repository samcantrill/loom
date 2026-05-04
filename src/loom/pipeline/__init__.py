"""Pipeline package."""

from typing import TYPE_CHECKING

from loom.pipeline.context import StageContext
from loom.pipeline.errors import (
    InputBindingError,
    PipelineCycleError,
    PipelineGraphError,
    PipelineSpecError,
    PipelineValidationError,
    StageContractError,
    StatusSerializationError,
)
from loom.pipeline.specs import (
    PipelineSpec,
    StageFactorySpec,
    StageSpec,
    OutputSpec,
    parse_pipeline_config,
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
    "InputBindingError",
    "PipelineGraphError",
    "PipelineCycleError",
    "StageContractError",
    "StatusSerializationError",
    "PipelineRunner",
    "RunRequest",
    "RunResult",
]
