"""Executor protocol for pipeline stages."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loom.pipeline.execution.models import StageExecutionRequest, StageExecutionResult


@runtime_checkable
class Executor(Protocol):
    name: str

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult: ...


__all__ = ["Executor"]
