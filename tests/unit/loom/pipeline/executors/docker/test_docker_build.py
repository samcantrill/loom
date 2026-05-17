"""Unit tests for Docker container build helpers."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
    ContainerBuildCommandProjection,
    ContainerBuildFailure,
    ContainerBuildOutputRef,
    ContainerBuildPolicy,
    ContainerBuildRequest,
    ContainerBuildSource,
    ContainerBuildTarget,
    ContainerOptionError,
)
from loom.pipeline.executors.docker.build import (
    DockerBuildOptions,
    DockerContainerBuilder,
    build_docker_build_command,
)
from loom.pipeline.executors.docker.commands import (
    DockerCommandResult,
    FakeDockerCommandRunner,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


def _target(*, policy: str = "always") -> ContainerBuildTarget:
    return ContainerBuildTarget(
        name="ci-image",
        runtime="docker",
        source=ContainerBuildSource(
            kind="docker_context",
            context_path=".",
            recipe_path="Dockerfile",
        ),
        output=ContainerBuildOutputRef(
            kind="docker_image",
            reference="example/ci:latest",
        ),
        policy=ContainerBuildPolicy(mode=policy),
        build_args={"TOKEN": "secret", "MODE": "test"},
    )


def test_docker_build_command_redacts_build_args() -> None:
    request = ContainerBuildRequest(target=_target(), requested_by="unit-test")

    command = build_docker_build_command(
        request,
        docker_build_options=DockerBuildOptions(buildx=True, builder="local"),
    )

    assert command.argv == (
        "docker",
        "buildx",
        "build",
        "--builder",
        "local",
        "--tag",
        "example/ci:latest",
        "--file",
        "Dockerfile",
        "--build-arg",
        "MODE=test",
        "--build-arg",
        "TOKEN=secret",
        ".",
    )
    assert cast(tuple[str, ...], command.redacted_argv) == (
        "docker",
        "buildx",
        "build",
        "--builder",
        "local",
        "--tag",
        "example/ci:latest",
        "--file",
        "Dockerfile",
        "--build-arg",
        f"MODE={REDACTED_VALUE}",
        "--build-arg",
        f"TOKEN={REDACTED_VALUE}",
        ".",
    )
    assert "secret" not in repr(command.metadata)


def test_docker_builder_reuses_local_image_for_if_stale_policy() -> None:
    inspect = DockerCommandResult(
        command="docker",
        argv=("docker", "image", "inspect", "example/ci:latest"),
        redacted_argv=("docker", "image", "inspect", "example/ci:latest"),
        returncode=0,
        stdout="example/ci@sha256:abc\n",
    )
    runner = FakeDockerCommandRunner(scripted_results=[inspect])
    builder = DockerContainerBuilder(runner=runner)

    result = builder.build(
        ContainerBuildRequest(target=_target(policy="if_stale"), requested_by="test")
    )

    assert result.status == "reused"
    assert len(runner.calls) == 1


def test_docker_builder_builds_and_records_redacted_projection() -> None:
    missing = DockerCommandResult(
        command="docker",
        argv=("docker", "image", "inspect", "example/ci:latest"),
        redacted_argv=("docker", "image", "inspect", "example/ci:latest"),
        returncode=1,
    )
    runner = FakeDockerCommandRunner(scripted_results=[missing])
    builder = DockerContainerBuilder(runner=runner)

    result = builder.build(ContainerBuildRequest(target=_target(), requested_by="test"))

    assert result.status == "built"
    assert len(runner.calls) == 2
    command = cast(ContainerBuildCommandProjection, result.command)
    assert f"TOKEN={REDACTED_VALUE}" in command.argv
    assert "secret" not in repr(result.to_dict())


def test_docker_builder_reports_command_failure_without_raw_args() -> None:
    missing = DockerCommandResult(
        command="docker",
        argv=("docker", "image", "inspect", "example/ci:latest"),
        redacted_argv=("docker", "image", "inspect", "example/ci:latest"),
        returncode=1,
    )
    failed = DockerCommandResult(
        command="docker",
        argv=("docker", "build", "--build-arg", "TOKEN=secret", "."),
        redacted_argv=(
            "docker",
            "build",
            "--build-arg",
            f"TOKEN={REDACTED_VALUE}",
            ".",
        ),
        returncode=2,
        error="CalledProcessError",
    )
    runner = FakeDockerCommandRunner(scripted_results=[missing, failed])
    builder = DockerContainerBuilder(runner=runner)

    result = builder.build(ContainerBuildRequest(target=_target(), requested_by="test"))

    assert result.status == "failed"
    details = cast(dict[str, PlainData], cast(ContainerBuildFailure, result.failure).details)
    assert details["returncode"] == 2
    assert "secret" not in repr(result.to_dict())


def test_docker_builder_rejects_non_docker_targets() -> None:
    target = ContainerBuildTarget(
        name="bad",
        runtime="apptainer",
        source={"kind": "definition_file", "path": "a.def"},
        output={"kind": "apptainer_sif", "path": "a.sif"},
    )

    with pytest.raises(ContainerOptionError, match="docker"):
        build_docker_build_command(
            ContainerBuildRequest(target=target, requested_by="test")
        )
