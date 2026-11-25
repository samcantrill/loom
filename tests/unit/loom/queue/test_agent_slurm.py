from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from typing import cast

import pytest
from tests.unit.loom.queue.test_agent_slurm_storage import drive_until

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
    drive_until(lambda: agent.replay_pending(acknowledge), lambda: not agent.has_retained_work())
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
            if not lost:
                assert transport.path.exists(), "evidence must survive the lost rejection acknowledgement"
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
            diagnostic_code=None,
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
        drive_until(lambda: agent.step(
            {
                **task,
                "cancel_requested": True,
                "result_identity": identity,
                "containment_request": {},
            },
            acknowledge,
        ), lambda: False)
    assert transport.path.exists()
    assert agent.has_retained_work()
    agent.close()
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    drive_until(lambda: reopened.replay_pending(acknowledge), lambda: not reopened.has_retained_work())
    assert not transport.path.exists()
    assert not agent.has_retained_work()


def test_quota_refusal_cannot_prevent_cancellation_of_unissued_job(tmp_path):
    from loom.queue._slurm_result_transport import SharedSlurmResult

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

    agent.step(task, acknowledge)  # Ordinary capacity is assignment-local.
    assert not runner.calls
    agent.step({**task, "cancel_requested": True}, acknowledge)
    drive_until(lambda: agent.replay_pending(acknowledge), lambda: not agent.has_retained_work())
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
    delivering = AgentSlurmJobs(tmp_path, (profile,))
    with pytest.raises(OSError, match="cleanup interrupted"):
        drive_until(lambda: delivering.step(
            {**task, "result_identity": identity}, acknowledge
        ), lambda: False)
    delivering.close()
    assert operations == ["report", "commit"]
    assert transport.path.exists() and not (transport.path / "report.json").exists()
    monkeypatch.setattr(SharedSlurmResult, "cleanup", cleanup)
    monkeypatch.setattr(
        owner_module,
        "resolve_slurm_containment",
        lambda _profile, proof: SimpleNamespace(
            contained=True,
            diagnostic_code=None,
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
    drive_until(lambda: reopened.replay_pending(acknowledge), lambda: not reopened.has_retained_work())
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
    if cancel:
        drive_until(lambda: reopened.replay_pending(acknowledge), lambda: not reopened.has_retained_work())
    assert result.request == original.request
    assert sum(call[0] == "sbatch" for call in runner.calls) == (0 if cancel else 1)
    assert result.state is (ReadyStageState.REJECTED if cancel else ReadyStageState.ACCEPTED)
    assert reopened.has_started_or_unacknowledged_work() is (not cancel)


def test_live_job_resume_requires_current_epoch_task_and_acknowledged_handle(tmp_path):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    task = _task(profile)
    binding = ("session-1", "epoch-1")
    agent.begin_reconciliation(binding)

    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": False}

    def lose_ack(value):
        if value["submission"]["state"] == "accepted":
            raise OSError("lost accepted acknowledgement")
        return acknowledge(value)

    with pytest.raises(OSError, match="lost accepted"):
        agent.step(task, lose_ack)
    assert agent.has_unreconciled_work(binding)
    saved = agent.journal.read("operation-1")
    confirmed = {**task, "job_id": saved.job_id, "cluster": saved.cluster}
    agent.replay_pending(acknowledge)
    # An acknowledged handle still needs current task confirmation.
    assert agent.has_unreconciled_work(binding)
    agent.step(confirmed, acknowledge)
    assert not agent.has_unreconciled_work(binding)
    assert agent.has_retained_work() and agent.has_started_or_unacknowledged_work()
    assert agent.has_unreconciled_work(("session-1", "epoch-2"))
    agent.begin_reconciliation(("session-1", "epoch-2"))
    assert agent.has_unreconciled_work(("session-1", "epoch-2"))
    agent.step(confirmed, acknowledge)
    assert not agent.has_unreconciled_work(("session-1", "epoch-2"))
    agent.step({**confirmed, "job_id": "different-job"}, acknowledge)
    assert agent.has_unreconciled_work(("session-1", "epoch-2"))
    agent.step(confirmed, acknowledge)
    agent.profiles.clear()
    assert agent.has_unreconciled_work(("session-1", "epoch-2"))
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    reopened.begin_reconciliation(binding)
    assert reopened.has_unreconciled_work(binding)
    reopened.step(confirmed, acknowledge)
    assert not reopened.has_unreconciled_work(binding)
    assert reopened.journal.read("operation-1").job_id == saved.job_id
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1
    # A crash/yield between the scheduler effect and its outbox publication
    # must not reuse the acknowledgement of the preceding observation.
    reopened.journal.request_cancel("operation-1", profile)
    assert reopened.has_unreconciled_work(binding)


@pytest.mark.parametrize("recovering", [False, True])
def test_frozen_containment_evidence_survives_lost_ack_and_restart(tmp_path, monkeypatch, recovering):
    import json
    from types import SimpleNamespace

    import loom.queue._agent_slurm as owner
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentHelper
    from loom.serialization import freeze_plain_data, thaw_plain_data

    runner = FakeSlurmCommandRunner()
    profile = replace(_profile(runner, tmp_path),
                      containment_helper=SlurmContainmentHelper("fixture", ("true",)))
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    task = _task(profile)

    def accept(value):
        return {"sequence": value["sequence"], "cancel_requested": False}

    agent.step(task, accept)
    saved = agent.journal.read("operation-1")
    proof = {"job_id": saved.job_id, "cluster_id": saved.cluster,
             "accounting_identity": {"job_id": saved.job_id, "cluster": saved.cluster,
                                     "steps": ["batch", "extern"], "name": "caf\u00e9"}}
    monkeypatch.setattr(owner, "resolve_slurm_containment", lambda _profile, request: SimpleNamespace(
        contained=True, diagnostic_code=None, state="CONTAINED",
        evidence_id="proof", evidence_revision="1", echo=request,
    ))
    field = "recovery_evidence" if recovering else "release"
    lost = []

    def lose_ack(value):
        # Match the real transport: it encodes the initial callback directly,
        # whereas restart replay has already decoded the persisted JSON.
        json.dumps(value, allow_nan=False)
        if value[field] is not None:
            lost.append(thaw_plain_data(value))
            raise OSError("lost containment acknowledgement")
        return accept(value)

    request = {**task, "job_id": saved.job_id, "cluster": saved.cluster}
    if recovering:
        request["recovery_request"] = proof
    else:
        request.update(release_requested=True, containment_request=proof)
    with pytest.raises(OSError, match="lost containment acknowledgement"):
        agent.step(freeze_plain_data(request), lose_ack)
    assert lost[0][field]["echo"] == proof
    replayed = []

    def replay_ack(value):
        replayed.append(value)
        return accept(value)

    reopened = AgentSlurmJobs(tmp_path, (profile,))
    reopened.replay_pending(replay_ack)
    assert replayed == lost
    assert reopened.journal.read("operation-1").job_id == saved.job_id
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1


def test_known_job_awaiting_containment_does_not_block_recovery_admission(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import loom.queue._agent_slurm as owner

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    binding = ("session-1", "epoch-1")
    agent.begin_reconciliation(binding)
    task = _task(profile)
    acknowledgements = []

    def acknowledge(value):
        acknowledgements.append(value)
        return {"sequence": value["sequence"], "cancel_requested": False}

    agent.step(task, acknowledge)
    saved = agent.journal.read("operation-1")
    monkeypatch.setattr(owner, "resolve_slurm_containment", lambda *_: SimpleNamespace(contained=False, state="UNKNOWN", diagnostic_code=None))
    agent.step({**task, "job_id": saved.job_id, "cluster": saved.cluster,
                "release_requested": True, "containment_request": {}}, acknowledge)
    assert not agent.has_unreconciled_work(binding)
    # Admission is not containment: keep the exact operation and its capability
    # until the ordinary positive release protocol completes.
    assert agent.has_retained_work()
    assert agent.has_started_or_unacknowledged_work()
    assert agent.journal.read("operation-1").job_id == saved.job_id
    assert all(value["release"] is None and not value["provider_released"] for value in acknowledgements)
    assert sum(call[0] == "sbatch" for call in runner.calls) == 1
    assert agent.has_unreconciled_work(("session-1", "epoch-2"))


def test_uncertain_submission_cannot_qualify_live_job_resume(tmp_path):
    runner = FakeSlurmCommandRunner(scripted_results={"sbatch": [TimeoutError("lost response")]})
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    binding = ("session-1", "epoch-1")
    agent.begin_reconciliation(binding)
    agent.step(_task(profile), lambda value: {"sequence": value["sequence"], "cancel_requested": False})
    assert agent.journal.read("operation-1").state is ReadyStageState.UNKNOWN
    assert agent.has_unreconciled_work(binding)
    assert agent.has_retained_work()


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


@pytest.mark.parametrize("cancel", [False, True])
def test_reopen_after_deferred_submit_permission_before_scheduler_call(tmp_path, cancel):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    first = AgentSlurmJobs(tmp_path, (profile,))
    task = _task(profile)
    deferred = []

    def pending(value):
        if value["submission"]["state"] == "submitting":
            deferred.append(value)
            return {"sequence": value["sequence"], "disposition": "pending",
                    "assignment_id": value["assignment"]["assignment_id"], "retry_after_seconds": 1}
        return {"sequence": value["sequence"], "cancel_requested": False}

    first.step(task, pending)
    assert len(deferred) == 1
    assert not any(name == "sbatch" for name, *_ in runner.calls)
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    receipts = []

    def applied(value):
        receipts.append(value)
        return {"sequence": value["sequence"], "cancel_requested": cancel}

    reopened.step(task, applied)
    assert receipts[0] == deferred[0]
    assert all(row["submission"]["state"] != "intent" for row in receipts)
    final = reopened.journal.read("operation-1")
    assert final.state is (ReadyStageState.REJECTED if cancel else ReadyStageState.ACCEPTED)
    assert sum(name == "sbatch" for name, *_ in runner.calls) == int(not cancel)


def test_failed_pending_ack_does_not_hide_later_receipts_or_submit_again(tmp_path):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=512 * 1024 * 1024)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))

    def unavailable(value):
        raise OSError("ack unavailable")

    for key in ("1", "2", "3"):
        with pytest.raises(OSError, match="ack unavailable"):
            agent.step(_task(profile, key=key), unavailable, allow_submission=False)
    delivered = []

    def selective(value):
        identity = value["assignment"]["operation_id"]
        delivered.append(identity)
        if identity == "operation-1":
            raise OSError("first receipt unavailable")
        return {"sequence": value["sequence"], "cancel_requested": False}

    with pytest.raises(OSError, match="first receipt"):
        agent.replay_pending(selective)
    agent.replay_pending(selective)
    assert delivered == ["operation-1", "operation-2", "operation-3"]
    with pytest.raises(OSError, match="first receipt"):
        agent.replay_pending(selective)
    assert not any(call[0] == "sbatch" for call in runner.calls)


