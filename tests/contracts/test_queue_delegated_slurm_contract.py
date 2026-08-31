"""Contract coverage for delegated SLURM queue handoff evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.serialization import thaw_plain_data
from loom.queue import (
    QUEUE_RECORD_SCHEMA_VERSION,
    LaunchContract,
    QueueItem,
    QueueItemStatus,
    RunIntent,
)
from loom.queue.slurm import SlurmQueueDispatchAdapter


def test_delegated_slurm_dispatch_handle_contract_shape() -> None:
    runner = FakeSlurmCommandRunner(
        starting_job_id=700,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="700|PENDING|Resources\n",
                )
            ]
        },
    )
    result = SlurmQueueDispatchAdapter(command_runner=runner).dispatch(_item())

    evidence = _mapping(thaw_plain_data(result.evidence, path="evidence"))
    assert result.handle_id == "slurm:item-1:1:700"
    assert evidence["adapter"] == "slurm"
    assert evidence["run_uri"] == "file:///runs/item-1"
    assert evidence["scheduler_job_id"] == "700"
    assert evidence["external_handle"] == {
        "kind": "slurm_job",
        "job_id": "700",
        "cluster": None,
    }
    assert evidence["delegated_handoff"] == {
        "durable": True,
        "external_handle_persisted": True,
        "downstream_status_read_succeeded": True,
        "persisted_downstream_status_read_succeeded": None,
        "authority_run_visibility_required": False,
        "loom_resource_leases_held": False,
    }
    assert evidence["loom_resource_leases_held"] is False


def test_delegated_slurm_cancellation_unknown_contract_shape() -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": [
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "700"),
                    returncode=1,
                    stderr="unknown job id",
                )
            ]
        }
    )
    item = _with_dispatch_handle(_item(), job_id="700")

    cancellation = SlurmQueueDispatchAdapter(command_runner=runner).cancel(
        item,
        requested_by="operator",
        reason="stop",
    )

    assert cancellation.reason == "SLURM cancellation outcome unknown"
    assert cancellation.evidence["scheduler_job_id"] == "700"
    assert cancellation.evidence["cancellation_outcome"] == "unknown"
    assert cancellation.evidence["reported_success"] is False
    assert cancellation.evidence["loom_resource_leases_held"] is False


def _item() -> QueueItem:
    run_uri = "file:///runs/item-1"
    return QueueItem(
        queue_item_id="item-1",
        queue_name="slurm",
        pool_name="slurm-pool",
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(
            adapter="slurm",
            entrypoint="sbatch",
            snapshot={"script_path": "/runs/item-1/slurm/job.sh"},
            delegated_verification={"shared_workspace": False},
        ),
        enqueued_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )


def _with_dispatch_handle(item: QueueItem, *, job_id: str) -> QueueItem:
    data = item.to_dict()
    data["status"] = QueueItemStatus.DISPATCHED.value
    data["dispatch_handle"] = {
        "schema_version": QUEUE_RECORD_SCHEMA_VERSION,
        "adapter": "slurm",
        "handle_id": f"slurm:{item.queue_item_id}:1:{job_id}",
        "dispatched_at": "2020-01-01T00:00:01Z",
        "dispatch_attempt": item.dispatch_attempt,
        "evidence": {
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
                "durable": True,
                "external_handle_persisted": True,
                "downstream_status_read_succeeded": True,
                "persisted_downstream_status_read_succeeded": None,
                "authority_run_visibility_required": False,
                "loom_resource_leases_held": False,
            },
            "loom_resource_leases_held": False,
        },
    }
    return QueueItem.from_dict(data)


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)
