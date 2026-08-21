from __future__ import annotations

import pytest

from loom.pipeline.executors import ExecutorRegistration, ExecutorRegistry
from loom.pipeline.executors.errors import ExecutorError
from loom.pipeline.runtime import ExecutorDescriptor, RunOptions


class _Executor:
    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, request: object) -> object:
        return request


def test_registry_pairs_descriptor_factory_and_result_name() -> None:
    registry = ExecutorRegistry()
    registration = ExecutorRegistration(ExecutorDescriptor(name="project"), lambda **_: _Executor("project"))
    registry.register(registration)
    assert registry.names == ("project",)
    assert registry.descriptor_registry.resolve("project") is registration.descriptor

    with pytest.raises(ExecutorError, match="already registered"):
        registry.register(registration)
    with pytest.raises(ExecutorError, match="result name"):
        ExecutorRegistry({"project": ExecutorRegistration(ExecutorDescriptor(name="project"), lambda **_: _Executor("other"))}).build(
            "project", services=object(), options=RunOptions()
        )
