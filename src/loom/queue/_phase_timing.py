"""Bounded process-local timing diagnostics, independent of lifecycle authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from itertools import count
import sys
from time import monotonic
from typing import Any, cast

from loom.serialization import PlainData


_observer: ContextVar[Callable[[dict[str, PlainData]], None] | None] = ContextVar(
    "queue_phase_observer", default=None
)
_operation: ContextVar[str | None] = ContextVar("queue_phase_operation", default=None)


@contextmanager
def observe_phases(observer: Callable[[dict[str, PlainData]], None]) -> Iterator[None]:
    """Route bounded queue diagnostics to the current host-operation owner."""
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def log_phases(value: dict[str, PlainData]) -> None:
    """Write opted-in service diagnostics to its existing stderr log."""
    sys.stderr.write(json.dumps({"diagnostic": "loom.phase_timings", **value}) + "\n")


@contextmanager
def phase(action: str, *, operation_id: str | None = None) -> Iterator[None]:
    """Record one boundary through the current diagnostic observer, if any.

    Only action, duration, outcome and the existing operation identity are emitted.
    Diagnostic failures never replace the operation's result or exception.
    """
    token = _operation.set(operation_id or _operation.get())
    timing = PhaseTimings()
    try:
        with timing.measure(action):
            yield
    finally:
        try:
            value = {**timing.payload(), "operation_id": _operation.get()}
            observer = _observer.get()
            if observer is not None:
                observer(value)
        except Exception:
            pass
        finally:
            _operation.reset(token)


class PhaseTimings:
    """Measure work where it executes; nested spans are not additive wall time."""

    def __init__(self) -> None:
        self.spans: list[PlainData] = []
        self.dropped = 0
        self.related: dict[str, PlainData] = {}

    @contextmanager
    def measure(self, action: str) -> Iterator[None]:
        started_at = datetime.now(timezone.utc).isoformat()
        start = monotonic()
        outcome = "complete"
        try:
            yield
        except BaseException:
            outcome = "error"
            raise
        finally:
            if len(self.spans) < 64:
                self.spans.append({
                    "action": action, "started_at": started_at,
                    # The native event protocol admits integer numeric values.
                    "elapsed_nanoseconds": round((monotonic() - start) * 1_000_000_000),
                    "outcome": outcome,
                })
            else:
                self.dropped += 1

    def observe(self, value: dict[str, PlainData]) -> None:
        """Collect nested native phase spans into this owner's bounded payload."""
        spans = cast(list[PlainData], value["spans"])
        remaining = max(0, 64 - len(self.spans))
        self.spans.extend(spans[:remaining])
        self.dropped += max(0, len(spans) - remaining) + cast(int, value["dropped_spans"])

    def call(self, action: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self.measure(action):
            return function(*args, **kwargs)

    def payload(self) -> dict[str, PlainData]:
        return {"clock": "process_monotonic", "spans": self.spans,
                "dropped_spans": self.dropped,
                **({"related": self.related} if self.related else {})}


@contextmanager
def state_lock(lock: Any) -> Iterator[None]:
    """Measure coordinator lock wait/hold and defer all reporting until release.

    Nested phase spans are collected into the same bounded diagnostic payload.
    With reentrant locks, the outer collector also defers inner lock reporting.
    """
    timings = PhaseTimings()
    observer = _observer.get()
    try:
        with timings.measure("coordinator_state_lock_wait"):
            lock.acquire()
        try:
            with observe_phases(timings.observe), timings.measure("coordinator_state_lock_hold"):
                yield
        finally:
            lock.release()
    finally:
        if observer is not None:
            try:
                observer({**timings.payload(), "operation_id": _operation.get()})
            except Exception:
                pass


_operation_samples = count()


@contextmanager
def reported_phases(action: str, *, operation_id: str | None = None) -> Iterator[None]:
    """Report slow operations and one in 64 ordinary operations after completion.

    Each asynchronous owner installs its own collector; it never appends to a
    request or reconciliation collector after that parent operation has returned.
    """
    timings = PhaseTimings()
    start = monotonic()
    try:
        with observe_phases(timings.observe), phase(action, operation_id=operation_id):
            yield
    finally:
        if monotonic() - start >= 1.0 or next(_operation_samples) % 64 == 0:
            try:
                log_phases({**timings.payload(), "operation_id": operation_id})
            except Exception:
                pass


@contextmanager
def request_phases() -> Iterator[None]:
    """Report bounded HTTP dispatch diagnostics after the handler returns."""
    with reported_phases("request_dispatch"):
        yield
