"""SQLite-backed queue repository."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from loom.serialization import PlainData, json_loads, stable_json_dumps
from loom.timestamps import utc_timestamp

from .errors import QueueConflictError, QueueSchemaError, QueueStorageError
from .models import (
    CancellationRecord,
    DispatchHandle,
    QueueAuditEvent,
    QueueClaim,
    QueueEnqueueDisposition,
    QueueEnqueueReceipt,
    QueueItem,
    QueueItemStatus,
    QueueRecoveryRecord,
    validate_queue_id,
)
from .repository import QueueItemPage, QueuePoolSnapshot

QUEUE_DB_SCHEMA_VERSION = 2
_BUSY_TIMEOUT_MS = 5000
_ACTIVE_RECOVERY_STATUSES = (
    QueueItemStatus.CLAIMED,
    QueueItemStatus.DISPATCHED,
)
_COMPLETION_STATUSES = frozenset(
    {
        QueueItemStatus.SUCCEEDED,
        QueueItemStatus.FAILED,
        QueueItemStatus.UNKNOWN,
    }
)


class SQLiteQueueRepository:
    """Built-in SQLite queue repository for workspace-scoped queue state."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        self._read_only = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            _ensure_schema(conn)

    @classmethod
    def open_read_only(cls, db_path: str | Path) -> "SQLiteQueueRepository":
        """Open one existing queue database without creating or changing it."""

        path = Path(db_path)
        if not path.is_file():
            raise QueueStorageError("queue repository does not exist")
        repository = cls.__new__(cls)
        repository.db_path = path
        repository._clock = utc_timestamp
        repository._read_only = True
        with repository._connect() as conn:
            _verify_schema(conn)
        return repository

    def enqueue(self, item: QueueItem) -> QueueItem:
        """Compatibility operation returning the canonical queue item only."""

        return self.admit(item).queue_item

    def admit(self, item: QueueItem) -> QueueEnqueueReceipt:
        """Classify one immutable enqueue in one SQLite transaction."""

        if QueueItemStatus(item.status) is not QueueItemStatus.QUEUED:
            raise QueueConflictError("only QUEUED items can be enqueued")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT item_json FROM queue_items WHERE queue_item_id = ?",
                (item.queue_item_id,),
            ).fetchone()
            if existing is not None:
                existing_item = _item_from_json(cast(str, existing["item_json"]))
                if existing_item.admission_digest == item.admission_digest:
                    return _receipt(
                        QueueEnqueueDisposition.SUBMISSION_REPLAY,
                        requested_queue_item_id=item.queue_item_id,
                        queue_item=existing_item,
                    )
                raise QueueConflictError(
                    f"queue item already exists: {item.queue_item_id}"
                )
            if (
                item.scientific_fingerprint is not None
                and not item.scientific_deduplication_bypassed
            ):
                scientific_match = conn.execute(
                    """
                    SELECT item_json
                    FROM queue_items
                    WHERE scientific_fingerprint = ?
                      AND scientific_deduplication_bypassed = 0
                    """,
                    (item.scientific_fingerprint,),
                ).fetchone()
                if scientific_match is not None:
                    canonical_item = _item_from_json(
                        cast(str, scientific_match["item_json"])
                    )
                    return _receipt(
                        QueueEnqueueDisposition.SCIENTIFIC_DUPLICATE,
                        requested_queue_item_id=item.queue_item_id,
                        queue_item=canonical_item,
                    )
            _insert_item(conn, item)
            _append_audit_event(
                conn,
                queue_item_id=item.queue_item_id,
                event_type="queue.item.enqueued",
                timestamp=item.enqueued_at,
                detail={
                    "queue_name": item.queue_name,
                    "pool_name": item.pool_name,
                    "run_uri": item.run_uri,
                },
            )
            conn.commit()
            return _receipt(
                QueueEnqueueDisposition.ENQUEUED,
                requested_queue_item_id=item.queue_item_id,
                queue_item=item,
            )

    def read_item(self, queue_item_id: str) -> QueueItem | None:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT item_json FROM queue_items WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
        if row is None:
            return None
        return _item_from_json(cast(str, row["item_json"]))

    def read_pool_snapshot(self, pool_name: str) -> QueuePoolSnapshot:
        """Read all selected-pool rows from one SQLite snapshot.

        Counts are deliberately derived by the status read model from these
        same rows, avoiding a separately-raced aggregate query.
        """

        pool_name = validate_queue_id(pool_name, "pool_name")
        with self._connect() as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                """
                SELECT item_json
                FROM queue_items
                WHERE pool_name = ?
                ORDER BY enqueued_at, queue_item_id
                """,
                (pool_name,),
            ).fetchall()
        return QueuePoolSnapshot(
            pool_name=pool_name,
            items=tuple(_item_from_json(cast(str, row["item_json"])) for row in rows),
        )

    def list_items(self, *, limit: int, cursor: str | None = None) -> QueueItemPage:
        """Read a bounded FIFO page without routing through status summaries."""

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 0 < limit <= 1000
        ):
            raise QueueConflictError("list limit must be an integer between 1 and 1000")
        cursor_parts = _decode_cursor(cursor)
        query = """
            SELECT item_json, enqueued_at, queue_item_id
            FROM queue_items
        """
        values: tuple[object, ...] = ()
        if cursor_parts is not None:
            query += """
                WHERE enqueued_at > ?
                   OR (enqueued_at = ? AND queue_item_id > ?)
            """
            values = (cursor_parts[0], cursor_parts[0], cursor_parts[1])
        query += " ORDER BY enqueued_at, queue_item_id LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (*values, limit + 1)).fetchall()
        page_rows = rows[:limit]
        items = tuple(_item_from_json(cast(str, row["item_json"])) for row in page_rows)
        next_cursor = None
        if len(rows) > limit and page_rows:
            last = page_rows[-1]
            next_cursor = _encode_cursor(
                cast(str, last["enqueued_at"]), cast(str, last["queue_item_id"])
            )
        return QueueItemPage(items=items, next_cursor=next_cursor)

    def _read_selection_candidates(
        self, pool_name: str, *, limit: int
    ) -> tuple[QueueItem, ...]:
        """Read one bounded FIFO window for private managed selection."""

        pool_name = validate_queue_id(pool_name, "pool_name")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise QueueConflictError("selection limit must be a positive integer")
        with self._connect() as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                """
                SELECT item_json
                FROM queue_items
                WHERE pool_name = ? AND status = ?
                ORDER BY enqueued_at, queue_item_id
                LIMIT ?
                """,
                (pool_name, QueueItemStatus.QUEUED.value, limit),
            ).fetchall()
        return tuple(_item_from_json(cast(str, row["item_json"])) for row in rows)

    def _claim_selection_candidate(
        self,
        queue_item_id: str,
        *,
        pool_name: str,
        expected_dispatch_attempt: int,
        owner_id: str,
        claim_id: str,
        preference_id: str,
        reason_code: str,
    ) -> QueueItem | None:
        """Atomically claim exactly one previously selected queued item."""

        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        pool_name = validate_queue_id(pool_name, "pool_name")
        owner_id = validate_queue_id(owner_id, "owner_id")
        claim_id = validate_queue_id(claim_id, "claim_id")
        if (
            not isinstance(expected_dispatch_attempt, int)
            or isinstance(expected_dispatch_attempt, bool)
            or expected_dispatch_attempt <= 0
        ):
            raise QueueConflictError(
                "expected_dispatch_attempt must be a positive integer"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT item_json
                FROM queue_items
                WHERE queue_item_id = ? AND pool_name = ? AND status = ?
                    AND dispatch_attempt = ?
                """,
                (
                    queue_item_id,
                    pool_name,
                    QueueItemStatus.QUEUED.value,
                    expected_dispatch_attempt,
                ),
            ).fetchone()
            if row is None:
                return None
            current = _item_from_json(cast(str, row["item_json"]))
            now = self._clock()
            claim = QueueClaim(
                claim_id=claim_id,
                owner_id=owner_id,
                claimed_at=now,
                dispatch_attempt=current.dispatch_attempt,
            )
            claimed = replace(
                current,
                status=QueueItemStatus.CLAIMED,
                claim=claim,
                updated_at=now,
            )
            if _update_item(conn, claimed, expected=current) != 1:
                return None
            _append_audit_event(
                conn,
                queue_item_id=claimed.queue_item_id,
                event_type="queue.item.claimed",
                timestamp=now,
                detail={
                    "claim_id": claim.claim_id,
                    "owner_id": claim.owner_id,
                    "dispatch_attempt": claim.dispatch_attempt,
                    "selection": {
                        "preference_id": preference_id,
                        "reason_code": reason_code,
                    },
                },
            )
            conn.commit()
            return claimed

    def record_dispatch_handle(
        self,
        queue_item_id: str,
        handle: DispatchHandle,
        *,
        expected: QueueItem,
    ) -> QueueItem:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        with self._connect() as conn:
            current = _require_item(conn, queue_item_id)
            _verify_expected(current, expected)
            if QueueItemStatus(current.status) is not QueueItemStatus.CLAIMED:
                raise QueueConflictError("queue item is not claimed")
            if handle.dispatch_attempt != current.dispatch_attempt:
                raise QueueConflictError("dispatch handle attempt does not match item")
            updated = replace(
                current,
                status=QueueItemStatus.DISPATCHED,
                dispatch_handle=handle,
                updated_at=handle.dispatched_at,
            )
            if _update_item(conn, updated, expected=current) != 1:
                raise QueueConflictError("queue item dispatch handle conflicted")
            _append_audit_event(
                conn,
                queue_item_id=updated.queue_item_id,
                event_type="queue.item.dispatched",
                timestamp=handle.dispatched_at,
                detail={
                    "adapter": handle.adapter,
                    "handle_id": handle.handle_id,
                    "dispatch_attempt": handle.dispatch_attempt,
                },
            )
            conn.commit()
            return updated

    def complete_item(
        self,
        queue_item_id: str,
        *,
        status: QueueItemStatus,
        reason: str,
        expected: QueueItem,
        evidence: Mapping[str, PlainData] | None = None,
    ) -> QueueItem:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        status = QueueItemStatus(status)
        if status not in _COMPLETION_STATUSES:
            raise QueueConflictError(
                "completion status must be SUCCEEDED, FAILED, or UNKNOWN"
            )
        with self._connect() as conn:
            current = _require_item(conn, queue_item_id)
            _verify_expected(current, expected)
            if current.terminal:
                raise QueueConflictError("queue item is already terminal")
            if QueueItemStatus(current.status) not in {
                QueueItemStatus.CLAIMED,
                QueueItemStatus.DISPATCHED,
            }:
                raise QueueConflictError("queue item has not been dispatched")
            now = self._clock()
            updated = replace(current, status=status, updated_at=now)
            if _update_item(conn, updated, expected=current) != 1:
                raise QueueConflictError("queue item completion conflicted")
            detail: dict[str, PlainData] = {"status": status.value, "reason": reason}
            if evidence is not None:
                detail["evidence"] = dict(evidence)
            _append_audit_event(
                conn,
                queue_item_id=updated.queue_item_id,
                event_type="queue.item.completed",
                timestamp=now,
                detail=detail,
            )
            conn.commit()
            return updated

    def request_cancellation(
        self,
        queue_item_id: str,
        cancellation: CancellationRecord,
        *,
        expected: QueueItem | None = None,
    ) -> QueueItem:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        with self._connect() as conn:
            current = _require_item(conn, queue_item_id)
            _verify_expected(current, expected)
            if current.terminal:
                raise QueueConflictError("queue item is already terminal")
            if (
                QueueItemStatus(current.status)
                in {QueueItemStatus.CLAIMED, QueueItemStatus.DISPATCHED}
                and expected is None
            ):
                raise QueueConflictError(
                    "active queue item cancellation requires an expected snapshot"
                )
            updated = replace(
                current,
                status=QueueItemStatus.CANCELLED,
                cancellation=cancellation,
                updated_at=cancellation.requested_at,
            )
            if _update_item(conn, updated, expected=current) != 1:
                raise QueueConflictError("queue item cancellation conflicted")
            _append_audit_event(
                conn,
                queue_item_id=updated.queue_item_id,
                event_type="queue.item.cancelled",
                timestamp=cancellation.requested_at,
                detail={
                    "requested_by": cancellation.requested_by,
                    "reason": cancellation.reason,
                    "evidence": cancellation.to_dict()["evidence"],
                },
            )
            conn.commit()
            return updated

    def defer_item(
        self,
        queue_item_id: str,
        *,
        reason_code: str,
        expected: QueueItem,
    ) -> QueueItem:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        if not isinstance(reason_code, str) or not reason_code:
            raise QueueConflictError("defer reason_code must be a non-empty string")
        with self._connect() as conn:
            current = _require_item(conn, queue_item_id)
            _verify_expected(current, expected)
            if QueueItemStatus(current.status) is not QueueItemStatus.CLAIMED:
                raise QueueConflictError("only claimed queue items can be deferred")
            now = self._clock()
            deferred = replace(
                current,
                status=QueueItemStatus.QUEUED,
                claim=None,
                dispatch_handle=None,
                updated_at=now,
            )
            if _update_item(conn, deferred, expected=current) != 1:
                raise QueueConflictError("queue item deferral conflicted")
            _append_audit_event(
                conn,
                queue_item_id=queue_item_id,
                event_type="queue.item.deferred",
                timestamp=now,
                detail={"reason_code": reason_code},
            )
            conn.commit()
            return deferred

    def scan_recovery(
        self, *, limit: int | None = None, pool_name: str | None = None
    ) -> tuple[QueueRecoveryRecord, ...]:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        ):
            raise QueueConflictError(
                "recovery limit must be a positive integer or None"
            )
        if pool_name is not None:
            pool_name = validate_queue_id(pool_name, "pool_name")
        where_pool = "" if pool_name is None else " AND pool_name = ?"
        suffix = "" if limit is None else " LIMIT ?"
        parameters: list[str | int] = [
            status.value for status in _ACTIVE_RECOVERY_STATUSES
        ]
        if pool_name is not None:
            parameters.append(pool_name)
        if limit is not None:
            parameters.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT queue_item_id, status, dispatch_attempt, item_json
                FROM queue_items
                WHERE status IN (?, ?)
                """
                + where_pool
                + """
                ORDER BY updated_at, queue_item_id
                """
                + suffix,
                tuple(parameters),
            ).fetchall()
        records: list[QueueRecoveryRecord] = []
        for row in rows:
            item = _item_from_json(cast(str, row["item_json"]))
            detail: dict[str, PlainData] = {
                "pool_name": item.pool_name,
                "queue_name": item.queue_name,
                "run_uri": item.run_uri,
            }
            if item.claim is not None:
                detail["claim_id"] = item.claim.claim_id
                detail["owner_id"] = item.claim.owner_id
            if item.dispatch_handle is not None:
                detail["handle_id"] = item.dispatch_handle.handle_id
                detail["adapter"] = item.dispatch_handle.adapter
            records.append(
                QueueRecoveryRecord(
                    queue_item_id=cast(str, row["queue_item_id"]),
                    status=cast(str, row["status"]),
                    dispatch_attempt=cast(int, row["dispatch_attempt"]),
                    detail=detail,
                )
            )
        return tuple(records)

    def list_audit_events(self, queue_item_id: str) -> tuple[QueueAuditEvent, ...]:
        queue_item_id = validate_queue_id(queue_item_id, "queue_item_id")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_json
                FROM queue_audit_events
                WHERE queue_item_id = ?
                ORDER BY sequence
                """,
                (queue_item_id,),
            ).fetchall()
        return tuple(
            _audit_event_from_json(cast(str, row["event_json"])) for row in rows
        )

    def _connect(self) -> Any:
        sqlite = _sqlite3()
        read_only = self._read_only
        try:
            connection = sqlite.connect(
                (
                    f"{self.db_path.resolve(strict=False).as_uri()}?mode=ro"
                    if read_only
                    else str(self.db_path)
                ),
                timeout=_BUSY_TIMEOUT_MS / 1000,
                uri=read_only,
            )
            connection.row_factory = sqlite.Row
            connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            if not read_only:
                try:
                    connection.execute("PRAGMA journal_mode=WAL")
                except sqlite.DatabaseError:
                    pass
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite.DatabaseError as exc:
            raise QueueStorageError(f"unable to open queue repository: {exc}") from exc


def _ensure_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    row = conn.execute(
        "SELECT value FROM queue_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        _create_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO queue_metadata(key, value)
            VALUES('schema_version', ?)
            """,
            (str(QUEUE_DB_SCHEMA_VERSION),),
        )
        conn.commit()
        return
    if row["value"] != str(QUEUE_DB_SCHEMA_VERSION):
        raise QueueSchemaError(
            f"unsupported queue schema version {row['value']}; "
            f"expected {QUEUE_DB_SCHEMA_VERSION}"
        )


