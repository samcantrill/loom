"""Contract coverage for queue repository operations."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    LaunchContract,
    QueueItem,
    QueueItemStatus,
    QueueRepository,
    RunIntent,
    SQLiteQueueRepository,
)


def test_sqlite_queue_repository_satisfies_repository_protocol(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")

    assert isinstance(repository, QueueRepository)


def test_queue_repository_does_not_publish_implicit_fifo_ownership(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    assert not hasattr(QueueRepository, "claim" "_next")
    assert not hasattr(repository, "claim" "_next")


def test_queue_repository_deferral_preserves_fifo_identity(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite", clock=lambda: "2020-01-01T00:00:01Z"
    )
    repository.enqueue(_item("item-1", "2020-01-01T00:00:00Z"))
    claimed = _claim(repository, "item-1", claim_id="claim-1")

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
    claim = _claim(repository, "item-1", claim_id="claim-1")

    completed = repository.complete_item(
        "item-1",
        status=QueueItemStatus.UNKNOWN,
        reason="operator-recovery",
        expected=claim,
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


def _claim(repository: SQLiteQueueRepository, item_id: str, *, claim_id: str) -> QueueItem:
    candidate = repository.read_item(item_id)
    assert candidate is not None
    claimed = repository._claim_selection_candidate(
        item_id,
        pool_name="gpu-pool",
        expected_dispatch_attempt=candidate.dispatch_attempt,
        owner_id="controller-1",
        claim_id=claim_id,
        preference_id="test.fixture",
        reason_code="test.fixture",
    )
    assert claimed is not None
    return claimed
