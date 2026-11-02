from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from typing import cast

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import ReadyStageState
from loom.queue._agent_slurm import AgentSlurmJobs
from loom.queue.errors import QueueConflictError
from loom.queue.slurm_ready_stage import SlurmStageAssignment
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import (
    _profile as _base_profile,
    _request,
    _TEST_HELPER,
)


def _profile(runner, tmp_path, *, retention_bytes=128 * 1024 * 1024):
    from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider

    root = tmp_path / "shared-results"
    root.mkdir(exist_ok=True)
    return replace(
        _base_profile(runner, provider=SlurmJobPrivateFileProvider(
            fixed_path=str(tmp_path / "capability"), descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        )),
        result_storage={
            "agent_root": str(root),
            "compute_root": str(root),
            "retention_bytes": retention_bytes,
        },
    )


def _task(profile, resources=None, *, key="1"):
    request = _request(profile, resources=resources, operation_id=f"operation-{key}", stage_work_id=f"work-{key}")
    assignment = SlurmStageAssignment(
        assignment_id=f"assignment-{key}",
        operation_id=request.operation_id,
        run_uri=request.run_uri,
        stage_work_id=request.stage_work_id,
        stage_name="train",
        attempt=1,
        attempt_id=request.attempt_id,
        profile_id=profile.profile_id,
        profile_descriptor=profile.descriptor,
        profile_configuration_fingerprint=profile.configuration_fingerprint,
        request_digest=request.digest,
        agent_id="agent-a",
        agent_root_id="root-a",
    )
    return {
        "schema_version": 1,
        "assignment": assignment.to_dict(),
        "request": request.to_dict(),
        "expected_sequence": 0,
        "release_requested": False,
        "job_id": None,
        "cluster": None,
    }


@pytest.mark.parametrize("rollback", [False, True])
def test_agent_reopens_exact_journal_and_replays_lost_ack_without_sbatch(
    tmp_path: Path, rollback,
):
    from loom._sqlite_policy import SQLitePolicy
    policy = SQLitePolicy("delete", "extra", 1234) if rollback else None
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path, sqlite_policy=policy)
    agent = AgentSlurmJobs(tmp_path, (profile,), sqlite_policy=policy)
    task = _task(profile)
    accepted = []

    def acknowledge(value):
        accepted.append(value)
        if value["submission"]["state"] == "accepted":
            raise OSError("lost coordinator acknowledgement")
        return {"sequence": value["sequence"], "cancel_requested": False}

    with pytest.raises(OSError, match="lost coordinator"):
        agent.step(task, acknowledge)
    assert agent.has_retained_work()
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    reopened = AgentSlurmJobs(tmp_path, (profile,), sqlite_policy=policy)
    replayed = []

    def accept(value):
        replayed.append(value)
        return {"sequence": value["sequence"], "cancel_requested": False}

    reopened.replay_pending(accept)
    assert replayed[0] == accepted[-1]
    reopened.step({**task, "expected_sequence": accepted[-1]["sequence"]}, accept)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    assert reopened.journal.read("operation-1").state is ReadyStageState.ACCEPTED
    (tmp_path / "slurm.sqlite").unlink()
    with pytest.raises(Exception, match="missing"):
        AgentSlurmJobs(tmp_path, (profile,), sqlite_policy=policy)


