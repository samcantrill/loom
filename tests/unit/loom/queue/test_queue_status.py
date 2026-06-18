"""Unit coverage for queue operational status read models."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.queue import (
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    normalize_queue_spec,
)
from loom.queue.status import build_queue_operational_status


pytestmark = pytest.mark.unit


def test_queue_operational_status_keeps_ownership_sections_separate(
    tmp_path: Path,
) -> None:
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
                "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
            }
        ),
        clock=_clock("2020-01-01T00:00:00Z"),
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )

    report = build_queue_operational_status(service, queue_item_id="item-1")
    payload = report.to_dict()
    item = cast(Mapping[str, object], payload["item"])
    item_payload = cast(Mapping[str, object], item["item"])
    ownership = cast(Mapping[str, str], payload["ownership"])

    assert payload["service_scope"] == "in_process_command"
    assert item_payload["status"] == QueueItemStatus.QUEUED.value
    assert ownership["queue_state"].startswith("queue service owns")
    assert "authority remains" in ownership["authority_state"]
    assert "delegated adapters" in ownership["delegated_scheduler_state"]


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
