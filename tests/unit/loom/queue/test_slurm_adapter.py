"""Unit coverage for delegated SLURM queue dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.serialization import thaw_plain_data
from loom.queue import LaunchContract, QueueItem, QueueItemStatus, RunIntent
from loom.queue.slurm import SlurmQueueDispatchAdapter


def test_slurm_adapter_submits_and_records_durable_handoff_without_leases() -> None:
    runner = FakeSlurmCommandRunner(
        starting_job_id=42,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="42|PENDING|Resources\n",
                )
            ]
        },
    )
    adapter = SlurmQueueDispatchAdapter(command_runner=runner)
    item = _item("item-1")

    result = adapter.dispatch(item)

    evidence = _mapping(thaw_plain_data(result.evidence, path="evidence"))
    handoff = _mapping(evidence["delegated_handoff"])
    verification = _mapping(evidence["delegated_launch_verification"])
    assert result.complete is False
    assert result.status is QueueItemStatus.DISPATCHED
    assert result.handle_id == "slurm:item-1:1:42"
    assert evidence["scheduler_job_id"] == "42"
    assert evidence["external_handle"] == {
        "kind": "slurm_job",
        "job_id": "42",
        "cluster": None,
    }
    assert handoff["durable"] is True
    assert handoff["downstream_status_read_succeeded"] is True
    assert evidence["loom_resource_leases_held"] is False
    assert "downstream_status_read" in _sequence(verification["proven"])
    assert "loom_resource_leases_not_held" in _sequence(verification["proven"])
    assert "shared_workspace" in _sequence(verification["unproven"])
    assert [call[0] for call in runner.calls] == ["sbatch", "squeue"]


def test_slurm_adapter_inspects_terminal_scheduler_state() -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": [
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="42|COMPLETED|0:0\n",
                )
            ],
            "squeue": [
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0)
            ],
        }
    )
    adapter = SlurmQueueDispatchAdapter(command_runner=runner)
    item = _with_dispatch_handle(_item("item-1"), job_id="42", durable=True)

    inspection = adapter.inspect(item)

    assert inspection.terminal is True
    assert inspection.status is QueueItemStatus.SUCCEEDED
    assert inspection.reason == "SLURM job completed"


def test_slurm_adapter_reports_missing_authority_run_while_handle_is_active() -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": [
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0)
            ],
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="42|RUNNING|None\n",
                )
            ],
        }
    )
    adapter = SlurmQueueDispatchAdapter(
        command_runner=runner,
        authority_run_exists=lambda run_uri: False,
    )
    item = _with_dispatch_handle(_item("item-1"), job_id="42", durable=True)

    inspection = adapter.inspect(item)
    evidence = _mapping(thaw_plain_data(inspection.evidence, path="evidence"))
    authority_run = _mapping(evidence["authority_run"])

    assert inspection.terminal is False
    assert inspection.handoff_complete is True
    assert authority_run["missing_authority_run"] is True
    diagnostics = _sequence(authority_run["diagnostics"])
    first_diagnostic = _mapping(diagnostics[0])
    assert first_diagnostic["code"] == "queue.slurm.missing_authority_run"


def test_slurm_adapter_recovers_partial_handoff_after_later_status_read() -> None:
    runner = FakeSlurmCommandRunner(
        starting_job_id=42,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=1,
                    stderr="scheduler temporarily unavailable",
                ),
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="42|PENDING|Resources\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0)
            ],
        },
    )
    adapter = SlurmQueueDispatchAdapter(command_runner=runner)
    item = _item("item-1")

    result = adapter.dispatch(item)
    result_evidence = _mapping(thaw_plain_data(result.evidence, path="evidence"))
    result_handoff = _mapping(result_evidence["delegated_handoff"])
    dispatched = _with_dispatch_handle(
        item,
        job_id="42",
        durable=result_handoff["durable"] is True,
        evidence=result.evidence,
    )
    inspection = adapter.inspect(dispatched)

    assert result_handoff["durable"] is False
    assert inspection.terminal is False
    assert inspection.handoff_complete is True
    assert inspection.status is QueueItemStatus.DISPATCHED
    assert [call[0] for call in runner.calls] == ["sbatch", "squeue", "sacct", "squeue"]


def test_slurm_adapter_cancel_records_requested_or_unknown_outcome() -> None:
    requested_runner = FakeSlurmCommandRunner()
    adapter = SlurmQueueDispatchAdapter(command_runner=requested_runner)
    item = _with_dispatch_handle(_item("item-1"), job_id="42", durable=True)

    requested = adapter.cancel(item, requested_by="operator", reason="stop")

    assert requested.reason == "stop"
    assert requested.evidence["cancellation_outcome"] == "requested"
    assert requested.evidence["reported_success"] is True

    unknown_runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": [
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "42"),
                    returncode=1,
                    stderr="unknown job id",
                )
            ]
        }
    )
    unknown = SlurmQueueDispatchAdapter(command_runner=unknown_runner).cancel(
        item,
        requested_by="operator",
        reason="stop",
    )

    assert unknown.reason == "SLURM cancellation outcome unknown"
    assert unknown.evidence["cancellation_outcome"] == "unknown"
    assert unknown.evidence["reported_success"] is False


def _item(item_id: str) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name="slurm",
        pool_name="slurm-pool",
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(
            adapter="slurm",
            entrypoint="sbatch",
            resources={"gpu": 1},
            snapshot={
                "script_path": f"/runs/{item_id}/slurm/job.sh",
                "dependency_job_ids": ["11", "12"],
            },
            delegated_verification={
                "shared_workspace": False,
                "script_path": True,
            },
        ),
        enqueued_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )


def _with_dispatch_handle(
    item: QueueItem,
    *,
    job_id: str,
    durable: bool,
    evidence: object | None = None,
) -> QueueItem:
    data = item.to_dict()
    data["status"] = QueueItemStatus.DISPATCHED.value
    data["dispatch_handle"] = {
        "schema_version": 1,
        "adapter": "slurm",
        "handle_id": f"slurm:{item.queue_item_id}:1:{job_id}",
        "dispatched_at": "2020-01-01T00:00:01Z",
        "dispatch_attempt": item.dispatch_attempt,
        "evidence": thaw_plain_data(
            evidence
            if evidence is not None
            else {
                "adapter": "slurm",
                "run_uri": item.run_uri,
                "scheduler_job_id": job_id,
                "slurm_cluster": None,
                "external_handle": {
                    "kind": "slurm_job",
                    "job_id": job_id,
                    "cluster": None,
                },
                "delegated_handoff": {
                    "durable": durable,
                    "external_handle_persisted": True,
                    "downstream_status_read_succeeded": durable,
                    "persisted_downstream_status_read_succeeded": None,
                    "authority_run_visibility_required": False,
                    "loom_resource_leases_held": False,
                },
                "loom_resource_leases_held": False,
            },
            path="evidence",
        ),
    }
    return QueueItem.from_dict(data)


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    assert isinstance(value, Sequence) and not isinstance(value, str)
    return cast(Sequence[object], value)
