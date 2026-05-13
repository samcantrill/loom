"""Integration coverage for fake queue controller operation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.queue import (
    QueueClient,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    load_queue_spec,
)


def test_fake_controller_drains_loaded_queue_config(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    db_path = tmp_path / "queue.sqlite"
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {db_path}
          pools:
            - pool_name: gpu-pool
              mode: managed
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = QueueService.from_spec(load_queue_spec(config_path), clock=clock)
    client = QueueClient(service)
    client.start_service()
    client.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )

    drain = client.drain_foreground()
    inspection = client.inspect("item-1")

    assert len(drain.steps) == 1
    assert drain.recovery_records == ()
    assert inspection.item is not None
    assert inspection.item.status is QueueItemStatus.SUCCEEDED


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
