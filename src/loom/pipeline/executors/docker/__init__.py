"""Docker executor contracts and implementation."""

from typing import TYPE_CHECKING

from loom.pipeline.executors.docker.build import (
    DockerBuildOptions,
    DockerContainerBuilder,
    build_docker_build_command,
)
from loom.pipeline.executors.docker.commands import (
    DOCKER_COMMAND_RESULT_SCHEMA_VERSION,
    MAX_DOCKER_COMMAND_OUTPUT_CHARS,
    DockerCommandResult,
    DockerCommandRunner,
    DockerCommandUnavailableError,
    DockerOptionError,
    DockerOptions,
    DockerRunCommand,
    FakeDockerCommandRunner,
    SubprocessDockerCommandRunner,
    build_docker_image_digest_command,
    build_docker_run_command,
    build_docker_version_command,
    bound_docker_output,
    command_result_from_exception,
)

if TYPE_CHECKING:
    from loom.pipeline.executors.docker.executor import DockerExecutor


def __getattr__(name: str) -> object:
    if name == "DockerExecutor":
        from loom.pipeline.executors.docker.executor import DockerExecutor

        return DockerExecutor
    raise AttributeError(
        f"module 'loom.pipeline.executors.docker' has no attribute {name!r}"
    )

__all__ = [
    "DOCKER_COMMAND_RESULT_SCHEMA_VERSION",
    "MAX_DOCKER_COMMAND_OUTPUT_CHARS",
    "DockerBuildOptions",
    "DockerCommandResult",
    "DockerCommandRunner",
    "DockerContainerBuilder",
    "DockerExecutor",
    "DockerCommandUnavailableError",
    "DockerOptionError",
    "DockerOptions",
    "DockerRunCommand",
    "FakeDockerCommandRunner",
    "SubprocessDockerCommandRunner",
    "build_docker_build_command",
    "build_docker_image_digest_command",
    "build_docker_run_command",
    "build_docker_version_command",
    "bound_docker_output",
    "command_result_from_exception",
]
