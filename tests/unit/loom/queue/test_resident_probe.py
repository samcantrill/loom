from __future__ import annotations

import errno
import os
from pathlib import Path
import sys
import tempfile
from time import monotonic, sleep

import pytest

from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._resident_probe import run_resident_probe


pytestmark = pytest.mark.unit


def test_probe_reports_scratch_cleanup_failure_after_containing_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleanup = tempfile.TemporaryDirectory.cleanup

    def fail_cleanup(directory: tempfile.TemporaryDirectory[str]) -> None:
        cleanup(directory)
        raise OSError("private scratch detail")

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", fail_cleanup)
    result = run_resident_probe(
        _profile(tmp_path), "print('{}')", {}, timeout_seconds=2
    )
    assert result.contained
    assert result.payload is None
    assert result.failure == "resident probe scratch creation or cleanup failed"


def _profile(tmp_path: Path, **environment: str) -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=tmp_path,
        python_executable=Path(sys.executable),
        descriptor={"profile_id": "probe"},
        environment=environment,
    )


def test_probe_uses_worker_environment_and_private_scratch(tmp_path: Path) -> None:
    result = run_resident_probe(
        _profile(tmp_path, CUSTOM="present", CUDA_VISIBLE_DEVICES="ambient"),
        "import json, os; print(json.dumps({'custom': os.environ['CUSTOM'], 'gpu': os.environ['CUDA_VISIBLE_DEVICES'], 'scratch': os.environ['TMPDIR'], 'cache': os.environ['XDG_CACHE_HOME'], 'config': os.environ['XDG_CONFIG_HOME'], 'bytecode': os.environ['PYTHONDONTWRITEBYTECODE']}))",
        {},
        timeout_seconds=2,
    )

    assert result.failure is None
    assert result.payload is not None
    assert result.payload["custom"] == "present"
    assert result.payload["gpu"] == ""
    assert result.payload["bytecode"] == "1"
    assert isinstance(result.payload["scratch"], str)
    assert result.payload["cache"] == result.payload["scratch"]
    assert result.payload["config"] == result.payload["scratch"]
    assert not Path(result.payload["scratch"]).exists()


def test_probe_reports_non_python_executable_without_leaking_output(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "not-python"
    executable.write_text(
        "#!/bin/sh\necho private-detail >&2\nexit 7\n", encoding="utf-8"
    )
    executable.chmod(0o700)
    profile = ResidentWorkerLaunchProfile(
        project_root=tmp_path,
        python_executable=executable,
        descriptor={"profile_id": "probe"},
    )

    result = run_resident_probe(profile, "pass", {}, timeout_seconds=2)

    assert result == type(result)(None, "resident probe failed", True)


def test_probe_bounds_timeout_and_combined_output(tmp_path: Path) -> None:
    timeout = run_resident_probe(
        _profile(tmp_path), "import time; time.sleep(60)", {}, timeout_seconds=0.1
    )
    oversized = run_resident_probe(
        _profile(tmp_path), "print('x' * 65537)", {}, timeout_seconds=2
    )

    assert timeout.failure == "resident probe timed out"
    assert timeout.contained
    assert oversized.failure == "resident probe output exceeded its bound"
    assert oversized.contained


def test_probe_contains_descendant_holding_stdout_pipe(tmp_path: Path) -> None:
    child_pid = tmp_path / "child.pid"
    script = (
        "import json, os, subprocess, sys; "
        "os.set_inheritable(sys.stdout.fileno(), True); "
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], close_fds=False); Path = __import__('pathlib').Path; Path({str(child_pid)!r}).write_text(str(child.pid)); "
        "print(json.dumps({'ok': True}))"
    )
    started = monotonic()
    result = run_resident_probe(_profile(tmp_path), script, {}, timeout_seconds=2)

    assert result.payload == {"ok": True}
    assert result.contained
    assert monotonic() - started < 3
    pid = int(child_pid.read_text(encoding="utf-8"))
    deadline = monotonic() + 1
    while True:
        try:
            os.kill(pid, 0)
        except OSError as exc:
            assert exc.errno == errno.ESRCH
            break
        if monotonic() >= deadline:
            raise AssertionError("resident probe left a descendant alive")
        sleep(0.01)


def test_probe_reads_complete_bounded_output_after_root_exit(tmp_path: Path) -> None:
    result = run_resident_probe(
        _profile(tmp_path),
        "import json; print(json.dumps({'value': 'x' * 32000}))",
        {},
        timeout_seconds=2,
    )
    assert result.failure is None and result.contained
    assert result.payload == {"value": "x" * 32000}


def test_probe_does_not_inherit_daemon_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOM_DAEMON_SECRET", "must-not-be-inherited")
    result = run_resident_probe(
        _profile(tmp_path),
        "import json, os; print(json.dumps({'present': 'LOOM_DAEMON_SECRET' in os.environ, 'gpu': os.environ['CUDA_VISIBLE_DEVICES']}))",
        {},
        timeout_seconds=2,
        device_environment={"CUDA_VISIBLE_DEVICES": "GPU-owned"},
    )
    assert result.payload == {"present": False, "gpu": "GPU-owned"}
    assert result.contained
