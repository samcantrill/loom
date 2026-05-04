"""Execution-specific exceptions for pipeline runtime."""

from __future__ import annotations

from loom.errors import ExecutionError, PipelineError, ValidationError


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


class OutputValidationError(PipelineExecutionError, ValidationError):
    """Raised when stage outputs violate declared output contracts."""


__all__ = [
    "PipelineExecutionError",
    "RunRequestError",
    "PlanExecutionError",
    "LifecycleError",
    "StageExecutionRuntimeError",
    "OutputValidationError",
]
