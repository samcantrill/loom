"""Unit tests for Docker command construction and runners."""

from __future__ import annotations

import subprocess
import sys
from typing import cast

import pytest

from loom.pipeline.executors.containers import ContainerOptions, ContainerResourceIntent
from loom.pipeline.executors.docker import (
    MAX_DOCKER_COMMAND_OUTPUT_CHARS,
    DockerCommandResult,
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
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import ResourceCapability
from loom.serialization import stable_json_dumps


pytestmark = pytest.mark.unit


def test_build_docker_run_command_is_deterministic_and_redacted() -> None:
    container = _container_options()

    command = build_docker_run_command(
        container_options=container,
        docker_options={
            "network": "none",
            "platform": "linux/amd64",
            "user": "1000:1000",
            "hostname": "loom-stage",
        },
        worker_command=("python", "-c", "print('ok')"),
    )

    assert command.argv == (
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--platform",
        "linux/amd64",
        "--user",
        "1000:1000",
        "--hostname",
        "loom-stage",
        "--workdir",
        "/workspace",
        "--mount",
        "type=bind,source=/readonly,target=/readonly,readonly",
        "--mount",
        "type=bind,source=/workspace,target=/workspace",
        "--env",
        "MODE=test",
        "--env",
        "TOKEN=secret",
        "--env",
        "HOME",
        "--cpus",
        "2",
        "--memory",
        "512m",
        "python:3.12-slim",
        "python",
        "-c",
        "print('ok')",
    )
    assert command.redacted_argv == (
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--platform",
        "linux/amd64",
        "--user",
        "1000:1000",
        "--hostname",
        "loom-stage",
        "--workdir",
        "/workspace",
        "--mount",
        "type=bind,source=/readonly,target=/readonly,readonly",
        "--mount",
        "type=bind,source=/workspace,target=/workspace",
        "--env",
        "MODE=[redacted]",
        "--env",
        "TOKEN=[redacted]",
        "--env",
        "HOME",
        "--cpus",
        "2",
        "--memory",
        "512m",
        "python:3.12-slim",
        "python",
        "-c",
        "print('ok')",
    )
    assert stable_json_dumps(command.to_dict())
    assert "secret" not in repr(command.metadata)
    assert "TOKEN=[redacted]" in repr(command.metadata)


def test_docker_options_and_command_inputs_reject_invalid_shapes() -> None:
    with pytest.raises(DockerOptionError, match="unknown field"):
        DockerOptions.from_dict({"privileged": True})
    with pytest.raises(DockerOptionError, match="command"):
        DockerOptions.from_dict({"command": None})
    with pytest.raises(DockerOptionError, match="non-empty"):
        DockerOptions(command=" ")
    with pytest.raises(DockerOptionError, match="worker_command"):
        build_docker_run_command(
            container_options=_container_options(),
            worker_command=(),
        )
    with pytest.raises(DockerOptionError, match="environment variable name"):
        build_docker_run_command(
            container_options=ContainerOptions(
                image="python",
                environment={"variables": {"BAD-NAME": "value"}},
            ),
            worker_command=("python", "-V"),
        )


def test_gpu_and_unknown_resources_fail_closed() -> None:
    gpu_intent = ContainerResourceIntent(
        entries={"gpu": ResourceEntry(kind="gpu", amount=1)},
        capabilities={
            "gpu": ResourceCapability(
                support_level="unsupported",
                enforcement="not_applicable",
                severity="error",
            )
        },
    )
    custom_intent = ContainerResourceIntent(
        entries={"custom.accelerator": ResourceEntry(kind="custom.accelerator", amount=1)},
        capabilities={
            "custom.accelerator": ResourceCapability(
                support_level="supported",
                enforcement="best_effort",
            )
        },
    )

    with pytest.raises(DockerOptionError, match="unsupported"):
        build_docker_run_command(
            container_options=ContainerOptions(image="python", resources=gpu_intent),
            worker_command=("python", "-V"),
        )
    with pytest.raises(DockerOptionError, match="custom.accelerator"):
        build_docker_run_command(
            container_options=ContainerOptions(image="python", resources=custom_intent),
            worker_command=("python", "-V"),
        )


def test_command_result_round_trip_and_output_bounding() -> None:
    long_text = "x" * (MAX_DOCKER_COMMAND_OUTPUT_CHARS + 100)
    result = DockerCommandResult(
        command="docker",
        argv=("docker", "--version"),
        redacted_argv=("docker", "--version"),
        returncode=1,
        stdout=long_text,
        stderr="bad\x00output",
        error="failed\x01badly",
    )

    document = result.to_dict()

    assert stable_json_dumps(document)
    assert DockerCommandResult.from_dict(document).to_dict() == document
    assert cast(str, document["stdout"]).endswith("...[truncated]")
    assert document["stderr"] == "bad?output"
    assert document["error"] == "failed?badly"
    with pytest.raises(DockerOptionError, match="schema_version"):
        DockerCommandResult.from_dict({**document, "schema_version": 99})


def test_fake_runner_records_calls_and_scripts_results() -> None:
    scripted = DockerCommandResult(
        command="docker",
        argv=("docker", "--version"),
        redacted_argv=("docker", "--version"),
        returncode=0,
        stdout="Docker version 27.0.0",
    )
    runner = FakeDockerCommandRunner(scripted_results=(scripted,))

    result = runner.version()

    assert result is scripted
    assert runner.calls[0].argv == ("docker", "--version")
    with pytest.raises(DockerCommandUnavailableError):
        FakeDockerCommandRunner(unavailable_commands=("docker",)).version()


def test_runner_exception_mapping_preserves_bounded_timeout_facts() -> None:
    exc = subprocess.TimeoutExpired(
        cmd=("docker", "run"),
        timeout=5,
        output="partial",
        stderr=b"slow",
    )

    result = command_result_from_exception(
        command="docker",
        argv=("docker", "run"),
        redacted_argv=("docker", "run"),
        exc=exc,
        timeout_seconds=5,
    )

    assert result.timed_out is True
    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.stderr == "slow"
    assert result.timeout_seconds == 5


def test_runner_exception_mapping_redacts_argv_values_from_error_text() -> None:
    result = command_result_from_exception(
        command="docker",
        argv=("docker", "run", "--env", "TOKEN=secret"),
        redacted_argv=("docker", "run", "--env", "TOKEN=[redacted]"),
        exc=RuntimeError("failed command TOKEN=secret"),
    )

    assert "secret" not in cast(str, result.error)
    assert "TOKEN=[redacted]" in cast(str, result.error)


def test_subprocess_runner_uses_shell_free_argv() -> None:
    runner = SubprocessDockerCommandRunner()
    command = DockerRunCommand.from_argv(
        (sys.executable, "-c", "print('ok')"),
        metadata={"operation": "unit-test"},
    )

    result = runner.run(command)

    assert result.ok is True
    assert result.stdout.strip() == "ok"
    assert result.argv == (sys.executable, "-c", "print('ok')")


def test_version_and_image_digest_commands_do_not_pull_images() -> None:
    version = build_docker_version_command()
    digest = build_docker_image_digest_command(image="python:3.12-slim")

    assert version.argv == ("docker", "--version")
    assert digest.argv == (
        "docker",
        "image",
        "inspect",
        "--format",
        "{{index .RepoDigests 0}}",
        "python:3.12-slim",
    )
    assert digest.metadata["pull"] is False


def test_bound_docker_output_rejects_non_text_values() -> None:
    with pytest.raises(DockerOptionError, match="must be a string"):
        bound_docker_output(123)


def _container_options() -> ContainerOptions:
    resources = ResourceRequest(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
        }
    )
    intent = ContainerResourceIntent.from_runtime(
        resources,
        {
            "cpu": ResourceCapability(
                support_level="supported",
                enforcement="best_effort",
            ),
            "memory": ResourceCapability(
                support_level="supported",
                enforcement="best_effort",
            ),
        },
    )
    return ContainerOptions(
        image="python:3.12-slim",
        workdir="/workspace",
        mounts=(
            {"source": "/workspace", "target": "/workspace", "mode": "rw"},
            {"source": "/readonly", "target": "/readonly", "mode": "ro"},
        ),
        environment={
            "variables": {"TOKEN": "secret", "MODE": "test"},
            "required_host_variables": ["HOME"],
        },
        resources=intent,
    )