def test_expected_agent_operation_cannot_be_reconstructed(tmp_path: Path):
    profile = _profile(FakeSlurmCommandRunner(), tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    with pytest.raises(QueueConflictError, match="missing"):
        agent.step({**_task(profile), "expected_sequence": 2}, lambda value: {})
    assert not cast(FakeSlurmCommandRunner, profile.runner).calls


def test_suppressed_call_releases_only_after_authority_acknowledges(tmp_path: Path):
    profile = _profile(FakeSlurmCommandRunner(), tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    seen = []

    def acknowledge(value):
        seen.append(value)
        return {"sequence": value["sequence"], "cancel_requested": True}

    agent.step(_task(profile), acknowledge)
    assert all(
        call[0] != "sbatch"
        for call in cast(FakeSlurmCommandRunner, profile.runner).calls
    )
    assert seen[-2]["provider_released"] is False
    assert seen[-1]["provider_released"] is True
    assert seen[-1]["release"] == {"kind": "definite_rejection"}
    assert not agent.has_retained_work()


def test_uncertain_agent_call_discovers_before_exact_cancel_without_host_gpu(
    tmp_path: Path,
):
    from loom.pipeline.executors.slurm.commands import SlurmCommandResult
    from loom.pipeline.executors.slurm.ready_stage import operation_marker
    from loom.pipeline.resources import ResourceRequest, ResourceEntry

    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner, tmp_path)
    task = _task(
        profile,
        ResourceRequest(
            entries={
                "gpu": ResourceEntry(
                    "gpu", 2, "count", {"allocation_mode": "exclusive"}
                )
            }
        ),
    )
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    cancel = False
    acknowledged = []

    def accept(value):
        acknowledged.append(value)
        return {"sequence": value["sequence"], "cancel_requested": cancel}

    agent.step(task, accept)
    assert agent.journal.read("operation-1").state is ReadyStageState.UNKNOWN
    assert "--gres=gpu:2" in task["request"]["script"]
    cancel = True
    empty = AgentSlurmJobs(tmp_path, (profile,))
    empty.step({**task, "expected_sequence": acknowledged[-1]["sequence"]}, accept)
    assert empty.journal.read("operation-1").state is ReadyStageState.UNKNOWN
    assert not any(call[0] == "scancel" for call in runner.calls)
    discovered = FakeSlurmCommandRunner(
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout="5101|" + operation_marker("operation-1") + "\n",
                )
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    reopened = AgentSlurmJobs(tmp_path, (replace(profile, runner=discovered),))
    reopened.step(
        {
            **task,
            "expected_sequence": acknowledged[-1]["sequence"],
            "containment_request": {},
        },
        accept,
    )
    assert reopened.journal.read("operation-1").job_id == "5101"
    assert any(call[0] == "scancel" and "5101" in call[1] for call in discovered.calls)
    assert not any(call[0] == "sbatch" for call in discovered.calls)
    assert reopened.has_retained_work(), "scancel is not containment"


@pytest.mark.parametrize("interruption", ("acknowledgement", "cleanup"))
def test_cancelled_published_result_waits_for_terminal_rejection_ack(
    tmp_path, monkeypatch, interruption
):
    from types import SimpleNamespace
    from loom.pipeline.status import StageStatus
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentHelper
    from loom.queue._remote_stage_execution import _RemoteExecutionReport
    from loom.queue._slurm_result_transport import SharedSlurmResult
    import loom.queue._agent_slurm as owner_module

    profile = replace(
        _profile(FakeSlurmCommandRunner(), tmp_path),
        containment_helper=SlurmContainmentHelper("fixture", ("true",)),
    )
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    task = _task(profile)
    cancel = False
    lost = False
    transport = SharedSlurmResult(profile.result_storage, "assignment-1")

    def acknowledge(value):
        nonlocal lost
        assert "result_operation" not in value, (
            "cancelled result must not block containment"
        )
        if value["provider_released"]:
            assert transport.path.exists(), (
                "evidence must survive the lost rejection acknowledgement"
            )
            if not lost:
                lost = True
                if interruption == "acknowledgement":
                    raise OSError("lost terminal rejection acknowledgement")
        return {"sequence": value["sequence"], "cancel_requested": cancel}

    agent.step(task, acknowledge)
    identity = {
        "coordinator_id": "coordinator",
        "assignment": task["assignment"],
        "fence": "fence",
        "incarnation": "bootstrap",
    }
    report = _RemoteExecutionReport(
        "assignment-1",
        "train",
        1,
        StageStatus.SUCCEEDED,
        "2026-09-13T00:00:00Z",
        "2026-09-13T00:00:01Z",
        "local",
        schema_version=6,
        executor_metadata={},
        process_created=True,
    )
    transport.publish(identity, report, lambda *_args: (b"", True))
    monkeypatch.setattr(
        owner_module,
        "resolve_slurm_containment",
        lambda _profile, proof: SimpleNamespace(
            contained=True,
            state="CONTAINED",
            evidence_id="proof",
            evidence_revision="1",
            echo=proof,
        ),
    )
    cleanup = SharedSlurmResult.cleanup
    interrupted_cleanup = False

    def cleanup_with_interruption(owner):
        nonlocal interrupted_cleanup
        if interruption == "cleanup" and not interrupted_cleanup:
            interrupted_cleanup = True
            (owner.path / "report.json").unlink()
            raise OSError("lost terminal rejection cleanup")
        cleanup(owner)

    monkeypatch.setattr(SharedSlurmResult, "cleanup", cleanup_with_interruption)
    cancel = True
    with pytest.raises(OSError, match="lost terminal rejection"):
        agent.step(
            {
                **task,
                "cancel_requested": True,
                "result_identity": identity,
                "containment_request": {},
            },
            acknowledge,
        )
    assert transport.path.exists()
    assert agent.has_retained_work()
    AgentSlurmJobs(tmp_path, (profile,)).replay_pending(acknowledge)
    assert not transport.path.exists()
    assert not agent.has_retained_work()


def test_quota_refusal_cannot_prevent_cancellation_of_unissued_job(tmp_path):
    from loom.queue._slurm_result_transport import SharedSlurmResult
    from loom.queue.errors import QueueServiceError

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    assert profile.result_storage is not None
    storage = {**profile.result_storage, "retention_bytes": 65 * 1024 * 1024}
    profile = replace(profile, result_storage=storage)
    task = _task(profile)
    occupied = SharedSlurmResult(storage, "another-retained-attempt")
    occupied.reserve(
        {**task["assignment"], "assignment_id": "another-retained-attempt"}
    )
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))

    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": True}

    with pytest.raises(QueueServiceError, match="quota exhausted"):
        agent.step(task, acknowledge)
    assert not runner.calls
    agent.step({**task, "cancel_requested": True}, acknowledge)
    assert not agent.has_retained_work()
    assert occupied.path.exists()
    assert not any(call[0] == "sbatch" for call in runner.calls)


