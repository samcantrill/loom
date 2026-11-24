"""Process-local change hints; committed SQLite state remains authoritative."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Literal

from .errors import QueueServiceError
import sqlite3
from threading import Condition


class _ChangeSignal:
    def __init__(self) -> None:
        self._condition = Condition()
        self._generation = 0
        self._closed = False

    def snapshot(self) -> int:
        with self._condition:
            return self._generation

    def notify(self) -> None:
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def wait_for_change(self, observed: int, timeout: float) -> None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._closed or self._generation != observed,
                timeout=timeout,
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class _ServiceSignal(_ChangeSignal):
    """Change signal retaining the scheduler's existing callback interface."""

    def set(self) -> None:
        self.notify()


class _KeyedWaiters:
    """A process-local generation shared only by subscribers to the same key."""

    signal_type = _ChangeSignal

    def __init__(self) -> None:
        self._condition = Condition()
        self._subscribers: dict[str, tuple[_ChangeSignal, int]] = {}
        self._closed = False

    @contextmanager
    def subscribe(self, key: str) -> Iterator[_ChangeSignal]:
        with self._condition:
            if self._closed:
                raise QueueServiceError("coordinator is stopping")
            entry = self._subscribers.get(key)
            signal, count = (self.signal_type(), 0) if entry is None else entry
            self._subscribers[key] = signal, count + 1
        try:
            yield signal
        finally:
            with self._condition:
                _, count = self._subscribers[key]
                if count == 1:
                    del self._subscribers[key]
                    self._condition.notify_all()
                else:
                    self._subscribers[key] = signal, count - 1

    def notify(self, key: str) -> None:
        with self._condition:
            subscriber = self._subscribers.get(key)
        if subscriber is not None:
            subscriber[0].notify()

    def notify_all(self) -> None:
        with self._condition:
            signals = tuple(item[0] for item in self._subscribers.values())
        for signal in signals:
            signal.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            signals = tuple(item[0] for item in self._subscribers.values())
        for signal in signals:
            signal.close()

    def drain(self) -> None:
        # Call without the daemon cycle lock: handlers need it for shutdown
        # detection and finish their exact poll cleanup before unsubscribing.
        with self._condition:
            self._condition.wait_for(lambda: not self._subscribers)


class _ChangeConnection(sqlite3.Connection):
    """Collect only changed projection identities in the originating transaction."""

    on_commit: Callable[[str], None] | None = None
    _transaction_id = 0
    _pending = False
    _create_buffer = (
        "CREATE TEMP TABLE IF NOT EXISTS loom_status_keys "
        "(generation INTEGER, key TEXT, PRIMARY KEY (generation, key)) WITHOUT ROWID"
    )

    def retain_keys(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        # A savepoint rollback can remove the temporary table or its rows.
        self.execute(self._create_buffer)
        if not self._pending:
            self.execute("DELETE FROM temp.loom_status_keys WHERE generation != ?", (self._transaction_id,))
        self.executemany("INSERT OR IGNORE INTO temp.loom_status_keys VALUES (?, ?)",
                         ((self._transaction_id, key) for key in keys))
        self._pending = True

    def commit(self) -> None:
        keys = ()
        if self._pending:
            self.execute(self._create_buffer)
            keys = tuple(row[0] for row in self.execute(
                "SELECT key FROM temp.loom_status_keys WHERE generation = ?", (self._transaction_id,),
            ))
        super().commit()
        self._pending = False
        self._transaction_id += 1
        if self.on_commit is not None:
            for key in keys:
                self.on_commit(key)

    def rollback(self) -> None:
        super().rollback()
        self._pending = False
        self._transaction_id += 1


def write_status(
    conn: sqlite3.Connection, kind: Literal["operation", "admission", "recovery"],
    sql: str, parameters: Sequence = (),
) -> sqlite3.Cursor:
    """Retain commit hints for the rows the SQL actually changed, including multirow updates."""
    if not isinstance(conn, _ChangeConnection) or conn.on_commit is None:
        return conn.execute(sql, parameters)
    columns = {"operation": "operation_id", "recovery": "recovery_id", "admission": "admission_id, queue_item_id"}
    cursor = conn.execute(sql.rstrip() + " RETURNING " + columns[kind], parameters)
    keys: list[str] = []
    for row in cursor:
        if kind == "admission":
            keys.extend(("admission:" + row[0], "queue_item:" + row[1]))
        else:
            keys.append("operation:" + row[0])
    conn.retain_keys(keys)
    return cursor
