"""Short, replayable SQLite transitions ordered with coordinator policy."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
import sqlite3
from time import monotonic, sleep
from typing import TYPE_CHECKING, TypeVar

from ._phase_timing import phase

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon

_T = TypeVar("_T")


def sqlite_busy(error: BaseException) -> bool:
    """Recognize ordinary and extended SQLite busy results from a writer."""
    return isinstance(error, sqlite3.OperationalError) and (getattr(error, "sqlite_errorcode", 0) & 255) == sqlite3.SQLITE_BUSY


def short_write(
    daemon: LocalDaemon,
    apply: Callable[[sqlite3.Connection], _T],
    *,
    scheduling_guard: Callable[[], AbstractContextManager] = nullcontext,
    before_begin: Callable[[], None] | None = None,
    committed: Callable[[_T], None] | None = None,
    wait_phase: str = "coordinator_database_busy_wait",
    wait_for_writer: bool = True,
) -> _T:
    """Retry the whole transition on SQLite busy after releasing both guards."""
    with daemon._connection() as conn:
        timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) / 1000
        deadline = monotonic() + timeout
        conn.execute("PRAGMA busy_timeout = 0")
        while True:
            with scheduling_guard(), daemon._state_guard():
                if before_begin is not None:
                    before_begin()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    result = apply(conn)
                    conn.commit()
                except BaseException as exc:
                    conn.rollback()
                    if (
                        not sqlite_busy(exc)
                        or not wait_for_writer
                        or monotonic() >= deadline
                    ):
                        raise
                else:
                    if committed is not None:
                        committed(result)
                    return result
            with phase(wait_phase):
                sleep(min(0.01, max(0, deadline - monotonic())))
