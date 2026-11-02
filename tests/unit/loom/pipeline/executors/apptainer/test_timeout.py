"""Admission and rare-failure checks; actual descendant proof lives in acceptance."""

import subprocess
import os
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


@pytest.fixture
def pidfd_capable_host(monkeypatch):
    # Version-parser cases are independent of the test interpreter's build flags.
    monkeypatch.setattr(
        "loom._pidfd.require_pidfd_support", lambda: None
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
        "apptainer version 1.5.3\n",
        "loom-apptainer-guard version 2\n",
        "singularity-ce version 4.1.2\n",
        "singularity version 3.10.5\n",
    ],
)
def test_unverified_runtime_rejected_before_payload(
    monkeypatch: pytest.MonkeyPatch,
    output: str,
    pidfd_capable_host,
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
        "loom-apptainer-guard version 1\n",
    ],
)
def test_qualified_runtime_versions_admitted(
    monkeypatch: pytest.MonkeyPatch,
    output: str,
    pidfd_capable_host,
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


def test_host_environment_reaches_version_launcher_and_timeout_files(tmp_path, monkeypatch, pidfd_capable_host):
    import tempfile
    from types import SimpleNamespace
    import loom.pipeline.executors.apptainer._timeout as timed

    environment = {"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path), "PROBE_SELECTED": "yes"}
    calls = []

    def version(argv, **kwargs):
        assert kwargs["env"] == environment
        calls.append("version")
        return subprocess.CompletedProcess(argv, 0, "singularity-ce version 4.1.1\n", "")

    real_temporary = tempfile.TemporaryFile

    def temporary(**kwargs):
        assert kwargs["dir"] == str(tmp_path)
        calls.append("temporary")
        return real_temporary(**kwargs)

    def launch(argv, **kwargs):
        assert kwargs["env"] == environment
        assert argv[:4] == ["/usr/bin/true", "exec", "--pid", "--no-init=false"]
        kwargs["stdout"].write(b"captured")
        calls.append("launch")
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(subprocess, "run", version)
    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(tempfile, "TemporaryFile", temporary)
    monkeypatch.setattr(timed, "_root_status", lambda _: 0)
    monkeypatch.setattr(timed, "_capture_init", lambda *a: None)
    monkeypatch.setattr(timed, "_settle", lambda *a: [])
    command = ApptainerExecCommand.from_argv(("/usr/bin/true", "exec", "image.sif", "worker"))
    result = SubprocessApptainerExecRunner().run(command, timeout_seconds=2, host_environment=environment)
    assert result.ok and result.stdout == "captured"
    assert calls == ["version", "temporary", "temporary", "launch"]


def test_unavailable_kernel_pidfds_refuse_before_runtime_query(monkeypatch):
    from loom import _pidfd

    def unavailable():
        raise OSError("pidfd operation unavailable")

    monkeypatch.setattr(_pidfd, "require_pidfd_support", unavailable)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("runtime query started"))
    with pytest.raises(UnsupportedTimeoutError, match="working Linux pidfd"):
        _require_runtime("singularity", monotonic() + 2)


def test_fake_runtime_selects_host_temporary_root(tmp_path, monkeypatch):
    from pathlib import Path
    from examples.execution.containers.apptainer_fixture import fake_apptainer

    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with fake_apptainer() as binding:
        root = Path(binding["options"]["command"]).parent
        assert root.parent == tmp_path
        assert root.stat().st_mode & 0o777 == 0o700
    assert not root.exists()
