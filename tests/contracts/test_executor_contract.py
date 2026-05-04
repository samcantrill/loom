"""Executor protocol contract tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from loom.pipeline.execution import StageExecutionRequest, StageExecutionResult
from loom.pipeline.executors import Executor, LocalExecutor


pytestmark = pytest.mark.contract


@dataclass(slots=True)
class StructuralExecutor:
    name: str = "structural"

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        raise NotImplementedError


def test_executor_protocol_is_structural() -> None:
    assert isinstance(StructuralExecutor(), Executor)
    assert isinstance(LocalExecutor(), Executor)
