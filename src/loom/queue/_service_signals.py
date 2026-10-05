"""Process-local change hints; committed SQLite state remains authoritative."""

from collections.abc import Callable
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


class _ChangeConnection(sqlite3.Connection):
    """Notify passive readers after a successful changing control-store commit.

    The callback must only signal: no database IO or scheduling work. A changed
    row is a hint, not a revision, acknowledgement or ownership proof. Rollback
    resets the change baseline so a later empty commit cannot advertise it.
    """

    on_commit: Callable[[], None] | None = None
    _committed_changes: int = 0

    def commit(self) -> None:
        super().commit()
        changed = self.total_changes != self._committed_changes
        self._committed_changes = self.total_changes
        if changed and self.on_commit is not None:
            self.on_commit()

    def rollback(self) -> None:
        super().rollback()
        self._committed_changes = self.total_changes
