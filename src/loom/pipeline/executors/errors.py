"""Executor-specific errors."""

from __future__ import annotations

from loom.pipeline.execution.errors import PipelineExecutionError


class ExecutorError(PipelineExecutionError):
    """Raised for executor infrastructure failures."""


class LocalExecutorError(ExecutorError):
    """Raised for local in-process executor infrastructure failures."""


__all__ = ["ExecutorError", "LocalExecutorError"]
