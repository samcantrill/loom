from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import ReadyStageState
from loom.queue._agent_slurm import AgentSlurmJobs
from loom.queue.errors import QueueConflictError
from loom.queue.slurm_ready_stage import SlurmStageAssignment
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile, _request


def _task(profile, resources=None):
    request = _request(profile, resources=resources)
    assignment = SlurmStageAssignment(
        assignment_id="assignment-1",
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


def test_agent_reopens_exact_journal_and_replays_lost_ack_without_sbatch(
    tmp_path: Path,
):
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
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
    reopened = AgentSlurmJobs(tmp_path, (profile,))
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
        AgentSlurmJobs(tmp_path, (profile,))


def test_expected_agent_operation_cannot_be_reconstructed(tmp_path: Path):
    profile = _profile(FakeSlurmCommandRunner())
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,))
    with pytest.raises(QueueConflictError, match="missing"):
        agent.step({**_task(profile), "expected_sequence": 2}, lambda value: {})
    assert not cast(FakeSlurmCommandRunner, profile.runner).calls


def test_suppressed_call_releases_only_after_authority_acknowledges(tmp_path: Path):
    profile = _profile(FakeSlurmCommandRunner())
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
    from dataclasses import replace
    from loom.pipeline.executors.slurm.commands import SlurmCommandResult
    from loom.pipeline.executors.slurm.ready_stage import operation_marker
    from loom.pipeline.resources import ResourceRequest, ResourceEntry

    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner)
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
