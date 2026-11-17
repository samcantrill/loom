"""Result replay and independent scheduler retries under the selected policy."""

from dataclasses import replace
import subprocess

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner, SlurmCommandPolicy, SlurmCommandResult
from loom.pipeline.executors.slurm.history import SlurmHistoryPolicy, operation_job_name
from loom.pipeline.executors.slurm.ready_stage import ReadyStageState, SlurmContainmentHelper, SlurmContainmentReceipt
from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
from loom.pipeline.status import StageStatus
from loom.queue._agent_slurm import AgentSlurmJobs
from loom.queue._remote_stage_execution import _RemoteExecutionReport
from loom.queue._slurm_observation import SlurmObservationPolicy
from loom.queue._slurm_result_transport import SharedSlurmResult
from loom.queue.errors import QueueConfigError
from tests.unit.loom.queue.test_agent_slurm import _profile, _task
from tests.unit.loom.queue.test_agent_slurm_storage import drive_until


def _row():
    return SlurmCommandResult("sacct", ("sacct",), 0, stdout=(
        f"17|{operation_job_name('operation-1')}|1000|cluster-a|2026-11-02T00:00:00|42|sFixture|RUNNING\n"
    ))


def _owner(tmp_path, monkeypatch, *, accounting=None, submission=None, cancellation=None):
    import loom.queue._agent_slurm as agent_module
    import loom.pipeline.executors.slurm.ready_stage as ready_module

    clock = [0.0]
    monkeypatch.setattr(agent_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ready_module, "utc_timestamp", lambda: "2026-11-02T00:00:00Z")
    runner = FakeSlurmCommandRunner(
        starting_job_id=17, command_policy=SlurmCommandPolicy(10, 60, 10),
        scripted_results={
            "sacct": accounting if accounting is not None else [_row()] * 30,
            "sbatch": submission or [], "scancel": cancellation or [],
        },
    )
    profile = replace(
        _profile(runner, tmp_path, retention_bytes=1024**3),
        cluster="cluster-a", accounting_history=SlurmHistoryPolicy(1000),
        poll_interval_seconds=30,
        job_private_file_provider=SlurmUserPrivateFileProvider(
            root=tmp_path / "credentials", descriptor="observation-test",
        ),
        containment_helper=SlurmContainmentHelper("fixture", ("/unused/helper",)),
    )
    AgentSlurmJobs.initialize(tmp_path)
    owner = AgentSlurmJobs(tmp_path, (profile,), observation_policy=SlurmObservationPolicy(300))
    return owner, _task(profile), clock, runner, profile


def _ack(value):
    return {"sequence": value["sequence"], "cancel_requested": False}


@pytest.mark.parametrize("diagnostic,expected", [
    ("terminal_controller_record_retained", [0, 30, 60, 90]),
    (None, [0, 30, 90]),
    ("unrecognized", [0, 30, 90]),
])
def test_containment_pending_keeps_normal_interval(tmp_path, monkeypatch, diagnostic, expected):
    import loom.queue._agent_slurm as agent_module

    owner, _task_value, clock, _runner, profile = _owner(tmp_path, monkeypatch)
    probes = []

    def probe(*_args):
        probes.append(clock[0])
        return SlurmContainmentReceipt("UNKNOWN", diagnostic_code=diagnostic)

    monkeypatch.setattr(agent_module, "resolve_slurm_containment", probe)
    for now in (0, 29, 30, 59, 60, 89, 90):
        clock[0] = now
        assert not owner._containment(profile, "operation-1", {}).contained
    assert probes == expected


def _queries(runner):
    return len([call for call in runner.calls if call[0] in {"squeue", "sacct"}])


def _publish_result(task, profile):
    identity = {
        "coordinator_id": "coordinator", "assignment": task["assignment"],
        "fence": "fence", "incarnation": "bootstrap",
    }
    report = _RemoteExecutionReport(
        "assignment-1", "train", 1, StageStatus.SUCCEEDED,
        "2026-11-02T00:00:00Z", "2026-11-02T00:00:01Z", "local",
        schema_version=6, executor_metadata={}, process_created=True,
    )
    transport = SharedSlurmResult(profile.result_storage, "assignment-1")
    transport.publish(identity, report, lambda *_args: (b"", True))
    return identity, transport


