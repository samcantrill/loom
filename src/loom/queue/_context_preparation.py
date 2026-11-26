"""Disposable, bounded retained-input preparation owned by reconciliation."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import TYPE_CHECKING
from time import monotonic

from ._context_timing import ContextTiming, current_load
from ._phase_timing import qualification_timings

if TYPE_CHECKING:
    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import ManagedLocalIntent


type PreparedAdmissionContext = tuple["ManagedLocalIntent", "_ScopedCoordinatorAuthority"]
type ContextLoader = Callable[["LocalDaemonAdmission", tuple[str | None, str | None]], PreparedAdmissionContext]


@dataclass(frozen=True, slots=True)
class _DispatchRetry:
    admission: LocalDaemonAdmission
    epochs: tuple[str | None, str | None]
    work_id: str


@dataclass
class PendingContext:
    admission: LocalDaemonAdmission
    epochs: tuple[str | None, str | None]
    future: Future[PreparedAdmissionContext]
    for_dispatch: bool
    fresh_load: bool = True
    invalidated: bool = False
    timing: ContextTiming | None = None

    def result(self) -> PreparedAdmissionContext:
        try:
            return self.future.result()
        except CancelledError:
            self.discard("load_superseded")
            raise
        except Exception:
            self.discard("load_failed")
            raise

    def discard(self, reason: str) -> None:
        if self.timing is not None:
            self.timing.discard("preparation", reason)


class ContextPreparations:
    """Two actual operations with no executor backlog.

    Only the reconciliation owner changes bookkeeping. A cancelled or superseded
    caller cannot release capacity occupied by a running filesystem operation.
    Completion callbacks only wake that owner; they never mutate durable state.
    """

    _retry_limit = 256
    _retry_batch = 8

    def __init__(self, wake: Callable[[], None]) -> None:
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-context")
        self._pending: dict[str, PendingContext] = {}
        self._wake = wake
        self._dispatch_retries: dict[str, _DispatchRetry] = {}
        self._next_load: dict[str, tuple[int, tuple[str | None, str | None], float, str]] = {}
        self._interval = 0.0
        self._tracing = qualification_timings()
        self._drained: list[ContextTiming] = []
        # Diagnostic history of offers refused before a slot exists. This is
        # bounded independently of the executor and never schedules a retry.
        self._waiting: OrderedDict[str, ContextTiming] = OrderedDict()

    def begin_cycle(
        self, *, minimum_interval: float = 0.0, invalidated: Iterable[str] = (),
    ) -> None:
        self._interval = minimum_interval
        now = monotonic()
        invalidated_runs = set(invalidated)
        for item in self._pending.values():
            if item.admission.run_uri in invalidated_runs:
                item.invalidated = True
                item.discard("run_invalidated")
        for identity, retry in tuple(self._dispatch_retries.items()):
            if retry.admission.run_uri in invalidated_runs:
                del self._dispatch_retries[identity]
        for identity, ticket in tuple(self._waiting.items()):
            if ticket.admission.run_uri in invalidated_runs:
                self._waiting.pop(identity).discard("request", "run_invalidated")
        # These entries only suppress repeat filesystem loads until their
        # deadline. Expire them independently of which admission page is read.
        for identity, (_, _, deadline, run_uri) in tuple(self._next_load.items()):
            if deadline <= now or run_uri in invalidated_runs:
                del self._next_load[identity]

    def has_capacity(self) -> bool:
        return sum(item.fresh_load for item in self._pending.values()) < 2

    def _request_timing(
        self, admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None], *,
        source: str, wait_reason: str, reuse: bool,
    ) -> ContextTiming | None:
        identity = admission.admission_id
        timing = self._waiting.get(identity)
        if timing is not None:
            reason = None
            if timing.epochs != epochs:
                reason = "epoch_changed"
            elif timing.admission.revision != admission.revision:
                reason = "admission_revision_changed"
            elif reuse:
                reason = "retained_reuse"
            if reason is not None:
                self._waiting.pop(identity).discard("request", reason)
                timing = None
        if reuse:
            return None
        if timing is None:
            timing = ContextTiming(admission, epochs, source)
            timing.event("context_requested", wait_reason=wait_reason)
            self._waiting[identity] = timing
            if len(self._waiting) > 256:
                self._waiting.popitem(last=False)[1].discard("request", "observation_limit")
        return timing

    def _remember_dispatch(self, retry: _DispatchRetry) -> bool:
        identity = retry.admission.admission_id
        if identity in self._dispatch_retries:
            return False  # Repeated visits keep the original FIFO position.
        if len(self._dispatch_retries) >= self._retry_limit:
            # Keep older equal-priority demand. Displaced work remains in READY.
            newest_lowest = min(reversed(self._dispatch_retries.values()), key=lambda r: r.admission.run_priority)
            if retry.admission.run_priority <= newest_lowest.admission.run_priority:
                return False
            del self._dispatch_retries[newest_lowest.admission.admission_id]
        self._dispatch_retries[identity] = retry
        return True

    def retry_dispatch(
        self, epochs: tuple[str | None, str | None],
        lookup: Callable[[set[str]], Mapping[str, LocalDaemonAdmission]],
        needed: Callable[[LocalDaemonAdmission, str], bool], load: ContextLoader,
    ) -> None:
        """Give the next live waiter the freed dispatch slot, in priority/FIFO order."""
        if not self._dispatch_retries or not self.has_capacity() or any(p.for_dispatch for p in self._pending.values()):
            return
        candidates = sorted((r for key, r in self._dispatch_retries.items() if key not in self._pending),
                            key=lambda r: -r.admission.run_priority)
        batch = candidates[:self._retry_batch]
        if not batch:
            return
        current = lookup({r.admission.admission_id for r in batch})
        for retry in batch:
            identity = retry.admission.admission_id
            admission = current.get(identity)
            if retry.epochs != epochs:
                reason = "epoch_changed"
            elif admission is None:
                reason = "admission_unschedulable"
            elif retry.admission.revision != admission.revision:
                reason = "admission_revision_changed"
            elif not needed(admission, retry.work_id):
                reason = "dispatch_no_longer_needed"
            else:
                if self._tracing:
                    self._request_timing(admission, epochs, source="dispatch", wait_reason="available", reuse=False)
                self._start(admission, epochs, load, for_dispatch=True, continuation=None)
                return
            del self._dispatch_retries[identity]
            timing = self._waiting.pop(identity, None)
            if timing is not None:
                timing.discard("request", reason)
        if len(batch) < len(candidates):
            self._wake()

    def try_submit(
        self, admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None],
        load: ContextLoader,
        *, dispatch_work_id: str | None = None, resume: bool = False,
        continuation: PreparedAdmissionContext | None = None,
    ) -> bool:
        """Submit a load or continuation; a refused READY request retains its retry."""
        identity = admission.admission_id
        for_dispatch = dispatch_work_id is not None
        queued = self._dispatch_retries.get(identity)
        if queued is not None and (queued.epochs != epochs or queued.admission.revision != admission.revision):
            del self._dispatch_retries[identity]
        pending = self._pending.get(identity)
        if pending is not None and (pending.epochs == epochs and pending.admission.revision == admission.revision
                                    and not pending.invalidated):
            return True
        previous = self._next_load.get(identity)
        if (pending is None and not (for_dispatch or resume) and previous is not None
            and previous[:2] == (admission.revision, epochs) and monotonic() < previous[2]):
            return True
        if pending is not None:
            wait_reason = "superseded_load_running"
        elif continuation is None and not self.has_capacity():
            wait_reason = "workers_busy"
        elif for_dispatch and any(item.for_dispatch for item in self._pending.values()):
            wait_reason = "dispatch_slot_busy"
        elif for_dispatch and self._dispatch_retries:
            wait_reason = "dispatch_retry_pending"
        else:
            wait_reason = "available"
        if self._tracing:
            source = "dispatch" if for_dispatch else ("resume" if resume else "discovery")
            self._request_timing(admission, epochs, source=source,
                                 wait_reason=wait_reason, reuse=continuation is not None)
        if wait_reason != "available":
            if dispatch_work_id is not None:
                added = self._remember_dispatch(_DispatchRetry(admission, epochs, dispatch_work_id))
                if added and wait_reason == "dispatch_retry_pending":
                    self._wake()  # The new waiter arrived after this turn serviced retries.
            return pending is not None
        self._start(admission, epochs, load, for_dispatch=for_dispatch, continuation=continuation)
        return True

    def _start(
        self, admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None],
        load: ContextLoader, *, for_dispatch: bool, continuation: PreparedAdmissionContext | None,
    ) -> None:
        identity = admission.admission_id
        self._dispatch_retries.pop(identity, None)  # Discovery can satisfy the same request.
        timing = self._waiting.pop(identity, None)
        if continuation is None:
            future = self._workers.submit(copy_context().run, _load_context, load, admission, epochs, timing)
        else:
            future = Future()
            future.set_result(continuation)
        self._pending[identity] = PendingContext(
            admission, epochs, future, for_dispatch, fresh_load=continuation is None, timing=timing,
        )
        future.add_done_callback(lambda _future: self._wake())

    def completed(self) -> tuple[PendingContext, ...]:
        completed = tuple(item for item in self._pending.values() if item.future.done())
        for item in completed:
            del self._pending[item.admission.admission_id]
            if item.fresh_load and not item.invalidated:
                self._next_load[item.admission.admission_id] = (
                    item.admission.revision, item.epochs, monotonic() + self._interval, item.admission.run_uri,
                )
        ready = tuple(item for item in completed if not item.invalidated)
        if self._tracing:
            self._drained.extend(item.timing for item in ready if item.timing is not None)
        return ready

    def finish_handoffs(self) -> None:
        # An exception while checking one admission can interrupt the drained
        # batch before the remaining contexts reach their individual owners.
        for timing in self._drained:
            if not timing.handed_off:
                timing.discard("preparation", "handoff_interrupted")
        self._drained.clear()

    def next_delay(self) -> float | None:
        now = monotonic()
        return min((value[2] - now for key, value in self._next_load.items()
                    if key not in self._pending and value[2] > now), default=None)

    def running(self) -> bool:
        return any(not item.future.done() for item in self._pending.values())

    def close(self) -> None:
        # Running IO cannot safely be killed. It holds only captured inputs and
        # may finish after shutdown; no completion can authorize execution.
        for item in self._pending.values():
            item.discard("shutdown")
        for timing in self._waiting.values():
            timing.discard("request", "shutdown")
        self._dispatch_retries.clear()
        self._waiting.clear()
        self._workers.shutdown(wait=False, cancel_futures=True)
        self._next_load.clear()


def _load_context(
    load: ContextLoader,
    admission: LocalDaemonAdmission, epochs: tuple[str | None, str | None], timing: ContextTiming | None,
) -> PreparedAdmissionContext:
    from ._phase_timing import reported_phases

    token = current_load.set(timing)
    try:
        if timing is not None:
            timing.event("context_loader_started")
        with reported_phases("context_preparation", operation_id=admission.authority_operation_id):
            context = load(admission, epochs)
        if timing is not None:
            timing.event("context_available")
        return context
    finally:
        current_load.reset(token)
