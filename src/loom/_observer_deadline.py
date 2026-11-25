"""Carry a caller's absolute observer deadline through nested transport calls."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic


_observer_end: ContextVar[float | None] = ContextVar("loom_observer_end", default=None)


def observer_end(deadline: float | None = None) -> float | None:
    enclosing = _observer_end.get()
    if enclosing is None:
        return deadline
    return enclosing if deadline is None else min(enclosing, deadline)


@contextmanager
def observer_until(deadline: float | None):
    token = _observer_end.set(observer_end(deadline))
    try:
        yield
    finally:
        _observer_end.reset(token)


def observer_budget(seconds: float):
    return observer_until(monotonic() + seconds)
