from __future__ import annotations

from typing import cast

import errno
import os
from pathlib import Path
import shutil
import sys
from time import monotonic, sleep

import pytest

from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._resident_probe import run_resident_probe


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("selected_mount", [False, True])
def test_software_container_probe_does_not_infer_gpu_request(tmp_path, monkeypatch, selected_mount):
    from dataclasses import replace
    import json
    from types import SimpleNamespace

    from loom.pipeline.executors.apptainer.commands import SubprocessApptainerExecRunner

    image = tmp_path / "installed.sif"
    image.write_bytes(b"command-only fixture")
    project = tmp_path / "project"
    project.mkdir()
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    selected = tmp_path / "selected"
    selected.mkdir()
    monkeypatch.setenv("TMPDIR", str(ambient))
    expected_root = selected if selected_mount else ambient
    profile = replace(
        _profile(project, TMPDIR="/tmp"),
        preparation_shared_roots={"optional": tmp_path / "missing-snapshots"},
        container={
            "kind": "apptainer",
            "container": {
                "image": {"reference": str(image)},
                "mounts": [{"source": str(selected), "target": "/tmp", "mode": "rw"}] if selected_mount else [],
            },
            "options": {"command": sys.executable},
            "python_executable": "/image/bin/python",
            "daemon_endpoint": None,
        },
        temporary_mounts=("/tmp",) if selected_mount else (),
    )
    calls = []

    def run(_runner, command, **kwargs):
        calls.append(command)
        assert "--nv" not in command.argv
        assert all(str(tmp_path / "missing-snapshots") not in item for item in command.argv)
        index = command.argv.index(str(image))
        output = Path(command.argv[index + 4])
        scratch = output.parents[2]
        assert scratch.parent == expected_root
        assert scratch.stat().st_mode & 0o777 == 0o700
        for name in ("TMPDIR", "TMP", "TEMP", "APPTAINER_TMPDIR", "SINGULARITY_TMPDIR"):
            assert kwargs["host_environment"][name] == str(scratch)
        output.write_text(json.dumps({"ok": True}))
        return SimpleNamespace(error=None, returncode=0, timed_out=False)

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-ambient")
    monkeypatch.setattr(SubprocessApptainerExecRunner, "run", run)
    result = run_resident_probe(profile, "print('{}')", {}, timeout_seconds=2)
    assert len(calls) == 1 and result.payload == {"ok": True}
    assert result.contained and result.failure is None
    assert list(expected_root.iterdir()) == []


def test_probe_reports_scratch_cleanup_failure_after_containing_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleanup = shutil.rmtree

    def fail_cleanup(directory) -> None:
        cleanup(directory)
        raise OSError("private scratch detail")

    monkeypatch.setattr(shutil, "rmtree", fail_cleanup)
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


@pytest.mark.parametrize("selection", ["profile", "ambient"])
def test_native_probe_selects_host_scratch_without_changing_parent(tmp_path, monkeypatch, selection):
    base = tmp_path / "scratch"
    base.mkdir()
    environment = {"TMPDIR": str(base)} if selection == "profile" else {}
    monkeypatch.setenv("TMPDIR", str(tmp_path if selection == "profile" else base))
    before = os.environ["TMPDIR"]
    result = run_resident_probe(
        _profile(tmp_path, **environment),
        "import json,os; print(json.dumps({key:os.environ[key] for key in ('TMPDIR','TMP','TEMP')}))",
        {}, timeout_seconds=2,
    )
    assert result.contained and result.failure is None
    assert result.payload is not None
    assert len(set(result.payload.values())) == 1
    assert Path(cast(str, result.payload["TMPDIR"])).parent == base
    assert list(base.iterdir()) == []
    assert os.environ["TMPDIR"] == before


def test_invalid_explicit_probe_root_refuses_before_process_creation(tmp_path, monkeypatch):
    import loom.queue._resident_probe as probe

    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid scratch launched a process"))
    result = run_resident_probe(_profile(tmp_path, TMPDIR=str(tmp_path / "absent")), "print('{}')", {}, timeout_seconds=2)
    assert result.contained and result.failure == "resident probe scratch creation failed"


def test_native_probe_retains_scratch_when_containment_is_unknown(tmp_path, monkeypatch):
    import loom.queue._resident_probe as probe

    base = tmp_path / "scratch"
    base.mkdir()

    def unresolved(profile, script, request, timeout, devices, scratch):
        Path(scratch, "still-owned").write_text("probe cleanup unresolved")
        return probe.ResidentProbeResult(None, "resident probe cleanup failed", False)

    monkeypatch.setattr(probe, "_run_probe_process", unresolved)
    result = run_resident_probe(_profile(tmp_path, TMPDIR=str(base)), "print('{}')", {}, timeout_seconds=2)
    assert not result.contained
    retained = list(base.iterdir())
    assert len(retained) == 1 and (retained[0] / "still-owned").is_file()


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


@pytest.mark.parametrize("timeout", (0, -1, True, 120.1, float("inf"), float("nan")))
def test_probe_rejects_invalid_timeout_before_launch(
    tmp_path: Path, timeout: float
) -> None:
    with pytest.raises(ValueError, match="resident probe timeout is invalid"):
        run_resident_probe(
            _profile(tmp_path), "print('{}')", {}, timeout_seconds=timeout
        )


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