@pytest.mark.parametrize("query_due", [False, True])
def test_retained_result_and_failing_observation_progress_independently(tmp_path, monkeypatch, query_due):
    owner, task, clock, runner, profile = _owner(
        tmp_path, monkeypatch, accounting=[subprocess.TimeoutExpired("sacct", 10)] * 3,
    )
    owner.step(task, _ack)
    assert _queries(runner) == 1
    identity, transport = _publish_result(task, profile)
    result_calls = []
    original = runner.discover_named_operation
    def observe(**selection):
        return original(**selection)
    monkeypatch.setattr(runner, "discover_named_operation", observe)
    def acknowledge(value):
        if "result_operation" in value:
            result_calls.append(value["result_operation"])
            return {"acknowledged": True}
        return _ack(value)
    clock[0] = 30 if query_due else 1
    owner.step({**task, "result_identity": identity}, acknowledge, allow_submission=False)
    drive_until(lambda: owner.step({**task, "result_identity": identity}, acknowledge, allow_submission=False),
                lambda: not transport.path.exists())
    assert result_calls == ["report", "commit"]
    assert _queries(runner) == (2 if query_due else 1)
    assert owner.has_retained_work(), "result delivery is not containment"
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


def test_observation_backoff_resets_on_healthy_empty_history(tmp_path, monkeypatch):
    timeout = subprocess.TimeoutExpired("sacct", 10)
    owner, task, clock, runner, _profile_value = _owner(
        tmp_path, monkeypatch, accounting=[timeout, timeout, SlurmCommandResult("sacct", ("sacct",), 0), timeout, _row()],
    )
    owner.step(task, _ack)
    for now, expected in ((29, 1), (30, 2), (89, 2), (90, 3), (119, 3), (120, 4), (149, 4), (150, 5)):
        clock[0] = now
        owner.step(task, _ack)
        assert _queries(runner) == expected
        if now == 90:
            assert owner.journal.read("operation-1").evidence == "slurm_history_not_found"
    identity = owner.journal.read("operation-1").accounting_identity
    assert identity is not None and identity.job_id == "17" and identity.sluid == "sFixture"


def test_cancel_retries_are_independent_from_normal_observation(tmp_path, monkeypatch):
    import loom.queue._agent_slurm as agent_module
    failed = SlurmCommandResult("scancel", ("scancel",), 1)
    owner, task, clock, runner, _profile_value = _owner(
        tmp_path, monkeypatch, accounting=[subprocess.TimeoutExpired("sacct", 10)] + [_row()] * 20,
        cancellation=[failed, failed],
    )
    cleanup_times = []
    def cleanup(*_args):
        cleanup_times.append(clock[0])
        return SlurmContainmentReceipt("UNKNOWN")
    monkeypatch.setattr(agent_module, "resolve_slurm_containment", cleanup)
    owner.step(task, _ack)
    cancelled = {**task, "cancel_requested": True, "containment_request": {}}
    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": True}
    for now, expected in ((1, 1), (2, 1), (30, 1), (31, 2), (32, 2), (61, 2), (90, 2), (91, 3), (92, 3), (121, 3)):
        clock[0] = now
        owner.step(cancelled, acknowledge)
        assert sum(call[0] == "scancel" for call in runner.calls) == expected
    assert cleanup_times == [1, 31, 91]
    assert owner.journal.read("operation-1").cancel_requested
    assert owner.has_retained_work()
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


def test_empty_cancellation_query_resets_observation_backoff_independently(tmp_path, monkeypatch):
    import loom.queue._agent_slurm as agent_module
    empty = SlurmCommandResult("sacct", ("sacct",), 0)
    owner, task, clock, runner, _profile_value = _owner(
        tmp_path, monkeypatch,
        accounting=[subprocess.TimeoutExpired("sacct", 10), empty, empty, _row(), _row()],
    )
    monkeypatch.setattr(agent_module, "resolve_slurm_containment", lambda *_args: SlurmContainmentReceipt("UNKNOWN"))
    owner.step(task, _ack)
    cancelled = {**task, "cancel_requested": True, "containment_request": {}}
    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": True}
    for now, expected in ((1, 2), (2, 2), (31, 3), (60, 3), (61, 4), (90, 4), (91, 5)):
        clock[0] = now
        owner.step(cancelled, acknowledge)
        assert _queries(runner) == expected
        assert sum(call[0] == "scancel" for call in runner.calls) == (1 if now == 91 else 0)
    assert owner.journal.read("operation-1").cancel_requested