def _verify_schema(conn: Any) -> None:
    try:
        row = conn.execute(
            "SELECT value FROM queue_metadata WHERE key = 'schema_version'"
        ).fetchone()
    except Exception as exc:
        raise QueueSchemaError("queue repository schema is missing") from exc
    if row is None or row["value"] != str(QUEUE_DB_SCHEMA_VERSION):
        actual = None if row is None else row["value"]
        raise QueueSchemaError(
            f"unsupported queue schema version {actual}; "
            f"expected {QUEUE_DB_SCHEMA_VERSION}"
        )


def _create_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_items (
            queue_item_id TEXT PRIMARY KEY,
            queue_name TEXT NOT NULL,
            pool_name TEXT NOT NULL,
            run_uri TEXT NOT NULL,
            status TEXT NOT NULL,
            dispatch_attempt INTEGER NOT NULL,
            enqueued_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            admission_digest TEXT NOT NULL,
            scientific_fingerprint TEXT,
            scientific_deduplication_bypassed INTEGER NOT NULL,
            item_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS queue_items_fifo_idx
        ON queue_items(pool_name, status, enqueued_at, queue_item_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS queue_items_listing_idx
        ON queue_items(enqueued_at, queue_item_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS queue_items_scientific_identity_idx
        ON queue_items(scientific_fingerprint)
        WHERE scientific_fingerprint IS NOT NULL
          AND scientific_deduplication_bypassed = 0
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            queue_item_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_json TEXT NOT NULL,
            FOREIGN KEY(queue_item_id)
                REFERENCES queue_items(queue_item_id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS queue_audit_events_item_idx
        ON queue_audit_events(queue_item_id, sequence)
        """
    )


def _insert_item(conn: Any, item: QueueItem, *, item_json: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO queue_items (
            queue_item_id, queue_name, pool_name, run_uri, status,
            dispatch_attempt, enqueued_at, updated_at, admission_digest,
            scientific_fingerprint, scientific_deduplication_bypassed, item_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _item_row_values(item, item_json=item_json),
    )


def _update_item(
    conn: Any, item: QueueItem, *, expected: QueueItem | None = None
) -> int:
    query = """
        UPDATE queue_items
        SET queue_name = ?, pool_name = ?, run_uri = ?, status = ?,
            dispatch_attempt = ?, enqueued_at = ?, updated_at = ?, admission_digest = ?,
            scientific_fingerprint = ?, scientific_deduplication_bypassed = ?,
            item_json = ?
        WHERE queue_item_id = ?
    """
    values: list[object] = [
        item.queue_name,
        item.pool_name,
        item.run_uri,
        QueueItemStatus(item.status).value,
        item.dispatch_attempt,
        item.enqueued_at,
        item.updated_at,
        item.admission_digest,
        item.scientific_fingerprint,
        int(item.scientific_deduplication_bypassed),
        _item_json(item),
        item.queue_item_id,
    ]
    if expected is not None:
        query += " AND item_json = ?"
        values.append(_item_json(expected))
    cursor = conn.execute(query, tuple(values))
    return int(cursor.rowcount)


def _verify_expected(current: QueueItem, expected: QueueItem | None) -> None:
    if expected is not None and current != expected:
        raise QueueConflictError("queue item mutation conflicted with a stale snapshot")


def _item_row_values(
    item: QueueItem, *, item_json: str | None = None
) -> tuple[object, ...]:
    return (
        item.queue_item_id,
        item.queue_name,
        item.pool_name,
        item.run_uri,
        QueueItemStatus(item.status).value,
        item.dispatch_attempt,
        item.enqueued_at,
        item.updated_at,
        item.admission_digest,
        item.scientific_fingerprint,
        int(item.scientific_deduplication_bypassed),
        _item_json(item) if item_json is None else item_json,
    )


def _require_item(conn: Any, queue_item_id: str) -> QueueItem:
    row = conn.execute(
        "SELECT item_json FROM queue_items WHERE queue_item_id = ?",
        (queue_item_id,),
    ).fetchone()
    if row is None:
        raise QueueConflictError(f"unknown queue item: {queue_item_id}")
    return _item_from_json(cast(str, row["item_json"]))


def _append_audit_event(
    conn: Any,
    *,
    queue_item_id: str,
    event_type: str,
    timestamp: str,
    detail: dict[str, PlainData],
) -> QueueAuditEvent:
    cursor = conn.execute(
        """
        INSERT INTO queue_audit_events (
            event_id, queue_item_id, event_type, timestamp, event_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        ("pending", queue_item_id, event_type, timestamp, "{}"),
    )
    sequence = int(cursor.lastrowid)
    event = QueueAuditEvent(
        event_id=f"{queue_item_id}:{sequence}",
        queue_item_id=queue_item_id,
        event_type=event_type,
        timestamp=timestamp,
        sequence=sequence,
        detail=detail,
    )
    conn.execute(
        """
        UPDATE queue_audit_events
        SET event_id = ?, event_json = ?
        WHERE sequence = ?
        """,
        (event.event_id, _audit_event_json(event), sequence),
    )
    return event


def _item_json(item: QueueItem) -> str:
    return stable_json_dumps(item.to_dict())


def _item_from_json(text: str) -> QueueItem:
    return QueueItem.from_dict(json_loads(text, path="QueueItem"))


def _receipt(
    disposition: QueueEnqueueDisposition,
    *,
    requested_queue_item_id: str,
    queue_item: QueueItem,
) -> QueueEnqueueReceipt:
    return QueueEnqueueReceipt(
        disposition=disposition,
        requested_queue_item_id=requested_queue_item_id,
        canonical_queue_item_id=queue_item.queue_item_id,
        queue_item=queue_item,
        accepted_at=queue_item.enqueued_at,
    )


def _encode_cursor(enqueued_at: str, queue_item_id: str) -> str:
    return f"{enqueued_at}|{queue_item_id}"


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str):
        raise QueueConflictError("list cursor must be a string or None")
    try:
        enqueued_at, queue_item_id = cursor.rsplit("|", 1)
    except ValueError as exc:
        raise QueueConflictError("list cursor is invalid") from exc
    if not enqueued_at or not queue_item_id:
        raise QueueConflictError("list cursor is invalid")
    validate_queue_id(queue_item_id, "cursor queue_item_id")
    return enqueued_at, queue_item_id


def _audit_event_json(event: QueueAuditEvent) -> str:
    return stable_json_dumps(event.to_dict())


def _audit_event_from_json(text: str) -> QueueAuditEvent:
    return QueueAuditEvent.from_dict(json_loads(text, path="QueueAuditEvent"))


def _sqlite3() -> ModuleType:
    try:
        import sqlite3
    except ModuleNotFoundError as exc:
        raise QueueStorageError(
            "sqlite3 is required for SQLiteQueueRepository"
        ) from exc
    return sqlite3


__all__ = [
    "QUEUE_DB_SCHEMA_VERSION",
    "SQLiteQueueRepository",
]
