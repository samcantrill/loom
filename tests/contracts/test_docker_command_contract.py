"""Contracts for Docker command records."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.executors.containers import ContainerOptions
from loom.pipeline.executors.docker import (
    DOCKER_COMMAND_RESULT_SCHEMA_VERSION,
    DockerCommandResult,
    DockerOptions,
    DockerRunCommand,
    build_docker_run_command,
)
from loom.serialization import PlainData, stable_json_dumps


pytestmark = pytest.mark.contract


def test_docker_options_plain_data_contract_is_stable() -> None:
    options = DockerOptions.from_dict(
        {
            "command": "docker",
            "remove": True,
            "network": "none",
            "platform": "linux/amd64",
            "user": "1000:1000",
            "hostname": "loom-stage",
        }
    )

    assert options.to_dict() == {
        "command": "docker",
        "remove": True,
        "network": "none",
        "platform": "linux/amd64",
        "user": "1000:1000",
        "hostname": "loom-stage",
    }
    assert stable_json_dumps(options.to_dict())


def test_docker_run_command_redacted_projection_contract_is_stable() -> None:
    command = build_docker_run_command(
        container_options=ContainerOptions(
            image="example/runtime:latest",
            workdir="/workspace",
            mounts=({"source": "/workspace", "target": "/workspace", "mode": "rw"},),
            environment={"variables": {"TOKEN": "secret"}},
        ),
        worker_command=("python", "-m", "loom.cli.main", "stage", "run"),
    )

    document = command.to_dict()

    assert stable_json_dumps(document)
    assert DockerRunCommand.from_dict(document).to_dict() == document
    assert "secret" not in repr(command.metadata)
    assert "TOKEN=[redacted]" in repr(command.redacted_argv)
    metadata = cast(dict[str, PlainData], document["metadata"])
    assert metadata["executor"] == "docker"
    assert "secret" not in repr(metadata)


def test_docker_command_result_plain_data_contract_is_stable() -> None:
    result = DockerCommandResult(
        command="docker",
        argv=("docker", "--version"),
        redacted_argv=("docker", "--version"),
        returncode=0,
        stdout="Docker version 27.0.0",
    )

    document = result.to_dict()

    assert document["schema_version"] == DOCKER_COMMAND_RESULT_SCHEMA_VERSION
    assert stable_json_dumps(document)
    assert DockerCommandResult.from_dict(document) == result
