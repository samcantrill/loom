"""Pipeline executor API."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.pipeline.executors.base import (
        Executor,
        ExecutorFactory,
        ExecutorRegistration,
        ExecutorRegistry,
        create_default_executor_registry,
    )
    from loom.pipeline.executors.errors import ExecutorError, LocalExecutorError
    from loom.pipeline.executors.local import LocalExecutor


def __getattr__(name: str) -> object:
    if name in {
        "Executor",
        "ExecutorFactory",
        "ExecutorRegistration",
        "ExecutorRegistry",
        "create_default_executor_registry",
    }:
        from loom.pipeline.executors.base import (
            Executor,
            ExecutorFactory,
            ExecutorRegistration,
            ExecutorRegistry,
            create_default_executor_registry,
        )

        return {
            "Executor": Executor,
            "ExecutorFactory": ExecutorFactory,
            "ExecutorRegistration": ExecutorRegistration,
            "ExecutorRegistry": ExecutorRegistry,
            "create_default_executor_registry": create_default_executor_registry,
        }[name]
    if name in {"ExecutorError", "LocalExecutorError"}:
        from loom.pipeline.executors.errors import ExecutorError, LocalExecutorError

        return {
            "ExecutorError": ExecutorError,
            "LocalExecutorError": LocalExecutorError,
        }[name]
    if name == "LocalExecutor":
        from loom.pipeline.executors.local import LocalExecutor

        return LocalExecutor
    raise AttributeError(f"module 'loom.pipeline.executors' has no attribute {name!r}")


__all__ = [
    "Executor",
    "ExecutorFactory",
    "ExecutorRegistration",
    "ExecutorRegistry",
    "create_default_executor_registry",
    "ExecutorError",
    "LocalExecutor",
    "LocalExecutorError",
]
