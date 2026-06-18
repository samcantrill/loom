"""Pipeline-phase exception hierarchy."""

from __future__ import annotations

from collections.abc import Sequence

from loom.errors import ContractError, PipelineError, ValidationError
from loom.ids import StageID


class PipelineValidationError(PipelineError, ValidationError):
    """Raised for invalid static pipeline specs and binding/graph inputs."""


class PipelineSpecError(PipelineValidationError):
    """Raised when the resolved pipeline configuration is malformed."""


class RuntimeResourceError(PipelineSpecError):
    """Raised when runtime or resource foundation models are malformed."""


class InputBindingError(PipelineValidationError):
    """Raised when stage input references are malformed or unresolved."""


class PipelineGraphError(PipelineValidationError):
    """Raised for invalid graph structure."""


class PipelineCycleError(PipelineGraphError):
    """Raised when a pipeline graph contains one or more cycles."""

    cycles: tuple[tuple[StageID, ...], ...]

    def __init__(self, cycles: Sequence[Sequence[StageID]], *, message: str | None = None) -> None:
        self.cycles = tuple(tuple(cycle) for cycle in cycles)
        if not self.cycles:
            resolved = message or "pipeline graph contains a cycle"
        else:
            cycle_list = ", ".join(" -> ".join(cycle) for cycle in self.cycles)
            if message is None:
                resolved = f"pipeline graph contains cycle(s): {cycle_list}"
            else:
                resolved = f"{message}: {cycle_list}"
        super().__init__(resolved)


class StageContractError(PipelineError, ContractError):
    """Raised when stage objects do not satisfy the required contract."""


class StatusSerializationError(PipelineValidationError):
    """Raised when status records cannot be serialized or deserialized."""


__all__ = [
    "PipelineValidationError",
    "PipelineSpecError",
    "RuntimeResourceError",
    "InputBindingError",
    "PipelineGraphError",
    "PipelineCycleError",
    "StageContractError",
    "StatusSerializationError",
]
