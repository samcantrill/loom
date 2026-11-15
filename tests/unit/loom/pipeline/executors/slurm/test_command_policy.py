"""Explicit scheduler deadlines preserve uncertain calls and legacy identities."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import time

import pytest

from loom.pipeline.executors.slurm import FakeSlurmCommandRunner, SlurmCommandResult
from loom.pipeline.executors.slurm.commands import (
    MAX_PERSISTED_COMMAND_OUTPUT_CHARS,
    SlurmCommandPolicy,
    SubprocessSlurmCommandRunner,
)
from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState, SQLiteReadyStageSubmissions, operation_marker,
)
from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile, _request, _script


def _policy(**overrides):
    return SlurmCommandPolicy(**{
        "observation_timeout_seconds": 10,
        "submission_timeout_seconds": 60,
        "cancellation_timeout_seconds": 7,
        **overrides,
    })


@pytest.mark.parametrize("value", [True, 0, -1, "10", float("inf"), float("nan"), 10**400, 3601])
def test_invalid_policy_is_rejected_before_any_command(value, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("started a command"))
    with pytest.raises(SlurmPlanningError, match="observation_timeout_seconds"):
        SubprocessSlurmCommandRunner(command_policy={
            "observation_timeout_seconds": value,
            "submission_timeout_seconds": 60,
            "cancellation_timeout_seconds": 7,
        })


def test_command_policy_requires_complete_closed_selection():
    for value in ({}, {"submission_timeout_seconds": 60}, {**_policy().to_dict(), "extra": 1}):
        with pytest.raises(SlurmPlanningError, match="all three"):
            SubprocessSlurmCommandRunner(command_policy=value)


def test_policy_binds_every_deadline_without_changing_legacy_profile():
    legacy = _profile(FakeSlurmCommandRunner())
    explicit_none = replace(legacy, runner=FakeSlurmCommandRunner(command_policy=None))
    assert explicit_none.configuration_fingerprint == legacy.configuration_fingerprint
    selected = replace(legacy, runner=FakeSlurmCommandRunner(command_policy=_policy()))
    assert selected.configuration_fingerprint != legacy.configuration_fingerprint
    equivalent = replace(legacy, runner=FakeSlurmCommandRunner(command_policy=_policy(
        observation_timeout_seconds=10.0,
    )))
    assert equivalent.configuration_fingerprint == selected.configuration_fingerprint
    for field in ("observation_timeout_seconds", "submission_timeout_seconds", "cancellation_timeout_seconds"):
        changed = replace(legacy, runner=FakeSlurmCommandRunner(command_policy=_policy(**{field: 3})))
        assert changed.configuration_fingerprint != selected.configuration_fingerprint


def test_deadlines_reach_each_scheduler_command_and_legacy_remains_unselected(monkeypatch):
    import loom.pipeline.executors.slurm.commands as commands

    observed = []

    def bounded(argv, *, timeout, environment):
        observed.append((argv, timeout, environment))
        return subprocess.CompletedProcess(argv, 0, "17\n" if argv[0] == "sbatch" else "", "")

    monkeypatch.setattr(commands, "_run_bounded_command", bounded)
    monkeypatch.setattr(commands.shutil, "which", lambda _command: "/unused/site/command")
    runner = SubprocessSlurmCommandRunner(command_policy=_policy())
    runner.sbatch("/scratch/job.sh", environment={})
    runner.squeue(job_ids=("17",))
    runner.sacct(job_ids=("17",))
    runner.scancel(job_ids=("17",))
    runner.discover_live_operations()
    runner.discover_accounted_operations(started_after="2026-11-02T00:00:00Z")
    assert [item[1] for item in observed] == [60, 10, 10, 7, 10, 10]
    assert observed[0][2] == {}
    assert "--export=NIL" in observed[0][0]

    calls = []
    def legacy_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "18\n", "")
    monkeypatch.setattr(subprocess, "run", legacy_run)
    SubprocessSlurmCommandRunner().sbatch("/scratch/job.sh", environment={})
    assert "timeout" not in calls[0][1]
    assert calls[0][1]["env"] == {}
    assert len(observed) == 6


def _assert_child_stopped(child_pid):
    state_file = Path(f"/proc/{child_pid}/stat")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            state = state_file.read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return
        if state in {"Z", "X"}:
            return
        time.sleep(0.01)
    pytest.fail("scheduler wrapper descendant survived its command boundary")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-state evidence")
@pytest.mark.parametrize("descriptor", [1, 2])
def test_output_limit_stops_noisy_wrapper_and_descendant(tmp_path, monkeypatch, descriptor):
    # Output never closes on its own, so post-communicate checking cannot pass.
    pid_path = tmp_path / "child.pid"
    child_program = (
        "import os, time\nfrom pathlib import Path\n"
        f"while not Path({str(pid_path)!r}).exists(): time.sleep(0.01)\n"
        f"while True: os.write({descriptor}, b'x' * 4096)\n"
    )
    executable = tmp_path / "sbatch"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\nfrom pathlib import Path\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_program!r}])\n"
        f"Path({str(pid_path)!r}).write_text(str(child.pid))\nchild.wait()\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    runner = SubprocessSlurmCommandRunner(command_policy=_policy())
    start = time.monotonic()
    with pytest.raises(SlurmPlanningError, match="evidence limit"):
        runner.sbatch(tmp_path / "unused-job.sh", environment={})
    assert time.monotonic() - start < 10
    _assert_child_stopped(int(pid_path.read_text()))


@pytest.mark.parametrize("character", ["x", "é"])
def test_bounded_capture_preserves_output_at_limit_and_translates_newlines(tmp_path, monkeypatch, character):
    executable = tmp_path / "sacct"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"sys.stdout.write({character!r} * {MAX_PERSISTED_COMMAND_OUTPUT_CHARS})\n"
        "sys.stderr.buffer.write(b'first\\r\\nsecond\\rthird\\n')\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    result = SubprocessSlurmCommandRunner(command_policy=_policy()).sacct(job_ids=("17",))
    assert result.ok
    assert result.stdout == character * MAX_PERSISTED_COMMAND_OUTPUT_CHARS
    assert result.stderr == "first\nsecond\nthird\n"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-state evidence")
def test_actual_timeout_stops_wrapper_descendant_and_preserves_uncertainty(tmp_path, monkeypatch):
    # A fake local sbatch wrapper, not a scheduler allocation. Its descendant
    # inherits the pipes and ignores SIGTERM, so killing the wrapper alone hangs.
    pid_path = tmp_path / "child.pid"
    executable = tmp_path / "sbatch"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\nfrom pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        + repr("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)")
        + "])\n"
        + f"Path({str(pid_path)!r}).write_text(str(child.pid))\nchild.wait()\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    runner = SubprocessSlurmCommandRunner(command_policy=_policy(submission_timeout_seconds=3))
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        runner.sbatch(tmp_path / "unused-job.sh", environment={})
    assert time.monotonic() - start < 10
    _assert_child_stopped(int(pid_path.read_text()))


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_selected_submit_failure_reconciles_without_second_call(tmp_path, failure):
    failed = (
        SlurmCommandResult("sbatch", ("sbatch",), 1, stderr="controller communication failed")
        if failure == "exit" else subprocess.TimeoutExpired("sbatch", 60)
    )
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(command_policy=_policy(), scripted_results={
        "sbatch": [failed],
        "squeue": [SlurmCommandResult("squeue", ("squeue",), 0)],
        "sacct": [SlurmCommandResult("sacct", ("sacct",), 0, stdout=f"17|{marker}|cluster-a|\n")],
    })
    profile = replace(_profile(runner), job_private_file_provider=SlurmUserPrivateFileProvider(
        root=tmp_path / "credentials", descriptor="command-policy-test",
    ))
    request = _request(profile)
    database = tmp_path / "submissions.sqlite"
    store = SQLiteReadyStageSubmissions(database)
    script = _script(tmp_path, request)
    result = store.submit(request, profile, script)
    assert result.state is ReadyStageState.UNKNOWN
    assert result.evidence == ("slurm_submit_command_failed" if failure == "exit" else "slurm_submit_timeout")
    reopened = SQLiteReadyStageSubmissions(database, _allow_initialize=False)
    assert reopened.submit(request, profile, script) == result
    associated = reopened.reconcile(request.operation_id, profile)
    assert associated.job_id == "17"
    assert associated.state is ReadyStageState.ACCEPTED
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_selected_cancel_failure_does_not_claim_cancellation(tmp_path, failure):
    failed = (SlurmCommandResult("scancel", ("scancel",), 1)
              if failure == "exit" else subprocess.TimeoutExpired("scancel", 7))
    runner = FakeSlurmCommandRunner(command_policy=_policy(), scripted_results={"scancel": [failed]})
    profile = replace(_profile(runner), job_private_file_provider=SlurmUserPrivateFileProvider(
        root=tmp_path / "credentials", descriptor="command-policy-test",
    ))
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    submitted = store.submit(request, profile, _script(tmp_path, request))
    result = store.request_cancel(request.operation_id, profile)
    assert result.job_id == submitted.job_id
    assert result.state is ReadyStageState.ACCEPTED
    assert not result.cancel_requested
    assert result.evidence == ("slurm_cancel_unknown" if failure == "exit" else "slurm_cancel_timeout")
