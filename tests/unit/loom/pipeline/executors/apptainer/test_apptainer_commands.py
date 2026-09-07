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
from loom.pipeline.executors.containers import ContainerOptions, ContainerResourceIntent
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime.capabilities import ResourceCapability
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
    with pytest.raises(ApptainerOptionError, match="cpu_memory_enforcement"):
        ApptainerExecOptions.from_dict({"cpu_memory_enforcement": "advisory"})
    with pytest.raises(ApptainerOptionError, match="cpu_memory_enforcement"):
        ApptainerExecOptions.from_dict({"cpu_memory_enforcement": ["runtime"]})
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


def test_build_apptainer_exec_command_maps_exact_cpu_and_memory_before_image() -> None:
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(
            image="analysis.sif",
            resources=_resource_intent(
                cpu=ResourceEntry(kind="cpu", amount=2),
                memory=ResourceEntry(kind="memory", amount=512, unit="MiB"),
            ),
        ),
        worker_command=("python", "-V"),
    )

    assert command.argv == (
        "apptainer",
        "exec",
        "--cleanenv",
        "--cpus",
        "2",
        "--memory",
        "536870912",
        "analysis.sif",
        "python",
        "-V",
    )
    assert command.redacted_argv == command.argv


def test_build_apptainer_exec_command_converts_exact_fractional_memory_units() -> None:
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(
            image="analysis.sif",
            resources=_resource_intent(
                memory=ResourceEntry(kind="memory", amount=0.5, unit="MiB"),
            ),
        ),
        worker_command=("python", "-V"),
    )

    assert command.argv[command.argv.index("--memory") + 1] == "524288"


def test_scheduling_only_omits_limits_but_retains_and_validates_intent() -> None:
    resources = _resource_intent(
        cpu=ResourceEntry(kind="cpu", amount=2),
        memory=ResourceEntry(kind="memory", amount=512, unit="MiB"),
    )
    options = ApptainerExecOptions(cpu_memory_enforcement="scheduling_only")
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(image="analysis.sif", resources=resources),
        apptainer_options=options,
        worker_command=("python", "-V"),
    )

    assert "--cpus" not in command.argv
    assert "--memory" not in command.argv
    assert command.metadata["apptainer_options"] == options.to_dict()
    assert command.metadata["container"] == ContainerOptions(
        image="analysis.sif", resources=resources
    ).to_redacted_metadata()
    with pytest.raises(ApptainerOptionError, match="positive integer"):
        build_apptainer_exec_command(
            container_options=ContainerOptions(
                image="analysis.sif",
                resources=_resource_intent(cpu=ResourceEntry(kind="cpu", amount=0)),
            ),
            apptainer_options=options,
            worker_command=("python", "-V"),
        )


@pytest.mark.parametrize(
    ("entry", "match"),
    (
        (ResourceEntry(kind="cpu", amount=0), "positive integer"),
        (ResourceEntry(kind="memory", amount=0.5, unit="B"), "whole number of bytes"),
        (
            ResourceEntry(kind="memory", amount=1 << 63, unit="B"),
            "unrepresentable",
        ),
        (
            ResourceEntry(kind="memory", amount=(1 << 53) + 1, unit="B"),
            "not exactly representable",
        ),
    ),
)
def test_build_apptainer_exec_command_revalidates_bypassed_resource_intent(
    entry: ResourceEntry,
    match: str,
) -> None:
    with pytest.raises(ApptainerOptionError, match=match):
        build_apptainer_exec_command(
            container_options=ContainerOptions(
                image="analysis.sif",
                resources=_resource_intent(**{entry.kind: entry}),
            ),
            worker_command=("python", "-V"),
        )


def test_build_apptainer_exec_command_accepts_exact_large_float64_byte_value() -> None:
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(
            image="analysis.sif",
            resources=_resource_intent(
                memory=ResourceEntry(kind="memory", amount=(1 << 53) + 2, unit="B")
            ),
        ),
        worker_command=("python", "-V"),
    )

    assert command.argv[command.argv.index("--memory") + 1] == str((1 << 53) + 2)


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


def _resource_intent(
    **entries: ResourceEntry,
) -> ContainerResourceIntent:
    return ContainerResourceIntent(
        entries=entries,
        capabilities={
            kind: ResourceCapability(support_level="supported")
            for kind in entries
        },
    )
