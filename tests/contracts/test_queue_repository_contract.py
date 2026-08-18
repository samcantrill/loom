"""Contract coverage for queue repository operations."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    LaunchContract,
    QueueClaimResult,
    QueueItem,
    QueueItemStatus,
    QueueRepository,
    RunIntent,
    SQLiteQueueRepository,
)


def test_sqlite_queue_repository_satisfies_repository_protocol(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")

    assert isinstance(repository, QueueRepository)


def test_queue_repository_claim_contract_returns_claimed_item(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    repository.enqueue(_item("item-1", "2020-01-01T00:00:00Z"))

    result = repository.claim_next(
        "gpu-pool",
        owner_id="controller-1",
        claim_id="claim-1",
    )

    assert isinstance(result, QueueClaimResult)
    assert result.item is not None
    assert result.item.status is QueueItemStatus.CLAIMED
    assert result.item.claim is not None
    assert result.item.claim.claim_id == "claim-1"
    assert result.item.dispatch_attempt == 1


def test_queue_repository_deferral_preserves_fifo_identity(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite", clock=lambda: "2020-01-01T00:00:01Z"
    )
    repository.enqueue(_item("item-1", "2020-01-01T00:00:00Z"))
    claim_result = repository.claim_next(
        "gpu-pool", owner_id="controller-1", claim_id="claim-1"
    )
    assert isinstance(claim_result, QueueClaimResult)
    assert claim_result.item is not None
    claimed = claim_result.item

    deferred = repository.defer_item("item-1", reason_code="capacity", expected=claimed)

    assert deferred.status is QueueItemStatus.QUEUED
    assert deferred.claim is None
    assert deferred.dispatch_attempt == claimed.dispatch_attempt
    assert [event.event_type for event in repository.list_audit_events("item-1")] == [
        "queue.item.enqueued",
        "queue.item.claimed",
        "queue.item.deferred",
    ]


def test_queue_repository_pool_snapshot_is_ordered_and_protocol_visible(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")
    repository.enqueue(_item("item-2", "2020-01-01T00:00:02Z"))
    repository.enqueue(_item("item-1", "2020-01-01T00:00:01Z"))

    snapshot = repository.read_pool_snapshot("gpu-pool")

    assert snapshot.pool_name == "gpu-pool"
    assert [item.queue_item_id for item in snapshot.items] == ["item-1", "item-2"]


def test_queue_repository_completion_evidence_is_optional_and_guarded(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite", clock=lambda: "2020-01-01T00:00:01Z"
    )
    repository.enqueue(_item("item-1", "2020-01-01T00:00:00Z"))
    claim = repository.claim_next(
        "gpu-pool", owner_id="controller-1", claim_id="claim-1"
    )
    assert claim is not None

    completed = repository.complete_item(
        "item-1",
        status=QueueItemStatus.UNKNOWN,
        reason="operator-recovery",
        expected=claim.item,
        evidence={"recovery": {"attested": True}},
    )

    assert completed.status is QueueItemStatus.UNKNOWN
    assert repository.list_audit_events("item-1")[-1].detail == {
        "status": "UNKNOWN",
        "reason": "operator-recovery",
        "evidence": {"recovery": {"attested": True}},
    }


def _item(item_id: str, enqueued_at: str) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name="gpu",
        pool_name="gpu-pool",
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(adapter="local", entrypoint="entry"),
        enqueued_at=enqueued_at,
        updated_at=enqueued_at,
    )