def test_pending_ack_replay_visits_at_most_32_receipts_per_iteration(tmp_path, monkeypatch):
    monkeypatch.setattr("loom.queue._agent_slurm.monotonic", lambda: 1.0)
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=8 * 1024**3)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))

    def unavailable(value):
        raise OSError("retain pending evidence")

    for index in range(35):
        with pytest.raises(OSError, match="retain pending"):
            agent.step(_task(profile, key=f"{index:03d}"), unavailable, allow_submission=False)
    received = []

    def acknowledge(value):
        received.append(value["assignment"]["operation_id"])
        return {"sequence": value["sequence"], "cancel_requested": False}

    agent.replay_pending(acknowledge)
    assert received == [f"operation-{index:03d}" for index in range(32)]
    agent.replay_pending(acknowledge)
    assert received == [f"operation-{index:03d}" for index in range(35)]
    AgentSlurmJobs(tmp_path, (profile,)).replay_pending(acknowledge)
    assert len(received) == 35
    assert not any(call[0] == "sbatch" for call in runner.calls)


def test_pending_evidence_preserves_outbox_and_allows_peer_submission(tmp_path):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=256 * 1024 * 1024)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    pending = []

    def acknowledge(value):
        if (value['assignment']['assignment_id'] == 'assignment-1'
                and value['submission']['state'] == 'accepted'):
            pending.append(value)
            return {'sequence': value['sequence'], 'assignment_id': 'assignment-1',
                    'disposition': 'pending', 'retry_after_seconds': 5}
        return {'sequence': value['sequence'], 'cancel_requested': False}

    agent.step(_task(profile), acknowledge)
    with agent._connect() as conn:
        assert conn.execute('SELECT acknowledged FROM agent_slurm_operations WHERE operation_id=?',
                            ('operation-1',)).fetchone() == (0,)
    agent.replay_pending(acknowledge)
    agent.step(_task(profile, key='2'), acknowledge)
    assert len(pending) == 1
    assert len([call for call in runner.calls if call[0] == 'sbatch']) == 2
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    receipts = []

    def applied(value):
        receipts.append(value)
        return {'sequence': value['sequence'], 'disposition': 'applied', 'cancel_requested': False}

    reopened.replay_pending(applied)
    assert receipts == pending
    with reopened._connect() as conn:
        assert conn.execute('SELECT acknowledged FROM agent_slurm_operations WHERE operation_id=?',
                            ('operation-1',)).fetchone() == (1,)
    assert len([call for call in runner.calls if call[0] == 'sbatch']) == 2


