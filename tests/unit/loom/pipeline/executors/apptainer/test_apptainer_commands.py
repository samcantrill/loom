"""Unit tests for Apptainer exec command construction and runners."""

from __future__ import annotations

import subprocess
import sys
from typing import cast

import pytest

from loom.pipeline.executors.apptainer import (
    ApptainerExecCommand,
    ApptainerExecOptions,
    ApptainerOptionError,
    FakeApptainerExecRunner,
    SubprocessApptainerExecRunner,
    build_apptainer_exec_command,
    build_apptainer_version_command,
)
from loom.pipeline.executors.apptainer.build import (
    ApptainerCommandUnavailableError,
)
from loom.pipeline.executors.containers import ContainerOptions
from loom.serialization import stable_json_dumps


pytestmark = pytest.mark.unit


def test_build_apptainer_exec_command_is_deterministic_and_redacted() -> None:
    command = build_apptainer_exec_command(
        container_options=_container_options(),
        apptainer_options=ApptainerExecOptions(
            command="singularity",
            nv=True,
            fakeroot=True,
            no_home=True,
        ),
        worker_command=("python", "-c", "print('ok')"),
        host_environment={"HOME": "/home/test"},
    )

    assert command.argv == (
        "singularity",
        "exec",
        "--cleanenv",
        "--nv",
        "--fakeroot",
        "--no-home",
        "--pwd",
        "/workspace",
        "--bind",
        "/readonly:/readonly:ro",
        "--bind",
        "/workspace:/workspace:rw",
        "--env",
        "MODE=test",
        "--env",
        "TOKEN=secret",
        "--env",
        "HOME=/home/test",
        "analysis.sif",
        "python",
        "-c",
        "print('ok')",
    )
    assert command.redacted_argv == (
        "singularity",
        "exec",
        "--cleanenv",
        "--nv",
        "--fakeroot",
        "--no-home",
        "--pwd",
        "/workspace",
        "--bind",
        "/readonly:/readonly:ro",
        "--bind",
        "/workspace:/workspace:rw",
        "--env",
        "MODE=[redacted]",
        "--env",
        "TOKEN=[redacted]",
        "--env",
        "HOME=[redacted]",
        "analysis.sif",
        "python",
        "-c",
        "print('ok')",
    )
    assert stable_json_dumps(command.to_dict())
    assert "secret" not in repr(command.metadata)
    assert "TOKEN=[redacted]" in repr(command.metadata)
    assert command.metadata["command"] == "singularity"


def test_apptainer_exec_options_and_inputs_reject_invalid_shapes() -> None:
    with pytest.raises(ApptainerOptionError, match="unknown field"):
        ApptainerExecOptions.from_dict({"contain": True})
    with pytest.raises(ApptainerOptionError, match="cannot both be true"):
        ApptainerExecOptions(nv=True, rocm=True)
    with pytest.raises(ApptainerOptionError, match="worker_command"):
        build_apptainer_exec_command(
            container_options=_container_options(),
            worker_command=(),
        )
    with pytest.raises(ApptainerOptionError, match="invalid environment variable name"):
        build_apptainer_exec_command(
            container_options=ContainerOptions(
                image="analysis.sif",
                environment={"variables": {"BAD-NAME": "value"}},
            ),
            worker_command=("python", "-V"),
        )
    with pytest.raises(ApptainerOptionError, match="required host environment variable"):
        build_apptainer_exec_command(
            container_options=ContainerOptions(
                image="analysis.sif",
                environment={"required_host_variables": ["TOKEN"]},
            ),
            worker_command=("python", "-V"),
            host_environment={},
        )


def test_fake_runner_records_calls_and_scripts_version_results() -> None:
    runner = FakeApptainerExecRunner()

    result = runner.version({"command": "singularity"})

    assert result.ok is True
    assert runner.calls[0].argv == ("singularity", "--version")
    with pytest.raises(ApptainerCommandUnavailableError):
        FakeApptainerExecRunner(unavailable_commands=("apptainer",)).version()


def test_runner_exception_mapping_redacts_argv_values_from_error_text() -> None:
    command = ApptainerExecCommand(
        argv=("apptainer", "exec", "--env", "TOKEN=secret", "analysis.sif"),
        redacted_argv=(
            "apptainer",
            "exec",
            "--env",
            "TOKEN=[redacted]",
            "analysis.sif",
        ),
    )
    runner = FakeApptainerExecRunner(scripted_results=(RuntimeError("TOKEN=secret"),))

    result = runner.run(command)

    assert result.returncode == 127
    assert "secret" not in cast(str, result.error)
    assert "TOKEN=[redacted]" in cast(str, result.error)


def test_runner_exception_mapping_preserves_timeout_facts() -> None:
    command = ApptainerExecCommand.from_argv(("apptainer", "exec", "analysis.sif"))
    runner = FakeApptainerExecRunner(
        scripted_results=(
            subprocess.TimeoutExpired(
                cmd=("apptainer", "exec"),
                timeout=5,
                output="partial",
                stderr=b"slow",
            ),
        )
    )

    result = runner.run(command, timeout_seconds=5)

    assert result.timed_out is True
    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.stderr == "slow"
    assert result.timeout_seconds == 5


def test_subprocess_runner_uses_shell_free_argv() -> None:
    runner = SubprocessApptainerExecRunner()
    command = ApptainerExecCommand.from_argv(
        (sys.executable, "-c", "print('ok')"),
        metadata={"operation": "unit-test"},
    )

    result = runner.run(command)

    assert result.ok is True
    assert result.stdout.strip() == "ok"
    assert result.argv == (sys.executable, "-c", "print('ok')")


def test_version_command_is_cheap() -> None:
    command = build_apptainer_version_command({"command": "singularity"})

    assert command.argv == ("singularity", "--version")
    assert command.metadata["operation"] == "version"


def _container_options() -> ContainerOptions:
    return ContainerOptions(
        image="analysis.sif",
        workdir="/workspace",
        mounts=(
            {"source": "/workspace", "target": "/workspace", "mode": "rw"},
            {"source": "/readonly", "target": "/readonly", "mode": "ro"},
        ),
        environment={
            "variables": {"TOKEN": "secret", "MODE": "test"},
            "required_host_variables": ["HOME"],
        },
    )
