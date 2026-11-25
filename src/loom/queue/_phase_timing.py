"""Bounded process-local timing diagnostics, independent of lifecycle authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import count
import os
from time import monotonic
from typing import Any, cast

from loom.serialization import PlainData

from ._phase_diagnostics import diagnostics


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
    """Offer a bounded record to the process-local stderr writer."""
    diagnostics.submit(value, qualification=qualification_timings())


def request_identity(value: Mapping[str, object]) -> str | None:
    """Use existing bounded wire identities for matching sender and receiver spans."""
    renewal = value.get("renewal")
    if isinstance(renewal, Mapping):
        session, offer, sequence = (renewal.get(k) for k in ("session_id", "offer_id", "sequence"))
        if (isinstance(session, str) and len(session) <= 256 and isinstance(offer, str)
            and len(offer) <= 256 and type(sequence) is int and 0 <= sequence <= 2**63 - 1):
            return f"{session}:{offer}:{sequence}"
    for key in ("operation_id", "assignment_id", "admission_id", "idempotency_key", "session_id"):
        identity = value.get(key)
        if isinstance(identity, str) and 0 < len(identity) <= 256:
            return identity
    request = value.get("request")
    if isinstance(request, Mapping):
        preparation = request.get("preparation", request)
        if isinstance(preparation, Mapping):
            identity = preparation.get("operation_id")
            if isinstance(identity, str) and 0 < len(identity) <= 256:
                return identity
    return None


def qualification_timings() -> bool:
    return os.environ.get("LOOM_QUALIFICATION_TIMINGS") == "all"


@contextmanager
def phase(
    action: str, *, operation_id: str | None = None, pending: tuple[type[Exception], ...] = (),
) -> Iterator[dict[str, PlainData]]:
    """Record one boundary through the current diagnostic observer, if any.

    Callers may add bounded scalar evidence such as publication identity and
    byte/member counts to the yielded attributes. Diagnostic failures never
    replace the operation's result or exception.
    """
    token = _operation.set(operation_id or _operation.get())
    timing = PhaseTimings()
    attributes: dict[str, PlainData] = {}
    try:
        with timing.measure(action, pending=pending):
            yield attributes
    finally:
        try:
            if attributes:
                cast(dict[str, PlainData], timing.spans[0])["attributes"] = dict(attributes)
            if operation_id is not None:
                cast(dict[str, PlainData], timing.spans[0])["operation_id"] = operation_id
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
        self.idle_seconds = 0.0
        self.failed = False
        self.dropped = 0
        self.related: dict[str, PlainData] = {}

    @contextmanager
    def measure(self, action: str, *, pending: tuple[type[Exception], ...] = ()) -> Iterator[None]:
        started_at = datetime.now(timezone.utc).isoformat()
        start = monotonic()
        outcome = "complete"
        try:
            yield
        except pending:
            outcome = "pending"
            raise
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
_current: ContextVar[PhaseTimings | None] = ContextVar("queue_reported_timings", default=None)


@contextmanager
def idle_wait() -> Iterator[None]:
    """Exclude only the time spent waiting for a change notification."""
    timings = _current.get()
    if timings is None:
        yield
        return
    before = monotonic()
    try:
        yield
    finally:
        timings.idle_seconds += monotonic() - before


def received_idle_duration(header: str | None, elapsed: float) -> None:
    """Use an optional peer measurement, bounded by local time awaiting headers."""
    timings = _current.get()
    if timings is not None and header and len(header) <= 20 and header.isascii() and header.isdecimal():
        timings.idle_seconds += min(int(header) / 1_000_000_000, elapsed)


@contextmanager
def reported_phases(
    action: str, *, operation_id: str | None = None, started_monotonic: float | None = None,
    pending: tuple[type[Exception], ...] = (),
) -> Iterator[PhaseTimings]:
    """Report failures, slow active work and one in 64 ordinary operations.

    Each asynchronous owner installs its own collector; it never appends to a
    request or reconciliation collector after that parent operation has returned.
    An earlier process-local start includes capacity wait in slow-log selection,
    without changing the measured worker span or imposing any deadline.
    """
    timings = PhaseTimings()
    start = monotonic() if started_monotonic is None else started_monotonic
    token = _current.set(timings)
    outcome = "complete"
    try:
        with observe_phases(timings.observe), phase(action, operation_id=operation_id, pending=pending):
            yield timings
    except pending:
        outcome = "pending"
        raise
    except BaseException:
        timings.failed = True
        raise
    finally:
        _current.reset(token)
        active = max(0.0, monotonic() - start - timings.idle_seconds)
        if (qualification_timings() or timings.failed
            or active >= 1.0 or next(_operation_samples) % 64 == 0):
            try:
                log_phases({
                    **timings.payload(), "operation_id": operation_id,
                    "active_nanoseconds": round(active * 1_000_000_000),
                    "idle_nanoseconds": round(timings.idle_seconds * 1_000_000_000),
                    "outcome": "error" if timings.failed else outcome,
                })
            except Exception:
                pass


@contextmanager
def request_phases() -> Iterator[PhaseTimings]:
    """Report bounded HTTP dispatch diagnostics after response delivery."""
    with reported_phases("request_dispatch") as timings:
        yield timings