def test_uncertain_receipt_preserves_outbox_without_blocking_peer(tmp_path):
    from loom.queue._slurm_result_transport import SlurmRequestUncertain

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=256 * 1024 * 1024)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    retained = []

    def acknowledge(value):
        if value["assignment"]["assignment_id"] == "assignment-1":
            retained.append(value)
            raise SlurmRequestUncertain("response lost")
        return {"sequence": value["sequence"], "cancel_requested": False}

    agent.step(_task(profile), acknowledge)
    agent.step(_task(profile, key="2"), acknowledge)
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    with agent._connect() as conn:
        assert conn.execute(
            "SELECT acknowledged FROM agent_slurm_operations WHERE operation_id='operation-1'",
        ).fetchone() == (0,)
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    replayed = []

    def applied(value):
        replayed.append(value)
        return {"sequence": value["sequence"], "cancel_requested": False}

    reopened.replay_pending(applied)
    assert replayed == retained
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_pending_release_confirms_ownership_only_for_current_session(tmp_path):
    profile = _profile(FakeSlurmCommandRunner(), tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    binding = ("session-1", "epoch-1")
    agent.begin_reconciliation(binding)

    def acknowledge(value):
        if value["provider_released"]:
            return {
                "assignment_id": value["assignment"]["assignment_id"],
                "sequence": value["sequence"], "disposition": "pending",
                "reason": "recovery_retention", "retry_after_seconds": 5,
            }
        return {"sequence": value["sequence"], "cancel_requested": True}

    agent.step(_task(profile), acknowledge)
    assert not agent.has_unreconciled_work(binding)
    assert agent.has_retained_work()
    assert agent.has_started_or_unacknowledged_work()
    with agent._connect() as conn:
        assert conn.execute("SELECT acknowledged, released FROM agent_slurm_operations").fetchone() == (0, 0)
    next_binding = ("session-2", "epoch-2")
    agent.begin_reconciliation(next_binding)
    assert agent.has_unreconciled_work(next_binding)
    agent.replay_pending(acknowledge)
    assert not agent.has_unreconciled_work(next_binding)
    reopened = AgentSlurmJobs(tmp_path, (profile,))
    reopened.begin_reconciliation(next_binding)
    assert reopened.has_unreconciled_work(next_binding)
    reopened.replay_pending(acknowledge)
    assert not reopened.has_unreconciled_work(next_binding)
    assert reopened.has_retained_work()
    assert isinstance(profile.runner, FakeSlurmCommandRunner)
    assert not any(call[0] == "sbatch" for call in profile.runner.calls)


def test_replay_time_budget_preserves_cursor_and_visits_later_receipts(tmp_path, monkeypatch):
    profile = _profile(FakeSlurmCommandRunner(), tmp_path, retention_bytes=1024**3)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    def unavailable(value):
        raise OSError("retained request")
    for key in ("1", "2", "3"):
        with pytest.raises(OSError):
            agent.step(_task(profile, key=key), unavailable, allow_submission=False)
    clock = [10.0]
    monkeypatch.setattr("loom.queue._agent_slurm.monotonic", lambda: clock[0])
    received = []
    def acknowledge(value):
        received.append(value["assignment"]["operation_id"])
        clock[0] += 2
        return {"sequence": value["sequence"], "cancel_requested": False}
    for count in (1, 2, 3):
        agent.replay_pending(acknowledge)
        assert len(received) == count
    assert received == ["operation-1", "operation-2", "operation-3"]


@pytest.mark.parametrize("effect", ["reservation", "credential"])
def test_async_preparation_stall_does_not_block_peer_submission_and_cancel(tmp_path, monkeypatch, effect):
    from threading import Event
    from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider
    from loom.queue._slurm_result_transport import SharedSlurmResult

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=4 * 65 * 1024**2)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    entered, release = Event(), Event()
    reserve = SharedSlurmResult.reserve
    prepare = SlurmJobPrivateFileProvider.prepare

    def reserve_with_stall(transport, assignment):
        if assignment["assignment_id"] == "assignment-1" and effect == "reservation":
            entered.set()
            assert release.wait(10)
        return reserve(transport, assignment)

    def prepare_with_stall(provider, *, operation_id, request_digest):
        if operation_id == "operation-1" and effect == "credential":
            entered.set()
            assert release.wait(10)
        return prepare(provider, operation_id=operation_id, request_digest=request_digest)

    monkeypatch.setattr(SharedSlurmResult, "reserve", reserve_with_stall)
    monkeypatch.setattr(SlurmJobPrivateFileProvider, "prepare", prepare_with_stall)
    first, second = _task(profile), _task(profile, key="2")
    binding = ("session", "epoch")
    agent.begin_reconciliation(binding)
    cancel_peer = False

    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": cancel_peer and value["assignment"]["assignment_id"] == "assignment-2"}

    try:
        drive_until(lambda: agent.step(first, acknowledge), entered.is_set)
        assert not agent.has_unreconciled_work(binding)
        assert not agent.has_started_or_unacknowledged_work()
        # A new epoch must reconfirm that zero-evidence fact; the in-memory
        # observation cannot authorize admission through a restart by itself.
        binding = ("session", "new-epoch")
        agent.begin_reconciliation(binding)
        assert agent.has_unreconciled_work(binding)
        agent.step(first, acknowledge)
        assert not agent.has_unreconciled_work(binding)
        drive_until(lambda: agent.step(second, acknowledge), lambda: (record := agent.journal.find("operation-2")) is not None and record.job_id is not None)
        assert not release.is_set()
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
        peer = agent.journal.read("operation-2")
        cancel_peer = True
        drive_until(lambda: agent.step({**second, "cancel_requested": True, "job_id": peer.job_id, "cluster": peer.cluster, "containment_request": {}}, acknowledge),
                    lambda: any(call[0] == "scancel" for call in runner.calls))
        assert not release.is_set()
    finally:
        release.set()
        agent.close()


