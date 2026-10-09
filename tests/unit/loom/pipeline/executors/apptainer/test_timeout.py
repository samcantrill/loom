"""Admission and rare-failure checks; actual descendant proof lives in acceptance."""

import subprocess
from time import monotonic

import pytest

from loom.pipeline.executors.apptainer import (
    ApptainerExecCommand,
    SubprocessApptainerExecRunner,
)
from loom.pipeline.executors.apptainer._timeout import (
    UnsupportedTimeoutError,
    _require_runtime,
    namespace_argv,
)


def test_namespace_options_do_not_reinterpret_values_or_payload_options() -> None:
    argv = (
        "singularity",
        "exec",
        "--pwd",
        "--pid",
        "--env",
        "TOKEN=secret",
        "image.sif",
        "sh",
        "--no-init",
    )
    projected = namespace_argv(argv)
    assert projected == ("singularity", "exec", "--pid", "--no-init=false", *argv[2:])
    assert namespace_argv(projected) == projected


@pytest.mark.parametrize(
    "argv",
    [
        ("singularity", "instance", "start", "image.sif", "name"),
        ("singularity", "exec", "--no-init", "image.sif", "sh"),
        ("singularity", "exec", "instance://name", "sh"),
    ],
)
def test_unsupported_modes_fail_before_launch(argv: tuple[str, ...]) -> None:
    with pytest.raises(UnsupportedTimeoutError):
        namespace_argv(argv)


@pytest.mark.parametrize(
    "output",
    [
        "apptainer version 1.4.0\n",
        "singularity-ce version 4.1.2\n",
        "singularity version 3.10.5\n",
    ],
)
def test_unverified_runtime_rejected_before_payload(
    monkeypatch: pytest.MonkeyPatch,
    output: str,
) -> None:
    calls: list[object] = []

    def version(argv, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(subprocess, "run", version)
    with pytest.raises(UnsupportedTimeoutError, match="SingularityCE 3.10.4"):
        _require_runtime("runtime", monotonic() + 1)
    assert calls == [["runtime", "--version"]]


@pytest.mark.parametrize(
    "output",
    [
        "singularity version 3.10.4\n",
        "singularity-ce version 3.10.4-focal\n",
        "singularity-ce version 4.1.1\n",
    ],
)
def test_qualified_runtime_versions_admitted(
    monkeypatch: pytest.MonkeyPatch,
    output: str,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, output, ""),
    )
    _require_runtime("runtime", monotonic() + 1)


def test_no_timeout_preserves_unrestricted_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def run(argv, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append((argv, kwargs["timeout"]))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(SubprocessApptainerExecRunner, "require", lambda *args: None)
    command = ApptainerExecCommand.from_argv(
        ("custom-runtime", "exec", "image.sif", "sh")
    )
    result = SubprocessApptainerExecRunner().run(command)
    assert result.returncode == 0
    assert calls == [(list(command.argv), None)]
    assert not result.timed_out
