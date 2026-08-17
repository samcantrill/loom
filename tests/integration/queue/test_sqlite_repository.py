"""Integration coverage for the SQLite queue repository."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

import pytest

from loom.queue import (
    QUEUE_DB_SCHEMA_VERSION,
    CancellationRecord,
    DispatchHandle,
    LaunchContract,
    QueueConflictError,
    QueueItem,
    QueueItemStatus,
    QueueSchemaError,
    RunIntent,
    SQLiteQueueRepository,
)


def test_sqlite_repository_persists_items_across_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.sqlite"
    repository = SQLiteQueueRepository(db_path)
    item = _item("item-1", "gpu-pool", "2020-01-01T00:00:00Z")

    repository.enqueue(item)
    reopened = SQLiteQueueRepository(db_path)

    assert reopened.read_item("item-1") == item
    with sqlite3.connect(db_path) as connection:
        schema_version = connection.execute(
            "SELECT value FROM queue_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert schema_version == str(QUEUE_DB_SCHEMA_VERSION)


def test_sqlite_repository_claims_fifo_within_pool(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:03Z"),
    )
    repository.enqueue(_item("newer", "gpu-pool", "2020-01-01T00:00:02Z"))
    repository.enqueue(_item("cpu", "cpu-pool", "2020-01-01T00:00:00Z"))
    repository.enqueue(_item("older", "gpu-pool", "2020-01-01T00:00:01Z"))

    claim = repository.claim_next(
        "gpu-pool",
        owner_id="controller-1",
        claim_id="claim-1",
    )

    assert claim is not None
    assert claim.item.queue_item_id == "older"
    assert claim.item.status is QueueItemStatus.CLAIMED
    assert claim.item.claim is not None
    assert claim.item.claim.owner_id == "controller-1"
    assert repository.read_item("older") == claim.item


def test_sqlite_repository_concurrent_claim_has_one_winner(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.sqlite"
    first = SQLiteQueueRepository(db_path)
    second = SQLiteQueueRepository(db_path)
    first.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    barrier = Barrier(2)

    def claim(repository: SQLiteQueueRepository, claim_id: str):
        barrier.wait()
        return repository.claim_next("gpu-pool", owner_id="controller", claim_id=claim_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda pair: claim(*pair),
                ((first, "claim-1"), (second, "claim-2")),
            )
        )

    assert sum(result is not None for result in results) == 1


def test_sqlite_repository_records_dispatch_and_completion(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:03Z"),
    )
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    claim = repository.claim_next(
        "gpu-pool",
        owner_id="controller-1",
        claim_id="claim-1",
    )
    assert claim is not None
    handle = DispatchHandle(
        adapter="local",
        handle_id="pid-1",
        dispatched_at="2020-01-01T00:00:02Z",
        dispatch_attempt=claim.item.dispatch_attempt,
        evidence={"pid": 123},
    )

    dispatched = repository.record_dispatch_handle("item-1", handle)
    completed = repository.complete_item(
        "item-1",
        status=QueueItemStatus.SUCCEEDED,
        reason="authority-run-succeeded",
    )
    events = repository.list_audit_events("item-1")

    assert dispatched.status is QueueItemStatus.DISPATCHED
    assert dispatched.dispatch_handle == handle
    assert completed.status is QueueItemStatus.SUCCEEDED
    assert [event.event_type for event in events] == [
        "queue.item.enqueued",
        "queue.item.claimed",
        "queue.item.dispatched",
        "queue.item.completed",
    ]


def test_sqlite_repository_rejects_completion_before_claim_or_dispatch(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))

    with pytest.raises(QueueConflictError, match="not been dispatched"):
        repository.complete_item(
            "item-1",
            status=QueueItemStatus.SUCCEEDED,
            reason="no-dispatch",
        )


def test_sqlite_repository_rejects_stale_guarded_mutations(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite", clock=_clock("2020-01-01T00:00:01Z")
    )
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    claim = repository.claim_next("gpu-pool", owner_id="controller", claim_id="claim-1")
    assert claim is not None
    repository.defer_item("item-1", reason_code="capacity", expected=claim.item)
    reclaim = repository.claim_next("gpu-pool", owner_id="controller", claim_id="claim-2")
    assert reclaim is not None

    with pytest.raises(QueueConflictError):
        repository.defer_item("item-1", reason_code="capacity", expected=claim.item)
    with pytest.raises(QueueConflictError):
        repository.record_dispatch_handle(
            "item-1",
            DispatchHandle(
                adapter="local",
                handle_id="stale",
                dispatched_at="2020-01-01T00:00:01Z",
                dispatch_attempt=claim.item.dispatch_attempt,
            ),
            expected=claim.item,
        )

    dispatched = repository.record_dispatch_handle(
        "item-1",
        DispatchHandle(
            adapter="local",
            handle_id="current",
            dispatched_at="2020-01-01T00:00:01Z",
            dispatch_attempt=reclaim.item.dispatch_attempt,
        ),
        expected=reclaim.item,
    )
    repository.complete_item(
        "item-1", status=QueueItemStatus.SUCCEEDED, reason="done", expected=dispatched
    )
    with pytest.raises(QueueConflictError):
        repository.complete_item(
            "item-1", status=QueueItemStatus.SUCCEEDED, reason="stale", expected=dispatched
        )
    with pytest.raises(QueueConflictError):
        repository.request_cancellation(
            "item-1",
            CancellationRecord(
                requested_at="2020-01-01T00:00:01Z",
                requested_by="controller",
                reason="stale",
            ),
            expected=dispatched,
        )


def test_sqlite_repository_records_cancellation_and_excludes_recovery(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    cancellation = CancellationRecord(
        requested_at="2020-01-01T00:00:01Z",
        requested_by="controller-1",
        reason="user-request",
        evidence={"adapter": "not-called"},
    )

    cancelled = repository.request_cancellation("item-1", cancellation)

    assert cancelled.status is QueueItemStatus.CANCELLED
    assert cancelled.cancellation == cancellation
    assert repository.scan_recovery() == ()


def test_sqlite_repository_scans_claimed_and_dispatched_recovery(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:01Z"),
    )
    repository.enqueue(_item("claimed", "gpu-pool", "2020-01-01T00:00:00Z"))
    repository.enqueue(_item("dispatched", "gpu-pool", "2020-01-01T00:00:00Z"))
    repository.claim_next("gpu-pool", owner_id="controller-1", claim_id="claim-1")
    second = repository.claim_next(
        "gpu-pool",
        owner_id="controller-1",
        claim_id="claim-2",
    )
    assert second is not None
    repository.record_dispatch_handle(
        second.item.queue_item_id,
        DispatchHandle(
            adapter="local",
            handle_id="pid-2",
            dispatched_at="2020-01-01T00:00:02Z",
            dispatch_attempt=second.item.dispatch_attempt,
        ),
    )

    recovery = repository.scan_recovery()

    assert [record.queue_item_id for record in recovery] == ["claimed", "dispatched"]
    assert [record.status for record in recovery] == [
        QueueItemStatus.CLAIMED,
        QueueItemStatus.DISPATCHED,
    ]


def test_sqlite_repository_rejects_conflicting_enqueue(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))

    with pytest.raises(QueueConflictError, match="already exists"):
        repository.enqueue(_item("item-1", "other-pool", "2020-01-01T00:00:00Z"))


def test_sqlite_repository_rejects_incompatible_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE queue_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO queue_metadata(key, value) VALUES('schema_version', '999')"
        )

    with pytest.raises(QueueSchemaError, match="unsupported queue schema version"):
        SQLiteQueueRepository(db_path)


def _item(item_id: str, pool_name: str, enqueued_at: str) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name=f"{pool_name}-queue",
        pool_name=pool_name,
        run_uri=run_uri,
        run_intent=RunIntent(
            run_uri=run_uri,
            request={"config": f"{item_id}.yaml"},
        ),
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="entry",
            drift_inputs={"config_fingerprint": f"sha256:{item_id}"},
            delegated_verification={"shared_workspace": False},
        ),
        enqueued_at=enqueued_at,
        updated_at=enqueued_at,
    )


def _clock(value: str):
    return lambda: value
