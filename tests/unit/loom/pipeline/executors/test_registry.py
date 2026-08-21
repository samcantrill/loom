from __future__ import annotations

from typing import Any, cast

import pytest

from loom.pipeline.executors import (
    ExecutorFactory,
    ExecutorRegistration,
    ExecutorRegistry,
)
from loom.pipeline.executors.errors import ExecutorError
from loom.pipeline.runtime import ExecutorDescriptor, RunOptions


class _Executor:
    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, request: object) -> object:
        return request


def test_registry_pairs_descriptor_factory_and_result_name() -> None:
    registry = ExecutorRegistry()
    registration = ExecutorRegistration(
        ExecutorDescriptor(name="project"),
        cast(ExecutorFactory, lambda **_: _Executor("project")),
    )
    registry.register(registration)
    assert registry.names == ("project",)
    assert registry.descriptor_registry.resolve("project") is registration.descriptor

    with pytest.raises(ExecutorError, match="already registered"):
        registry.register(registration)
    with pytest.raises(ExecutorError, match="result name"):
        ExecutorRegistry(
            {
                "project": ExecutorRegistration(
                    ExecutorDescriptor(name="project"),
                    cast(ExecutorFactory, lambda **_: _Executor("other")),
                )
            }
        ).build("project", services=cast(Any, object()), options=RunOptions())


def test_registry_rejects_unknown_name_and_non_executor_factory_result() -> None:
    registry = ExecutorRegistry()
    registry.register(
        ExecutorRegistration(
            ExecutorDescriptor(name="project"),
            cast(ExecutorFactory, lambda **_: object()),
        )
    )

    with pytest.raises(ExecutorError, match="unknown executor"):
        registry.resolve("missing")
    with pytest.raises(ExecutorError, match="did not return an Executor"):
        registry.build("project", services=cast(Any, object()), options=RunOptions())
