"""Integration coverage for the SQLite queue repository."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from pathlib import Path
from typing import Any

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


def test_sqlite_repository_exact_claims_selected_item(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:03Z"),
    )
    repository.enqueue(_item("newer", "gpu-pool", "2020-01-01T00:00:02Z"))
    repository.enqueue(_item("cpu", "cpu-pool", "2020-01-01T00:00:00Z"))
    repository.enqueue(_item("older", "gpu-pool", "2020-01-01T00:00:01Z"))

    claim = _claim(repository, "older", claim_id="claim-1")

    assert claim is not None
    assert claim.queue_item_id == "older"
    assert claim.status is QueueItemStatus.CLAIMED
    assert claim.claim is not None
    assert claim.claim.owner_id == "controller"
    assert repository.read_item("older") == claim


def test_sqlite_repository_concurrent_claim_has_one_winner(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.sqlite"
    first = SQLiteQueueRepository(db_path)
    second = SQLiteQueueRepository(db_path)
    first.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    barrier = Barrier(2)

    def claim(repository: SQLiteQueueRepository, claim_id: str):
        candidate = repository.read_item("item-1")
        assert candidate is not None
        barrier.wait()
        return repository._claim_selection_candidate(
            "item-1",
            pool_name=candidate.pool_name,
            expected_dispatch_attempt=candidate.dispatch_attempt,
            owner_id="controller",
            claim_id=claim_id,
            preference_id="test.fixture",
            reason_code="test.fixture",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda pair: claim(*pair),
                ((first, "claim-1"), (second, "claim-2")),
            )
        )

    assert sum(result is not None for result in results) == 1


def test_sqlite_selection_read_is_bounded_and_exact_claim_has_one_winner(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "queue.sqlite"
    first = SQLiteQueueRepository(db_path)
    second = SQLiteQueueRepository(db_path)
    for item_id, enqueued_at in (
        ("item-1", "2020-01-01T00:00:00Z"),
        ("item-2", "2020-01-01T00:00:01Z"),
        ("item-3", "2020-01-01T00:00:02Z"),
    ):
        first.enqueue(_item(item_id, "gpu-pool", enqueued_at))

    candidates = first._read_selection_candidates("gpu-pool", limit=2)
    assert [candidate.queue_item_id for candidate in candidates] == ["item-1", "item-2"]
    barrier = Barrier(2)

    def claim(repository: SQLiteQueueRepository, claim_id: str):
        barrier.wait()
        return repository._claim_selection_candidate(
            "item-1",
            pool_name="gpu-pool",
            expected_dispatch_attempt=1,
            owner_id="controller",
            claim_id=claim_id,
            preference_id="test.selection",
            reason_code="test.reason",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda pair: claim(*pair),
                ((first, "claim-1"), (second, "claim-2")),
            )
        )

    assert sum(result is not None for result in results) == 1
    events = first.list_audit_events("item-1")
    assert events[-1].detail["selection"] == {
        "preference_id": "test.selection",
        "reason_code": "test.reason",
    }


def test_sqlite_pool_read_snapshot_does_not_mix_a_controlled_transition(
    tmp_path: Path,
) -> None:
    """A selected-pool read remains on one SQLite side of a claim barrier."""
    db_path = tmp_path / "queue.sqlite"
    writer = SQLiteQueueRepository(db_path)
    writer.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    read_started = Event()
    claimed = Event()
    repository = _BarrierSQLiteQueueRepository(db_path, read_started, claimed)

    def claim_after_read_starts() -> None:
        assert read_started.wait(timeout=5)
        assert _claim(writer, "item-1", claim_id="claim-1") is not None
        claimed.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        transition = executor.submit(claim_after_read_starts)
        before = repository.read_pool_snapshot("gpu-pool")
        transition.result(timeout=5)

    assert before.items[0].status is QueueItemStatus.QUEUED
    assert writer.read_pool_snapshot("gpu-pool").items[0].status is QueueItemStatus.CLAIMED


def test_sqlite_repository_records_dispatch_and_completion(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:03Z"),
    )
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    claim = _claim(repository, "item-1", claim_id="claim-1")
    handle = DispatchHandle(
        adapter="local",
        handle_id="pid-1",
        dispatched_at="2020-01-01T00:00:02Z",
        dispatch_attempt=claim.dispatch_attempt,
        evidence={"pid": 123},
    )

    dispatched = repository.record_dispatch_handle(
        "item-1", handle, expected=claim
    )
    completed = repository.complete_item(
        "item-1",
        status=QueueItemStatus.SUCCEEDED,
        reason="authority-run-succeeded",
        expected=dispatched,
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
    queued = repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))

    with pytest.raises(QueueConflictError, match="not been dispatched"):
        repository.complete_item(
            "item-1",
            status=QueueItemStatus.SUCCEEDED,
            reason="no-dispatch",
            expected=queued,
        )


def test_sqlite_repository_rejects_stale_guarded_mutations(tmp_path: Path) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite", clock=_clock("2020-01-01T00:00:01Z")
    )
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    claim = _claim(repository, "item-1", claim_id="claim-1")
    repository.defer_item("item-1", reason_code="capacity", expected=claim)
    reclaim = _claim(repository, "item-1", claim_id="claim-2")

    with pytest.raises(QueueConflictError):
        repository.defer_item("item-1", reason_code="capacity", expected=claim)
    with pytest.raises(QueueConflictError):
        repository.record_dispatch_handle(
            "item-1",
            DispatchHandle(
                adapter="local",
                handle_id="stale",
                dispatched_at="2020-01-01T00:00:01Z",
            dispatch_attempt=claim.dispatch_attempt,
            ),
            expected=claim,
        )

    dispatched = repository.record_dispatch_handle(
        "item-1",
        DispatchHandle(
            adapter="local",
            handle_id="current",
            dispatched_at="2020-01-01T00:00:01Z",
            dispatch_attempt=reclaim.dispatch_attempt,
        ),
        expected=reclaim,
    )
    repository.complete_item(
        "item-1", status=QueueItemStatus.SUCCEEDED, reason="done", expected=dispatched
    )
    with pytest.raises(QueueConflictError):
        repository.complete_item(
            "item-1",
            status=QueueItemStatus.SUCCEEDED,
            reason="stale",
            expected=dispatched,
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


def test_sqlite_repository_requires_snapshot_for_active_cancellation(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite")
    repository.enqueue(_item("item-1", "gpu-pool", "2020-01-01T00:00:00Z"))
    _claim(repository, "item-1", claim_id="claim-1")
    cancellation = CancellationRecord(
        requested_at="2020-01-01T00:00:01Z",
        requested_by="controller-1",
        reason="user-request",
    )

    with pytest.raises(QueueConflictError, match="requires an expected snapshot"):
        repository.request_cancellation("item-1", cancellation)


def test_sqlite_repository_scans_claimed_and_dispatched_recovery(
    tmp_path: Path,
) -> None:
    repository = SQLiteQueueRepository(
        tmp_path / "queue.sqlite",
        clock=_clock("2020-01-01T00:00:01Z"),
    )
    repository.enqueue(_item("claimed", "gpu-pool", "2020-01-01T00:00:00Z"))
    repository.enqueue(_item("dispatched", "gpu-pool", "2020-01-01T00:00:00Z"))
    _claim(repository, "claimed", claim_id="claim-1")
    second = _claim(repository, "dispatched", claim_id="claim-2")
    repository.record_dispatch_handle(
        second.queue_item_id,
        DispatchHandle(
            adapter="local",
            handle_id="pid-2",
            dispatched_at="2020-01-01T00:00:02Z",
            dispatch_attempt=second.dispatch_attempt,
        ),
        expected=second,
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


class _BarrierSQLiteQueueRepository(SQLiteQueueRepository):
    def __init__(self, db_path: Path, read_started: Event, claimed: Event) -> None:
        self._read_started = read_started
        self._claimed = claimed
        super().__init__(db_path)

    def _connect(self) -> Any:
        return _ReadBarrierConnection(
            super()._connect(), self._read_started, self._claimed
        )


class _ReadBarrierConnection:
    def __init__(self, connection: Any, read_started: Event, claimed: Event) -> None:
        self._connection = connection
        self._read_started = read_started
        self._claimed = claimed

    def __enter__(self) -> "_ReadBarrierConnection":
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._connection.__exit__(*args)

    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Any:
        cursor = self._connection.execute(statement, parameters)
        if "FROM queue_items" in statement and "pool_name" in statement:
            self._read_started.set()
            assert self._claimed.wait(timeout=5)
        return cursor


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


def _claim(repository: SQLiteQueueRepository, item_id: str, *, claim_id: str) -> QueueItem:
    candidate = repository.read_item(item_id)
    assert candidate is not None
    claimed = repository._claim_selection_candidate(
        item_id,
        pool_name=candidate.pool_name,
        expected_dispatch_attempt=candidate.dispatch_attempt,
        owner_id="controller",
        claim_id=claim_id,
        preference_id="test.fixture",
        reason_code="test.fixture",
    )
    assert claimed is not None
    return claimed


def _clock(value: str):
    return lambda: value