def test_async_credential_revocation_does_not_block_peer_submission(tmp_path, monkeypatch):
    from threading import Event
    import loom.queue._agent_slurm as owner_module
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt, SlurmJobPrivateFileProvider

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=4 * 65 * 1024**2)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    entered, release = Event(), Event()
    revoke = SlurmJobPrivateFileProvider.revoke
    calls = []

    def slow_revoke(provider, capability):
        calls.append(capability)
        entered.set()
        assert release.wait(10)
        return revoke(provider, capability)

    monkeypatch.setattr(SlurmJobPrivateFileProvider, "revoke", slow_revoke)
    monkeypatch.setattr(owner_module, "resolve_slurm_containment", lambda _profile, proof: SlurmContainmentReceipt("CONTAINED", "proof", "1", proof))
    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": False, "result_committed": True}
    first, second = _task(profile), _task(profile, key="2")
    try:
        drive_until(lambda: agent.step(first, acknowledge), lambda: (record := agent.journal.find("operation-1")) is not None and record.job_id is not None)
        closing = {**first, "release_requested": True, "containment_request": {}}
        drive_until(lambda: agent.step(closing, acknowledge), entered.is_set)
        drive_until(lambda: agent.step(second, acknowledge), lambda: (record := agent.journal.find("operation-2")) is not None and record.job_id is not None)
        assert len(calls) == 1 and not release.is_set()
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 2
        release.set()
        def released():
            with agent._connect() as conn:
                return conn.execute("SELECT released FROM agent_slurm_operations WHERE operation_id='operation-1'").fetchone()[0] == 1
        drive_until(lambda: agent.step(closing, acknowledge), released)
    finally:
        release.set()
        agent.close()


