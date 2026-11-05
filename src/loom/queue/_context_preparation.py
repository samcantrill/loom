"""Disposable, bounded retained-input preparation owned by reconciliation."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import ManagedLocalIntent


@dataclass(frozen=True)
class PendingContext:
    admission: LocalDaemonAdmission
    epochs: tuple[str | None, str | None]
    future: Future[ManagedLocalIntent]


class ContextPreparations:
    """Two actual operations, no executor backlog, and round-robin admissions.

    Only the reconciliation owner changes bookkeeping. A cancelled or superseded
    caller cannot release capacity occupied by a running filesystem operation.
    Completion callbacks only wake that owner; they never mutate durable state.
    """

    def __init__(self, wake: Callable[[], None]) -> None:
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-context")
        self._pending: dict[str, PendingContext] = {}
        self._last_submitted: str | None = None
        self._wake = wake

    def submit(
        self, admissions: Iterable[LocalDaemonAdmission],
        epochs: tuple[str | None, str | None],
        load: Callable[[LocalDaemonAdmission], ManagedLocalIntent],
    ) -> None:
        candidates = list(admissions)
        cursor = next((i + 1 for i, item in enumerate(candidates)
                       if item.admission_id == self._last_submitted), 0)
        for admission in candidates[cursor:] + candidates[:cursor]:
            if len(self._pending) >= 2:
                break
            if admission.admission_id in self._pending:
                continue
            future = self._workers.submit(copy_context().run, load, admission)
            self._pending[admission.admission_id] = PendingContext(admission, epochs, future)
            self._last_submitted = admission.admission_id
            future.add_done_callback(lambda _future: self._wake())

    def completed(self) -> tuple[PendingContext, ...]:
        completed = tuple(item for item in self._pending.values() if item.future.done())
        for item in completed:
            del self._pending[item.admission.admission_id]
        return completed

    def close(self) -> None:
        # Running IO cannot safely be killed. It holds only captured inputs and
        # may finish after shutdown; no completion can authorize execution.
        self._workers.shutdown(wait=False, cancel_futures=True)
        self._pending.clear()
