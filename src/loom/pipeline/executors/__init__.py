"""Pipeline executor API."""

from typing import TYPE_CHECKING

from loom.pipeline.executors.base import Executor, ExecutorFactory, ExecutorRegistration, ExecutorRegistry

if TYPE_CHECKING:
    from loom.pipeline.executors.apptainer import (
        ApptainerExecutor,
        SingularityExecutor,
    )
    from loom.pipeline.executors.docker import DockerExecutor
    from loom.pipeline.executors.errors import ExecutorError, LocalExecutorError
    from loom.pipeline.executors.local import LocalExecutor
    from loom.pipeline.executors.subprocess import (
        SubprocessExecutor,
        SubprocessRunResult,
    )


def __getattr__(name: str) -> object:
    if name in {"ExecutorError", "LocalExecutorError"}:
        from loom.pipeline.executors.errors import ExecutorError, LocalExecutorError

        return {
            "ExecutorError": ExecutorError,
            "LocalExecutorError": LocalExecutorError,
        }[name]
    if name == "LocalExecutor":
        from loom.pipeline.executors.local import LocalExecutor

        return LocalExecutor
    if name == "DockerExecutor":
        from loom.pipeline.executors.docker import DockerExecutor

        return DockerExecutor
    if name in {"ApptainerExecutor", "SingularityExecutor"}:
        from loom.pipeline.executors.apptainer import (
            ApptainerExecutor,
            SingularityExecutor,
        )

        return {
            "ApptainerExecutor": ApptainerExecutor,
            "SingularityExecutor": SingularityExecutor,
        }[name]
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
    "ApptainerExecutor",
    "Executor",
    "ExecutorFactory",
    "ExecutorRegistration",
    "ExecutorRegistry",
    "DockerExecutor",
    "ExecutorError",
    "LocalExecutor",
    "LocalExecutorError",
    "SingularityExecutor",
    "SubprocessExecutor",
    "SubprocessRunResult",
]
