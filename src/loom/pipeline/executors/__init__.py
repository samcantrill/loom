"""Pipeline executor API."""

from typing import TYPE_CHECKING

from loom.pipeline.executors.base import Executor
from loom.pipeline.executors.errors import ExecutorError, LocalExecutorError
from loom.pipeline.executors.local import LocalExecutor

if TYPE_CHECKING:
    from loom.pipeline.executors.subprocess import (
        SubprocessExecutor,
        SubprocessRunResult,
    )


def __getattr__(name: str) -> object:
    if name in {"SubprocessExecutor", "SubprocessRunResult"}:
        from loom.pipeline.executors.subprocess import (
            SubprocessExecutor,
            SubprocessRunResult,
        )

        return {
            "SubprocessExecutor": SubprocessExecutor,
            "SubprocessRunResult": SubprocessRunResult,
        }[name]
    raise AttributeError(f"module 'loom.pipeline.executors' has no attribute {name!r}")

__all__ = [
    "Executor",
    "ExecutorError",
    "LocalExecutor",
    "LocalExecutorError",
    "SubprocessExecutor",
    "SubprocessRunResult",
]
