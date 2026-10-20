"""Bounded process-local timing diagnostics, independent of lifecycle authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import sys
from time import monotonic
from typing import Any

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

    def call(self, action: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self.measure(action):
            return function(*args, **kwargs)

    def payload(self) -> dict[str, PlainData]:
        return {"clock": "process_monotonic", "spans": self.spans,
                "dropped_spans": self.dropped,
                **({"related": self.related} if self.related else {})}