def test_interrupted_acknowledged_cleanup_replays_authority_before_retirement(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from loom.pipeline.status import StageStatus
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentHelper
    from loom.queue._remote_stage_execution import _RemoteExecutionReport
    from loom.queue._slurm_result_transport import SharedSlurmResult
    import loom.queue._agent_slurm as owner_module

    profile = replace(
        _profile(FakeSlurmCommandRunner(), tmp_path),
        containment_helper=SlurmContainmentHelper("fixture", ("true",)),
    )
    AgentSlurmJobs.initialize(tmp_path)
    task = _task(profile)
    operations = []

    def acknowledge(value):
        if "result_operation" in value:
            operations.append(value["result_operation"])
            return {"acknowledged": True}
        return {"sequence": value["sequence"], "cancel_requested": False}

    AgentSlurmJobs(tmp_path, (profile,)).step(task, acknowledge)
    identity = {
        "coordinator_id": "coordinator",
        "assignment": task["assignment"],
        "fence": "fence",
        "incarnation": "bootstrap",
    }
    report = _RemoteExecutionReport(
        "assignment-1",
        "train",
        1,
        StageStatus.SUCCEEDED,
        "2026-09-13T00:00:00Z",
        "2026-09-13T00:00:01Z",
        "local",
        schema_version=6,
        executor_metadata={},
        process_created=True,
    )
    transport = SharedSlurmResult(profile.result_storage, "assignment-1")
    transport.publish(identity, report, lambda *_args: (b"", True))
    cleanup = SharedSlurmResult.cleanup

    def interrupted(owner):
        (owner.path / "report.json").unlink()
        raise OSError("cleanup interrupted after acknowledged commit")

    monkeypatch.setattr(SharedSlurmResult, "cleanup", interrupted)
    with pytest.raises(OSError, match="cleanup interrupted"):
        AgentSlurmJobs(tmp_path, (profile,)).step(
            {**task, "result_identity": identity}, acknowledge
        )
    assert operations == ["report", "commit"]
    assert transport.path.exists() and not (transport.path / "report.json").exists()
    monkeypatch.setattr(SharedSlurmResult, "cleanup", cleanup)
    monkeypatch.setattr(
        owner_module,
        "resolve_slurm_containment",
        lambda _profile, proof: SimpleNamespace(
            contained=True,
            state="CONTAINED",
            evidence_id="proof",
            evidence_revision="1",
            echo=proof,
        ),
    )
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    reopened.step(
        {
            **task,
            "result_identity": identity,
            "release_requested": True,
            "containment_request": {},
        },
        acknowledge,
    )
    assert operations == ["report", "commit", "commit"]
    assert not transport.path.exists()
    assert not reopened.has_retained_work()


@pytest.mark.parametrize("uncertain", [False, True])
def test_submit_pacing_does_not_block_observation_cancel_or_restart(tmp_path, monkeypatch, uncertain):
    from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
    import loom.queue._agent_slurm as agent_module

    clock = [100.0]
    monkeypatch.setattr(agent_module, "monotonic", lambda: clock[0])
    runner = FakeSlurmCommandRunner(scripted_results={
        "sbatch": [TimeoutError("uncertain submission")],
    } if uncertain else {})
    profile = replace(
        _profile(runner, tmp_path, retention_bytes=1024 ** 3), poll_interval_seconds=0.05,
        job_private_file_provider=SlurmUserPrivateFileProvider(
            root=tmp_path / "capabilities", descriptor="trusted-pacing-test",
        ),
    )
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), submit_interval_seconds=1.0)
    cancel = set()
    seen = []

    def acknowledge(value):
        seen.append(value)
        return {"sequence": value["sequence"], "cancel_requested": value["submission"]["request"]["operation_id"] in cancel}

    first = _task(profile)
    agent.step(first, acknowledge)
    second = _task(profile, key="2")
    agent.step(second, acknowledge)
    assert agent.journal.read("operation-2").state is ReadyStageState.INTENT
    assert not any(item["submission"]["state"] == "submitting" and item["submission"]["request"]["operation_id"] == "operation-2" for item in seen)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1

    # A due existing operation is still observed while new submission is paced.
    clock[0] += 0.1
    observed_before = len([call for call in runner.calls if call[0] in {"squeue", "sacct"}])
    agent.step(first, acknowledge)
    assert len([call for call in runner.calls if call[0] in {"squeue", "sacct"}]) > observed_before
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1

    # Cancellation wins over the pacing wait and never calls sbatch.
    cancel.add("operation-2")
    agent.step(second, acknowledge)
    assert agent.journal.read("operation-2").state is ReadyStageState.REJECTED
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1

    third = _task(profile, key="3")
    agent.step(third, acknowledge)
    assert agent.journal.read("operation-3").state is ReadyStageState.INTENT
    clock[0] = 101.0
    agent.step(third, acknowledge)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 2
    restarted = AgentSlurmJobs(tmp_path, (profile,), submit_interval_seconds=1.0)
    restarted.step(first, acknowledge)
    restarted.step(third, acknowledge)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 2
    restarted.step(_task(profile, key="4"), acknowledge)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 3


