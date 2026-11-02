"""Guard selection and pre-payload refusal; real teardown is physical acceptance."""

import os
import signal
import subprocess
from types import SimpleNamespace

import pytest

from loom import _apptainer_guard as guard


def test_version_has_its_own_identity_without_launching(monkeypatch, capsys):
    monkeypatch.setattr(guard, "_qualify", lambda *a: pytest.fail("component launched"))
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("namespace launched"))
    assert guard.main(["--version"]) == 0
    assert capsys.readouterr().out == "loom-apptainer-guard version 1\n"


def test_exec_retains_creation_identity_and_wraps_all_runtime_processes(monkeypatch):
    monkeypatch.setenv("LOOM_APPTAINER_GUARD_RUNTIME", "/selected/apptainer")
    monkeypatch.setenv("LOOM_APPTAINER_GUARD_UNSHARE", "/selected/unshare")
    monkeypatch.setattr(guard.shutil, "which", lambda value: value)
    calls = []

    def execute(command, arguments):
        calls.append((command, arguments))
        raise RuntimeError("exec seam")

    monkeypatch.setattr(os, "execv", execute)
    payload = ["exec", "--bind", "/selected/tmp:/tmp", "image.sif", "sh", "-c", "exit 3"]
    with pytest.raises(RuntimeError, match="exec seam"):
        guard.main(payload)
    command, arguments = calls[0]
    assert command == "/selected/unshare"
    assert arguments[:8] == [
        command, "--user", "--map-current-user", "--keep-caps",
        "--mount-proc", "--pid", "--fork", "--kill-child=KILL",
    ]
    assert arguments[8:] == [
        guard.sys.executable, "-B", "-m", "loom._apptainer_guard",
        "--namespace-init", command, "/selected/apptainer", *payload,
    ]


@pytest.mark.parametrize("arguments", [[], ["build", "image.sif"], ["instance", "start"]])
def test_unsupported_commands_do_not_launch(monkeypatch, arguments):
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("namespace launched"))
    assert guard.main(arguments) == 125


def test_explicit_missing_runtime_has_no_fallback(monkeypatch):
    monkeypatch.setenv("LOOM_APPTAINER_GUARD_RUNTIME", "/missing/apptainer")
    monkeypatch.setattr(guard.shutil, "which", lambda _: None)
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("namespace launched"))
    assert guard.main(["exec", "image.sif", "true"]) == 125


def test_internal_shim_refuses_outside_owned_namespace(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 12)
    monkeypatch.setattr(guard, "_qualify", lambda *a: pytest.fail("component launched"))
    assert guard.main(["--namespace-init", "/unshare", "/runtime", "exec", "image"]) == 125


@pytest.mark.parametrize("failed", ["/unshare", "/runtime"])
def test_unqualified_component_refuses_before_payload(monkeypatch, failed):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        assert kwargs == {"timeout": 5, "environment": None, "output_limit": 4096, "text": True}
        version = "unqualified" if argv[0] == failed else guard._UNSHARE_VERSION
        return subprocess.CompletedProcess(argv, 0, version + "\n", "")

    monkeypatch.setattr(guard, "run_bounded_process", query)
    monkeypatch.setattr(subprocess, "Popen", lambda *a: pytest.fail("payload launched"))
    assert guard.main(["--namespace-init", "/unshare", "/runtime", "exec", "image"]) == 125
    assert calls[0] == ["/unshare", "--version"]


@pytest.mark.parametrize("exit_code,expected", [(0, 0), (3, 3), (-15, 143)])
def test_stable_init_preserves_status_and_forwards_signals(monkeypatch, exit_code, expected):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    monkeypatch.setattr(guard, "_qualify", lambda *a: None)
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    signals = []

    def wait():
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return exit_code

    def spawn(argv):
        assert argv == ["/runtime", "exec", "image"]
        return SimpleNamespace(wait=wait, send_signal=signals.append)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    assert guard._run_init("/unshare", "/runtime", ["exec", "image"]) == expected
    assert signals == [signal.SIGTERM]


def test_interrupted_preflight_does_not_start_payload(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    monkeypatch.setattr(guard, "_qualify", lambda *a: handlers[signal.SIGTERM](signal.SIGTERM, None))
    monkeypatch.setattr(subprocess, "Popen", lambda *a: pytest.fail("payload launched"))
    assert guard._run_init("/unshare", "/runtime", ["exec", "image"]) == 143