def test_async_capability_receipt_replays_after_restart_before_installation(tmp_path, monkeypatch):
    from threading import Event
    from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    prepared, release = Event(), Event()
    create = SlurmJobPrivateFileProvider.prepare
    receipts = []

    def prepare_then_pause(provider, **request):
        receipt = create(provider, **request)
        receipts.append(receipt)
        prepared.set()
        assert release.wait(10)
        return receipt

    monkeypatch.setattr(SlurmJobPrivateFileProvider, "prepare", prepare_then_pause)
    task = _task(profile)
    def acknowledge(value):
        return {"sequence": value["sequence"], "cancel_requested": False}
    try:
        drive_until(lambda: agent.step(task, acknowledge), prepared.is_set)
        assert agent.journal.read("operation-1").capability is None
        assert not [call for call in runner.calls if call[0] == "sbatch"]
    finally:
        release.set()
        agent.close()
    reopened = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    try:
        drive_until(lambda: reopened.step(task, acknowledge), lambda: reopened.journal.read("operation-1").job_id is not None)
        assert len(receipts) == 2 and receipts[0] == receipts[1]
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("blocked_effect", ["submit", "containment"])
def test_slow_scheduler_effect_does_not_block_peer_observation_or_cancel(tmp_path, monkeypatch, blocked_effect):
    from threading import Event, get_ident
    import loom.queue._agent_slurm as owner_module
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=4 * 65 * 1024**2)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    entered, release = Event(), Event()
    submit = runner.sbatch
    owner_thread = get_ident()
    journal_threads = []
    record_outcome = agent.journal._record_outcome

    def record(*args, **kwargs):
        journal_threads.append(get_ident())
        return record_outcome(*args, **kwargs)

    def slow_submit(script, **kwargs):
        if script.name == "assignment-1.sh" and blocked_effect == "submit":
            entered.set()
            assert release.wait(10)
        return submit(script, **kwargs)

    def slow_containment(_profile, proof):
        if proof.get("slow") is True and blocked_effect == "containment":
            entered.set()
            assert release.wait(10)
        return SlurmContainmentReceipt("UNKNOWN")

    monkeypatch.setattr(runner, "sbatch", slow_submit)
    monkeypatch.setattr(owner_module, "resolve_slurm_containment", slow_containment)
    monkeypatch.setattr(agent.journal, "_record_outcome", record)
    cancel_peer = False
    def acknowledge(value):
        assert get_ident() == owner_thread
        return {"sequence": value["sequence"], "cancel_requested": cancel_peer and value["assignment"]["assignment_id"] == "assignment-2"}

    first, peer = _task(profile), _task(profile, key="2")
    if blocked_effect == "containment":
        first = {**first, "release_requested": True, "containment_request": {"slow": True}}
    try:
        drive_until(lambda: agent.step(peer, acknowledge), lambda: (value := agent.journal.find("operation-2")) is not None and value.job_id is not None)
        drive_until(lambda: agent.step(first, acknowledge), entered.is_set)
        calls_before = len(runner.calls)
        agent._next_poll.pop("operation-2", None)
        drive_until(lambda: agent.step(peer, acknowledge),
                    lambda: any(name in {"squeue", "sacct"} for name, _ in runner.calls[calls_before:]))
        cancel_peer = True
        closing = {**peer, "cancel_requested": True, "containment_request": {}}
        drive_until(lambda: agent.step(closing, acknowledge), lambda: agent.journal.read("operation-2").cancel_requested)
        assert any(call[0] in {"squeue", "sacct"} for call in runner.calls[calls_before:])
        assert any(call[0] == "scancel" for call in runner.calls[calls_before:])
        assert not release.is_set()
        for _ in range(10):
            agent.step(first, acknowledge)
        assert journal_threads and set(journal_threads) == {owner_thread}
        release.set()
        drive_until(lambda: agent.step(first, acknowledge), lambda: agent.journal.read("operation-1").job_id is not None)
        assert sum(call[0] == "sbatch" for call in runner.calls) == 2
    finally:
        release.set()
        agent.close()