@pytest.mark.parametrize("finish", ["submit", "cancel"])
def test_drained_intent_survives_restart_without_submitting(tmp_path, finish):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    task = _task(profile)
    cancel = False

    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": cancel}

    def lose_ack(value):
        raise OSError("lost intent acknowledgement")

    with pytest.raises(OSError, match="lost intent"):
        agent.step(task, lose_ack, allow_submission=False)
    assert agent.has_started_or_unacknowledged_work()
    agent.step(task, acknowledge, allow_submission=False)
    original = agent.journal.read("operation-1")
    assert original.state is ReadyStageState.INTENT
    assert agent.has_retained_work()
    assert not agent.has_started_or_unacknowledged_work()
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    reopened.step(task, acknowledge, allow_submission=False)
    assert reopened.journal.read("operation-1") == original
    assert not any(call[0] == "sbatch" for call in runner.calls)
    cancel = finish == "cancel"
    reopened.step(task, acknowledge, allow_submission=not cancel)
    result = reopened.journal.read("operation-1")
    assert result.request == original.request
    assert sum(call[0] == "sbatch" for call in runner.calls) == (0 if cancel else 1)
    assert result.state is (ReadyStageState.REJECTED if cancel else ReadyStageState.ACCEPTED)
    assert reopened.has_started_or_unacknowledged_work() is (not cancel)


def test_pacing_starts_after_submitting_acknowledgement(tmp_path, monkeypatch):
    from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
    import loom.queue._agent_slurm as agent_module

    clock = [10.0]
    monkeypatch.setattr(agent_module, "monotonic", lambda: clock[0])
    runner = FakeSlurmCommandRunner()
    profile = replace(_profile(runner, tmp_path, retention_bytes=1024 ** 3), job_private_file_provider=SlurmUserPrivateFileProvider(
        root=tmp_path / "capabilities", descriptor="trusted-pacing-test",
    ))
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), submit_interval_seconds=1.0)

    def acknowledge(value):
        if value["submission"]["state"] == "submitting":
            clock[0] += 5.0
        return {"sequence": value["sequence"], "cancel_requested": False}

    agent.step(_task(profile), acknowledge)
    assert clock[0] == 15.0
    agent.step(_task(profile, key="2"), acknowledge)
    assert agent.journal.read("operation-2").state is ReadyStageState.INTENT
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
