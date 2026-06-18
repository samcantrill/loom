"""Executor protocol for pipeline stages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from loom.pipeline.execution.models import (
        StageExecutionRequest,
        StageExecutionResult,
    )


@runtime_checkable
class Executor(Protocol):
    name: str

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult: ...


__all__ = ["Executor"]
