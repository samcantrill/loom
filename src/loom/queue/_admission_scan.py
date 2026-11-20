"""Finite reconciliation sweeps; newly admitted work cannot extend a sweep forever."""

from collections.abc import Callable, Sequence
from itertools import islice
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .local_daemon import LocalDaemonAdmission


class AdmissionScan:
    def __init__(self) -> None:
        self.after: tuple[int, int, str] | None = None
        self.high_water: int | None = None

    def take(
        self,
        admissions: Sequence["LocalDaemonAdmission"],
        visit: Callable[["LocalDaemonAdmission"], bool],
        *,
        limit: int = 32,
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
