"""Two actual bulk IO operations shared by coordinator completion owners."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
from typing import Any, TypeVar


_T = TypeVar("_T")


class BulkOperations:
    """Disposable capacity; callers retain tokens and apply completed results.

    Submission and shutdown belong to the reconciliation/lifecycle owner.
    Workers only wake that owner and never change this capacity bookkeeping.
    """

    def __init__(self, wake: Callable[[], None]) -> None:
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-bulk")
        self._active: list[Future[Any]] = []
        self._wake = wake
        self._closed = False
        self._waiting: dict[tuple[tuple[str, ...], str, str], tuple[str, float]] = {}
        self._visiting: set[tuple[str, ...]] | None = None
        self._offering: tuple[tuple[str, ...], set[tuple[tuple[str, ...], str, str]]] | None = None

    @contextmanager
    def offering(self, scope: tuple[str, ...]) -> Iterator[None]:
        """Refresh waiters only when their owner actually revisits its operation.

        Waiting retains identity only, never a callable, arguments or hydrated
        report. No timeout or assumption about the next scan authorizes expiry.
        """
        if self._visiting is not None:
            self._visiting.add(scope)
        previous = self._offering
        seen: set[tuple[tuple[str, ...], str, str]] = set()
        self._offering = (scope, seen)
        try:
            yield
        finally:
            self._offering = previous
            for key in tuple(self._waiting):
                if key[0] == scope and key not in seen:
                    del self._waiting[key]

    def scopes(self, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
        return {key[0] for key in self._waiting if key[0][:len(prefix)] == prefix}

    @contextmanager
    def visiting(self, prefixes: set[tuple[str, ...]]) -> Iterator[None]:
        """Retire unvisited candidates only for owners actually reconsidered."""
        previous = self._visiting
        visited: set[tuple[str, ...]] = set()
        self._visiting = visited
        try:
            yield
            for key in tuple(self._waiting):
                scope = key[0]
                if scope not in visited and any(scope[:len(prefix)] == prefix for prefix in prefixes):
                    del self._waiting[key]
        finally:
            self._visiting = previous

    def discard(self, prefix: tuple[str, ...]) -> None:
        """Withdraw retired owners without changing actual running capacity."""
        for key in tuple(self._waiting):
            if key[0][:len(prefix)] == prefix:
                del self._waiting[key]

    def retain(self, prefix: tuple[str, ...], scopes: set[tuple[str, ...]]) -> None:
        """Retire scopes absent from the owner's current authoritative inventory."""
        for key in tuple(self._waiting):
            if key[0][:len(prefix)] == prefix and key[0] not in scopes:
                del self._waiting[key]

    def submit(
        self, operation_id: str, action: str, function: Callable[..., _T], *args: Any,
    ) -> Future[_T] | None:
        self.reap()
        if self._closed:
            return None
        queued = (datetime.now(timezone.utc).isoformat(), monotonic())
        key = None
        if self._offering is not None:
            scope, seen = self._offering
            key = (scope, operation_id, action)
            seen.add(key)
            queued = self._waiting.setdefault(key, queued)
        if len(self._active) >= 2 or (self._waiting and next(iter(self._waiting)) != key):
            return None
        if key is not None:
            del self._waiting[key]
        future = self._workers.submit(
            copy_context().run, _run, operation_id, action, function, args, queued,
        )
        self._active.append(future)
        future.add_done_callback(lambda _future: self._wake())
        return future

    def reap(self) -> None:
        # Completion owners retain their futures until application. Capacity
        # bookkeeping must not retain hydrated reports after those owners finish.
        self._active = [future for future in self._active if not future.done()]

    def running(self) -> bool:
        self.reap()
        return bool(self._active)

    def close(self) -> None:
        self._closed = True
        self._waiting.clear()
        self._workers.shutdown(wait=False, cancel_futures=True)


def _run(
    operation_id: str, action: str, function: Callable[..., _T], args: tuple[Any, ...],
    queued: tuple[str, float],
) -> _T:
    from ._phase_timing import reported_phases

    waiting_ns = round((monotonic() - queued[1]) * 1_000_000_000)
    with reported_phases(action, operation_id=operation_id, started_monotonic=queued[1]) as timings:
        timings.spans.append({
            "action": "bulk_capacity_wait", "started_at": queued[0],
            "elapsed_nanoseconds": waiting_ns, "outcome": "complete",
        })
        return function(*args)