def test_cancel_reaches_exact_job_with_both_observation_workers_occupied(tmp_path, monkeypatch):
    from threading import Event

    runner = FakeSlurmCommandRunner()
    profile = replace(_profile(runner, tmp_path, retention_bytes=4 * 65 * 1024**2), max_outstanding=3)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    tasks = [_task(profile, key=str(i)) for i in (1, 2, 3)]
    held = {}
    release = Event()
    original = runner.squeue
    cancel_job = False

    def acknowledge(value):
        return {"sequence": value["sequence"],
                "cancel_requested": cancel_job and value["assignment"]["assignment_id"] == "assignment-3"}

    def observe(*, job_ids=()):
        if len(job_ids) == 1 and job_ids[0] in held:
            held[job_ids[0]].set()
            assert release.wait(15)
        return original(job_ids=job_ids)

    try:
        for task in tasks:
            op = task["assignment"]["operation_id"]
            drive_until(lambda: agent.step(task, acknowledge),
                        lambda: (current := agent.journal.find(op)) is not None and current.job_id is not None)
        monkeypatch.setattr(runner, "squeue", observe)
        for task in tasks[:2]:
            op = task["assignment"]["operation_id"]
            job_id = agent.journal.read(op).job_id
            entered = held[job_id] = Event()
            agent._next_poll.pop(op, None)
            drive_until(lambda: agent.step(task, acknowledge), entered.is_set)
        cancel_job = True
        closing = {**tasks[2], "cancel_requested": True, "containment_request": {}}
        drive_until(lambda: agent.step(closing, acknowledge),
                    lambda: agent.journal.read("operation-3").cancel_requested)
        job = agent.journal.read("operation-3").job_id
        assert [argv for name, argv in runner.calls if name == "scancel"] == [("scancel", job)]
        assert not release.is_set()
    finally:
        release.set()
        agent.close()
