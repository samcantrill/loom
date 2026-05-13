"""Integration coverage for queue service lifecycle behavior."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    QueueServiceState,
    normalize_queue_spec,
)


def test_queue_service_reports_recovery_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.sqlite"
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
    )
    spec = normalize_queue_spec(
        {
            "db_path": str(db_path),
            "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
        }
    )
    first = QueueService.from_spec(spec, clock=clock)
    first.start()
    first.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )
    claim = first.claim_next(
        "gpu-pool",
        owner_id="controller-1",
        claim_id="claim-1",
    )
    assert claim is not None

    restarted = QueueService.from_spec(spec, clock=clock)
    status = restarted.start()

    assert status.state is QueueServiceState.RUNNING
    assert [record.queue_item_id for record in status.recovery_records] == ["item-1"]
    assert status.recovery_records[0].status is QueueItemStatus.CLAIMED


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
