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


pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency]


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
        pytest.skip(
            "set LOOM_RUN_APPTAINER_ACCEPTANCE=1 to run real Apptainer smoke"
        )
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


def _apptainer_command() -> str:
    configured = os.environ.get("LOOM_APPTAINER_COMMAND")
    if configured:
        return _required_command(configured)
    for candidate in ("apptainer", "singularity"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    pytest.skip("neither apptainer nor singularity is available on PATH")


def _required_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        pytest.skip(f"{command} is not available on PATH")
    return resolved


def _timeout(*, default: float = 30) -> float:
    return float(os.environ.get("LOOM_CONTAINER_ACCEPTANCE_TIMEOUT", str(default)))
