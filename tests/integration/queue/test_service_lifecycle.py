"""Integration coverage for queue service lifecycle behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    _claim_fixture(first, "item-1", claim_id="claim-1")

    restarted = QueueService.from_spec(spec, clock=clock)
    status = restarted.start()

    assert status.state is QueueServiceState.RUNNING
    assert [record.queue_item_id for record in status.recovery_records] == ["item-1"]
    assert status.recovery_records[0].status is QueueItemStatus.CLAIMED


def test_queue_service_omits_absent_completion_evidence_for_legacy_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
        }
    )
    service = QueueService.from_spec(spec, clock=lambda: "2020-01-01T00:00:01Z")
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )
    claim = _claim_fixture(service, "item-1", claim_id="claim-1")
    repository = service.repository
    complete_item = repository.complete_item

    def legacy_complete_item(queue_item_id, *, status, reason, expected):  # noqa: ANN001, ANN202
        return complete_item(
            queue_item_id,
            status=status,
            reason=reason,
            expected=expected,
        )

    monkeypatch.setattr(repository, "complete_item", legacy_complete_item)

    completed = service.complete_item(
        "item-1",
        status=QueueItemStatus.UNKNOWN,
        reason="legacy-compatible",
        expected=claim,
    )

    assert completed.status is QueueItemStatus.UNKNOWN


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value


def _claim_fixture(service: QueueService, item_id: str, *, claim_id: str):
    item = service.read_item(item_id)
    assert item is not None
    claimed = service.repository._claim_selection_candidate(
        item_id,
        pool_name=item.pool_name,
        expected_dispatch_attempt=item.dispatch_attempt,
        owner_id="controller-1",
        claim_id=claim_id,
        preference_id="test.fixture",
        reason_code="test.fixture",
    )
    assert claimed is not None
    return claimed
