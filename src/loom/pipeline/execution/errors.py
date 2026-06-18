"""Execution-specific exceptions for pipeline runtime."""

from __future__ import annotations

from loom.errors import ExecutionError, PipelineError, ValidationError
from loom.serialization import PlainData


class PipelineExecutionError(ExecutionError, PipelineError):
    """Raised for runtime execution failures."""


class RunRequestError(PipelineExecutionError, ValidationError):
    """Raised when an execution request is invalid."""


class PlanExecutionError(PipelineExecutionError):
    """Raised when planning-derived decisions cannot be executed."""


class LifecycleError(PipelineExecutionError):
    """Raised for run or stage lifecycle persistence failures."""


class StageExecutionRuntimeError(PipelineExecutionError):
    """Raised for runtime stage execution infrastructure failures."""


class ParallelExecutionUnsupportedError(RunRequestError):
    """Raised when explicit bounded parallel execution is unsupported."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "pipeline.parallel.unsupported",
        context: dict[str, PlainData] | None = None,
        diagnostics: tuple[dict[str, PlainData], ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})
        self.diagnostics = tuple(diagnostics)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "message": str(self),
            "code": self.code,
            "context": dict(self.context),
            "diagnostics": [dict(diagnostic) for diagnostic in self.diagnostics],
        }


class OutputValidationError(PipelineExecutionError, ValidationError):
    """Raised when stage outputs violate declared output contracts."""


__all__ = [
    "PipelineExecutionError",
    "RunRequestError",
    "PlanExecutionError",
    "LifecycleError",
    "ParallelExecutionUnsupportedError",
    "StageExecutionRuntimeError",
    "OutputValidationError",
]
