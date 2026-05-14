"""Integration coverage for delegated SLURM queue controller handoff."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.queue import (
    LaunchContract,
    QueueController,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    SQLiteQueueRepository,
    normalize_queue_spec,
)
from loom.queue.slurm import SlurmQueueDispatchAdapter
from loom.queue.status import inspect_managed_queue_status


def test_delegated_slurm_foreground_handoff_and_recovery_reuses_handle(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
        "2020-01-01T00:00:04Z",
        "2020-01-01T00:00:05Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    runner = FakeSlurmCommandRunner(
        starting_job_id=700,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="700|PENDING|Resources\n",
                ),
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="700|RUNNING|None\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0)
            ],
        },
    )
    adapter = SlurmQueueDispatchAdapter(
        command_runner=runner,
        authority_run_exists=lambda run_uri: False,
        clock=clock,
    )
    controller = QueueController(service, adapters={"slurm": adapter}, clock=clock)

    result = controller.drain_foreground(
        pool_name="slurm-pool",
        poll_interval_seconds=0,
    )
    dispatched = service.read_item("item-1")
    statuses = inspect_managed_queue_status(service, adapters={"slurm": adapter})

    assert [step.outcome for step in result.steps] == ["dispatched", "handoff"]
    assert len(result.recovery_records) == 1
    assert dispatched is not None
    assert dispatched.status is QueueItemStatus.DISPATCHED
    assert dispatched.run_uri == "file:///runs/item-1"
    assert dispatched.dispatch_handle is not None
    assert dispatched.dispatch_handle.evidence["scheduler_job_id"] == "700"
    assert dispatched.dispatch_handle.evidence["loom_resource_leases_held"] is False
    assert statuses[0].adapter_inspection is not None
    assert statuses[0].adapter_inspection.handoff_complete is True
    status_evidence = _mapping(statuses[0].adapter_inspection.evidence)
    authority_run = _mapping(status_evidence["authority_run"])
    assert authority_run["missing_authority_run"] is True
    assert [call[0] for call in runner.calls].count("sbatch") == 1

    recovery_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": [
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="700|COMPLETED|0:0\n",
                )
            ],
            "squeue": [
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0)
            ],
        }
    )
    recovered = QueueController(
        service,
        adapters={"slurm": SlurmQueueDispatchAdapter(command_runner=recovery_runner)},
        clock=clock,
    ).run_once(pool_name="slurm-pool")

    assert recovered.outcome == "completed"
    assert recovered.item is not None
    assert recovered.item.status is QueueItemStatus.SUCCEEDED
    assert recovered.item.run_uri == "file:///runs/item-1"
    assert [call[0] for call in recovery_runner.calls] == ["sacct", "squeue"]


def _request(item_id: str) -> QueueEnqueueRequest:
    return QueueEnqueueRequest(
        queue_item_id=item_id,
        queue_name="slurm",
        run_uri=f"file:///runs/{item_id}",
        launch_contract=LaunchContract(
            adapter="slurm",
            entrypoint="sbatch",
            resources={"gpu": 1},
            snapshot={"script_path": f"/runs/{item_id}/slurm/job.sh"},
            delegated_verification={"shared_workspace": False},
        ),
    )


def _started_service(tmp_path: Path, *, clock) -> QueueService:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "slurm-pool", "mode": "delegated", "resources": {"gpu": 8}},
            ],
            "queues": [{"queue_name": "slurm", "pool_name": "slurm-pool"}],
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    service.start()
    return service


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)
