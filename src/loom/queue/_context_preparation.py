"""Disposable, bounded retained-input preparation owned by reconciliation."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import TYPE_CHECKING
from time import monotonic

if TYPE_CHECKING:
    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import ManagedLocalIntent


type PreparedAdmissionContext = tuple["ManagedLocalIntent", "_ScopedCoordinatorAuthority"]
type ContextLoader = Callable[["LocalDaemonAdmission", tuple[str | None, str | None]], PreparedAdmissionContext]


@dataclass(frozen=True)
class PendingContext:
    admission: LocalDaemonAdmission
    epochs: tuple[str | None, str | None]
    future: Future[PreparedAdmissionContext]
    for_dispatch: bool


class ContextPreparations:
    """Two actual operations with no executor backlog.

    Only the reconciliation owner changes bookkeeping. A cancelled or superseded
    caller cannot release capacity occupied by a running filesystem operation.
    Completion callbacks only wake that owner; they never mutate durable state.
    """

    def __init__(self, wake: Callable[[], None]) -> None:
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-context")
        self._pending: dict[str, PendingContext] = {}
        self._wake = wake
        self._next_load: dict[str, tuple[int, tuple[str | None, str | None], float]] = {}
        self._interval = 0.0

    def begin_cycle(
        self, admissions: Iterable[LocalDaemonAdmission],
        *, minimum_interval: float = 0.0, invalidated: Iterable[str] = (),
    ) -> None:
        self._interval = minimum_interval
        active = {item.admission_id: item.run_uri for item in admissions}
        invalidated_runs = set(invalidated)
        for identity in self._next_load.keys() - active.keys():
            del self._next_load[identity]
        for identity, run_uri in active.items():
            if run_uri in invalidated_runs:
                self._next_load.pop(identity, None)

    def has_capacity(self) -> bool:
        return len(self._pending) < 2

    def try_submit(
        self, admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None],
        load: ContextLoader,
        *, for_dispatch: bool = False,
    ) -> bool:
        """Account for one admission, deferring it only when both slots are occupied."""
        identity = admission.admission_id
        if identity in self._pending:
            return True
        previous = self._next_load.get(identity)
        if (not for_dispatch and previous is not None
            and previous[:2] == (admission.revision, epochs) and monotonic() < previous[2]):
            return True
        if not self.has_capacity():
            return False
        # READY work gets first access to a freed slot. Keep the other slot
        # available for admissions that still need their initial reconciliation.
        if for_dispatch and any(item.for_dispatch for item in self._pending.values()):
            return False
        future = self._workers.submit(copy_context().run, _load_context, load, admission, epochs)
        self._pending[identity] = PendingContext(admission, epochs, future, for_dispatch)
        future.add_done_callback(lambda _future: self._wake())
        return True

    def completed(self) -> tuple[PendingContext, ...]:
        completed = tuple(item for item in self._pending.values() if item.future.done())
        for item in completed:
            del self._pending[item.admission.admission_id]
            self._next_load[item.admission.admission_id] = (
                item.admission.revision, item.epochs, monotonic() + self._interval,
            )
        return completed

    def next_delay(self) -> float | None:
        now = monotonic()
        return min((value[2] - now for key, value in self._next_load.items()
                    if key not in self._pending and value[2] > now), default=None)

    def running(self) -> bool:
        return any(not item.future.done() for item in self._pending.values())

    def close(self) -> None:
        # Running IO cannot safely be killed. It holds only captured inputs and
        # may finish after shutdown; no completion can authorize execution.
        self._workers.shutdown(wait=False, cancel_futures=True)
        self._next_load.clear()


def _load_context(
    load: ContextLoader,
    admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None],
) -> PreparedAdmissionContext:
    from ._phase_timing import reported_phases

    with reported_phases("context_preparation", operation_id=admission.authority_operation_id):
        return load(admission, epochs)
