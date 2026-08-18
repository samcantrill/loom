"""Contract coverage for the public queue Python API."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    QueueClient,
    QueueController,
    QueueEnqueueRequest,
    QueueService,
    QueueServiceState,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


def test_queue_python_api_contract(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "pool-1", "mode": "managed"}],
            "queues": [{"queue_name": "default", "pool_name": "pool-1"}],
        }
    )
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    client = QueueClient(service)

    status = client.start_service()
    item = client.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="default",
            run_uri="file:///runs/item-1",
        )
    )
    step = QueueController(service, clock=clock).run_once()

    assert status.to_dict() == {
        "state": QueueServiceState.RUNNING.value,
        "pool_names": ["pool-1"],
        "queue_names": ["default"],
        "recovery_records": [],
    }
    assert item.queue_item_id == "item-1"
    assert step.to_dict()["outcome"] == "dispatched"


def test_managed_local_queue_runtime_api_is_an_explicit_submodule() -> None:
    from loom.queue.managed_local import (
        ManagedLocalQueueRuntime,
        ManagedLocalQueueRuntimeState,
        ManagedLocalQueueRuntimeStatus,
    )

    assert ManagedLocalQueueRuntime
    assert [state.value for state in ManagedLocalQueueRuntimeState] == [
        "READY",
        "DEGRADED",
        "RECOVERY_REQUIRED",
        "DRAINING",
        "STOPPED",
    ]
    assert ManagedLocalQueueRuntimeStatus.__name__ == "ManagedLocalQueueRuntimeStatus"


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