@pytest.mark.parametrize("kind", ["release", "recovery"])
def test_repeated_cleanup_requests_back_off_without_losing_the_assignment(tmp_path, monkeypatch, kind):
    import loom.queue._agent_slurm as agent_module
    owner, task, clock, runner, _profile_value = _owner(tmp_path, monkeypatch)
    owner.step(task, _ack)
    calls = []
    def cleanup(_profile_value, proof):
        calls.append((clock[0], proof))
        return SlurmContainmentReceipt("UNKNOWN")
    monkeypatch.setattr(agent_module, "resolve_slurm_containment", cleanup)
    task = {**task, **({"release_requested": True, "containment_request": {}}
                      if kind == "release" else {"recovery_request": {"recovery": "operation-1"}})}
    for now, expected in ((1, 1), (2, 1), (31, 2), (90, 2), (91, 3), (211, 4), (451, 5), (750, 5), (751, 6)):
        clock[0] = now
        owner.step(task, _ack)
        assert len(calls) == expected
    assert [value[0] for value in calls] == [1, 31, 91, 211, 451, 751]
    assert owner.has_retained_work()
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


@pytest.mark.parametrize("restart", [False, True])
def test_acknowledged_cleanup_replays_revocation_without_new_helper_query(tmp_path, monkeypatch, restart):
    import loom.queue._agent_slurm as agent_module
    owner, task, clock, runner, profile = _owner(tmp_path, monkeypatch)
    owner.step(task, _ack)
    calls = []
    def cleanup(_profile_value, proof):
        assert not calls, "queried again after retaining positive release evidence"
        calls.append(proof)
        return SlurmContainmentReceipt("CONTAINED", "fixture", "1", proof)
    monkeypatch.setattr(agent_module, "resolve_slurm_containment", cleanup)
    lost = False
    def acknowledge(value):
        nonlocal lost
        if value["release"] is not None and not lost:
            lost = True
            raise OSError("lost release acknowledgement")
        return _ack(value)
    clock[0] = 1
    release = {**task, "release_requested": True, "containment_request": {}}
    with pytest.raises(OSError, match="lost release"):
        owner.step(release, acknowledge)
    if restart:
        owner = AgentSlurmJobs(tmp_path, (profile,), observation_policy=SlurmObservationPolicy(300))
    clock[0] = 2
    owner.step(release, acknowledge)
    def settle():
        clock[0] += 0.1
        owner.step(release, acknowledge)
    drive_until(settle, lambda: not owner.has_retained_work())
    assert not owner.has_retained_work()
    assert len(calls) == 1
    from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
    assert isinstance(profile.job_private_file_provider, SlurmUserPrivateFileProvider)
    assert not profile.job_private_file_provider.path_for("operation-1").exists()
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


def test_unknown_restart_reconciles_once_without_resubmission_or_duplicate_observation(tmp_path, monkeypatch):
    owner, task, clock, runner, profile = _owner(
        tmp_path, monkeypatch, submission=[subprocess.TimeoutExpired("sbatch", 60)],
        accounting=[subprocess.TimeoutExpired("sacct", 10), _row()],
    )
    owner.step(task, _ack)
    assert owner.journal.read("operation-1").state is ReadyStageState.UNKNOWN
    owner.step(task, _ack)
    assert _queries(runner) == 1
    clock[0] = 1
    owner.step(task, _ack)
    assert _queries(runner) == 1
    owner = AgentSlurmJobs(tmp_path, (profile,), observation_policy=SlurmObservationPolicy(300))
    owner.step(task, _ack)
    assert owner.journal.read("operation-1").state is ReadyStageState.ACCEPTED
    assert _queries(runner) == 2
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


def test_policy_cap_below_profile_interval_fails_before_opening_state(tmp_path):
    profile = replace(_profile(FakeSlurmCommandRunner(), tmp_path), poll_interval_seconds=30)
    with pytest.raises(QueueConfigError, match="below a profile poll interval"):
        AgentSlurmJobs(tmp_path, (profile,), observation_policy=SlurmObservationPolicy(10))
    assert not (tmp_path / "slurm.sqlite").exists()
