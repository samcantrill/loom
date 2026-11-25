"""Finite reconciliation sweeps; newly admitted work cannot extend a sweep forever."""

from collections.abc import Callable, Sequence
from itertools import islice
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .local_daemon import LocalDaemonAdmission


_ACTIVE = "state NOT IN ('SUCCEEDED','FAILED','CANCELLED','BLOCKED')"
LEGACY_CANCELLED = "state = 'CANCELLED' AND cancellation_operation_id IS NULL"
_PRIORITY_ORDER = "run_priority DESC, enqueue_sequence, admission_id"
_PAGE_SIZE = 32


# Other metadata keys can contain plain text rather than a JSON document.
PENDING_ADMISSION_RETRY = "CASE WHEN key GLOB 'admission-retry:*' THEN json_extract(value, '$.state') END = 'pending'"


def ensure_retry_index(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE INDEX IF NOT EXISTS pending_admission_retries ON daemon_metadata(key) "
                 f"WHERE {PENDING_ADMISSION_RETRY}")


def ensure_scan_index(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE INDEX IF NOT EXISTS legacy_cancelled_admissions "
                 f"ON managed_admissions(enqueue_sequence, admission_id) WHERE {LEGACY_CANCELLED}")
    conn.execute(f"CREATE INDEX IF NOT EXISTS managed_admissions_active_order "
                 f"ON managed_admissions ({_PRIORITY_ORDER}) WHERE {_ACTIVE}")


class SchedulingAdmissions(dict[str, "LocalDaemonAdmission"]):
    """The current turn's bounded READY pages, independent of admission discovery."""

    def __init__(self, enqueue_through: int, lookup: Callable[[set[str]], dict[str, "LocalDaemonAdmission"]]):
        super().__init__()
        self.enqueue_through = enqueue_through
        self._lookup = lookup
        self._checked: set[str] = set()
        self.visited_dispatch: set[tuple[str, ...]] = set()

    def include(self, identities: set[str]) -> None:
        missing = identities.difference(self, self._checked)
        if missing:
            self.update(self._lookup(missing))
            self._checked.update(missing)


class AdmissionScan:
    def __init__(self) -> None:
        self.after: tuple[int, int, str] | None = None
        self.high_water: int | None = None

    def page(self, conn: sqlite3.Connection, enqueue_through: int) -> tuple[sqlite3.Row, ...]:
        """Read just one priority-ordered page and its continuation witness."""
        if self.high_water is None:
            self.high_water = enqueue_through
        prefix = f"SELECT * FROM managed_admissions WHERE {_ACTIVE} AND enqueue_sequence <= ? "
        order = f"ORDER BY {_PRIORITY_ORDER} LIMIT ?"
        limit = _PAGE_SIZE + 1
        if self.after is None:
            return tuple(conn.execute(prefix + order, (self.high_water, limit)))
        negative_priority, sequence, identity = self.after
        priority = -negative_priority
        # A row-value comparison across mixed sort directions cannot seek to
        # this cursor. Finish its equal-priority suffix, then lower priorities.
        same = tuple(conn.execute(
            prefix + "AND run_priority = ? AND (enqueue_sequence, admission_id) > (?, ?) " + order,
            (self.high_water, priority, sequence, identity, limit),
        ))
        if len(same) == limit:
            return same
        lower = conn.execute(prefix + "AND run_priority < ? " + order, (self.high_water, priority, limit - len(same)))
        return (*same, *lower)

    def take(
        self,
        admissions: Sequence["LocalDaemonAdmission"],
        visit: Callable[["LocalDaemonAdmission"], bool],
        *,
        limit: int = _PAGE_SIZE,
    ) -> tuple["LocalDaemonAdmission", ...]:
        """Visit a bounded prefix. A refused visit leaves the admission at the head."""
        if self.high_water is None:
            self.high_water = max((row.enqueue_sequence for row in admissions), default=0)
        eligible = (
            row for row in admissions
            if row.enqueue_sequence <= self.high_water
            and (self.after is None or self.key(row) > self.after)
        )
        visited = []
        for row in islice(eligible, limit):
            if not visit(row):
                return tuple(visited)
            visited.append(row)
            self.after = self.key(row)
        if next(eligible, None) is None:
            self.after = self.high_water = None
        return tuple(visited)

    @staticmethod
    def key(row: "LocalDaemonAdmission") -> tuple[int, int, str]:
        return -row.run_priority, row.enqueue_sequence, row.admission_id
