"""Apptainer command contracts and prepared-worker execution."""

from typing import TYPE_CHECKING

from loom.pipeline.executors.apptainer.build import (
    APPTAINER_COMMAND_RESULT_SCHEMA_VERSION,
    ApptainerBuildCommand,
    ApptainerBuildOptions,
    ApptainerCommandResult,
    ApptainerCommandRunner,
    ApptainerContainerBuilder,
    ApptainerOptionError,
    FakeApptainerCommandRunner,
    SubprocessApptainerCommandRunner,
    build_apptainer_build_command,
)
from loom.pipeline.executors.apptainer.commands import (
    ApptainerExecCommand,
    ApptainerExecOptions,
    ApptainerExecRunner,
    FakeApptainerExecRunner,
    SubprocessApptainerExecRunner,
    build_apptainer_exec_command,
    build_apptainer_version_command,
)

if TYPE_CHECKING:
    from loom.pipeline.executors.apptainer.executor import (
        ApptainerExecutor,
        SingularityExecutor,
    )


def __getattr__(name: str) -> object:
    if name in {"ApptainerExecutor", "SingularityExecutor"}:
        from loom.pipeline.executors.apptainer.executor import (
            ApptainerExecutor,
            SingularityExecutor,
        )

        return {
            "ApptainerExecutor": ApptainerExecutor,
            "SingularityExecutor": SingularityExecutor,
        }[name]
    raise AttributeError(
        f"module 'loom.pipeline.executors.apptainer' has no attribute {name!r}"
    )


__all__ = [
    "APPTAINER_COMMAND_RESULT_SCHEMA_VERSION",
    "ApptainerBuildCommand",
    "ApptainerBuildOptions",
    "ApptainerCommandResult",
    "ApptainerCommandRunner",
    "ApptainerContainerBuilder",
    "ApptainerExecCommand",
    "ApptainerExecOptions",
    "ApptainerExecRunner",
    "ApptainerExecutor",
    "ApptainerOptionError",
    "FakeApptainerCommandRunner",
    "FakeApptainerExecRunner",
    "SingularityExecutor",
    "SubprocessApptainerCommandRunner",
    "SubprocessApptainerExecRunner",
    "build_apptainer_build_command",
    "build_apptainer_exec_command",
    "build_apptainer_version_command",
]
