"""Opt-in real container runtime acceptance tests.

These tests are skipped unless explicit environment variables are set. They are
manual site/runtime smoke hooks, not part of default validation evidence.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

from loom.pipeline.executors.apptainer import (
    ApptainerExecOptions,
    build_apptainer_exec_command,
)
from loom.pipeline.executors.containers import ContainerOptions, ContainerResourceIntent
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime.capabilities import ResourceCapability
from loom.pipeline.runtime import ResourcePolicy


pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency]

_RESOURCE_LIMIT_PROBE = (
    'i=0; while [ "$i" -lt 1000 ]; do i=$((i + 1)); done; '
    "cgroup=$(awk -F: '$1 == \"0\" {print $3; exit}' /proc/self/cgroup) || "
    "{ echo 'cannot read payload cgroup membership; use an image with awk and "
    "readable /proc/self/cgroup' >&2; exit 1; }; "
    'if [ -z "$cgroup" ]; then '
    "echo 'payload cgroup-v2 membership is missing; use a compatible "
    "unified-cgroup runtime session' >&2; exit 1; fi; "
    'cat "/sys/fs/cgroup${cgroup}/cpu.max" || '
    "{ echo 'cannot read payload cpu.max; use a session exposing payload "
    "cgroup-v2 controls' >&2; exit 1; }; "
    'cat "/sys/fs/cgroup${cgroup}/memory.max" || '
    "{ echo 'cannot read payload memory.max; use a session exposing payload "
    "cgroup-v2 controls' >&2; exit 1; }"
)


def test_real_docker_command_available() -> None:
    if os.environ.get("LOOM_RUN_DOCKER_ACCEPTANCE") != "1":
        pytest.skip("set LOOM_RUN_DOCKER_ACCEPTANCE=1 to run real Docker smoke")
    command = _required_command(os.environ.get("LOOM_DOCKER_COMMAND", "docker"))

    completed = subprocess.run(  # noqa: S603
        [command, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout(),
    )

    assert completed.returncode == 0, completed.stderr
    assert "Docker" in completed.stdout or "docker" in completed.stdout.lower()


def test_real_apptainer_or_singularity_command_available() -> None:
    if os.environ.get("LOOM_RUN_APPTAINER_ACCEPTANCE") != "1":
        pytest.skip("set LOOM_RUN_APPTAINER_ACCEPTANCE=1 to run real Apptainer smoke")
    command = _apptainer_command()

    completed = subprocess.run(  # noqa: S603
        [command, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout(),
    )

    assert completed.returncode == 0, completed.stderr
    assert command in completed.stdout.lower() or completed.stdout.strip()


def test_real_apptainer_sif_build_from_configured_definition(tmp_path: Path) -> None:
    if os.environ.get("LOOM_RUN_APPTAINER_BUILD_ACCEPTANCE") != "1":
        pytest.skip(
            "set LOOM_RUN_APPTAINER_BUILD_ACCEPTANCE=1 to run real SIF build smoke"
        )
    definition_text = os.environ.get("LOOM_APPTAINER_BUILD_DEFINITION")
    if not definition_text:
        pytest.skip("set LOOM_APPTAINER_BUILD_DEFINITION to a local definition file")
    definition = Path(definition_text).expanduser().resolve(strict=True)
    command = _apptainer_command()
    output = tmp_path / "loom-container-acceptance.sif"
    extra_flags = shlex.split(os.environ.get("LOOM_APPTAINER_BUILD_FLAGS", ""))

    completed = subprocess.run(  # noqa: S603
        [command, "build", *extra_flags, str(output), str(definition)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout(default=300),
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()


def test_real_apptainer_cpu_memory_limits_are_applied() -> None:
    """Inspect limits from a user-supplied image and compatible runtime session."""

    if os.environ.get("LOOM_RUN_APPTAINER_RESOURCE_ACCEPTANCE") != "1":
        pytest.skip(
            "set LOOM_RUN_APPTAINER_RESOURCE_ACCEPTANCE=1 to run Apptainer "
            "CPU/memory acceptance"
        )
    image = os.environ.get("LOOM_APPTAINER_RESOURCE_IMAGE")
    if not image:
        pytest.fail(
            "set LOOM_APPTAINER_RESOURCE_IMAGE to an approved local image; "
            "this test does not pull or build one"
        )
    image_path = Path(image).expanduser()
    if not image_path.is_file():
        pytest.fail("LOOM_APPTAINER_RESOURCE_IMAGE must name an existing local image")

    command = _required_apptainer_resource_command()
    resources = ContainerResourceIntent(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
        },
        capabilities={
            kind: ResourceCapability(support_level="supported")
            for kind in ("cpu", "memory")
        },
    )
    generated = build_apptainer_exec_command(
        container_options=ContainerOptions(image=str(image_path), resources=resources),
        apptainer_options=ApptainerExecOptions(command=command),
        worker_command=("sh", "-c", _RESOURCE_LIMIT_PROBE),
    )

    completed = subprocess.run(  # noqa: S603 - generated production argv.
        generated.argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout(),
    )

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) >= 2, completed.stdout
    quota, period = lines[-2].split()
    assert quota != "max", completed.stdout
    assert int(quota) / int(period) <= 2
    assert lines[-1] == "536870912"


def test_real_apptainer_scheduling_only_cpu_memory_smoke() -> None:
    """Run a bounded payload with retained intent and no direct limit flags."""

    if os.environ.get("LOOM_RUN_APPTAINER_SCHEDULING_ONLY_ACCEPTANCE") != "1":
        pytest.skip(
            "set LOOM_RUN_APPTAINER_SCHEDULING_ONLY_ACCEPTANCE=1 to run "
            "Apptainer scheduling-only CPU/memory smoke"
        )
    image = os.environ.get("LOOM_APPTAINER_RESOURCE_IMAGE")
    if not image:
        pytest.fail(
            "set LOOM_APPTAINER_RESOURCE_IMAGE to an approved local image; "
            "this test does not pull or build one"
        )
    image_path = Path(image).expanduser()
    if not image_path.is_file():
        pytest.fail("LOOM_APPTAINER_RESOURCE_IMAGE must name an existing local image")

    command = _required_apptainer_resource_command()
    resources = ContainerResourceIntent(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
        },
        capabilities={
            kind: ResourceCapability(support_level="supported")
            for kind in ("cpu", "memory")
        },
    )
    generated = build_apptainer_exec_command(
        container_options=ContainerOptions(image=str(image_path), resources=resources),
        apptainer_options=ApptainerExecOptions(command=command),
        worker_command=("sh", "-c", "printf 'scheduling-only\\n'"),
        resource_policy=ResourcePolicy(enforce=[]),
    )

    assert "--cpus" not in generated.argv
    assert "--memory" not in generated.argv
    assert (
        generated.metadata["apptainer_options"]
        == ApptainerExecOptions(command=command).to_dict()
    )
    completed = subprocess.run(  # noqa: S603 - generated production argv.
        generated.argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout(),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "scheduling-only"


def _apptainer_command() -> str:
    configured = os.environ.get("LOOM_APPTAINER_COMMAND")
    if configured:
        return _required_command(configured)
    for candidate in ("apptainer", "singularity"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    pytest.skip("neither apptainer nor singularity is available on PATH")


def _required_apptainer_resource_command() -> str:
    configured = os.environ.get("LOOM_APPTAINER_COMMAND")
    if configured:
        resolved = shutil.which(configured)
        if resolved is not None:
            return resolved
        pytest.fail("LOOM_APPTAINER_COMMAND is not available on PATH")
    for candidate in ("apptainer", "singularity"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    pytest.fail(
        "neither apptainer nor singularity is available on PATH; use a compatible "
        "runtime session with delegated cgroups"
    )


def _required_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        pytest.skip(f"{command} is not available on PATH")
    return resolved


def _timeout(*, default: float = 30) -> float:
    return float(os.environ.get("LOOM_CONTAINER_ACCEPTANCE_TIMEOUT", str(default)))
