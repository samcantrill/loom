"""Process-local hints for pending agent polls; SQLite owns all work state."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition

from .errors import QueueServiceError
from ._service_signals import _ChangeSignal


class _PollSignal(_ChangeSignal):
    """Session-scoped hint, owned by the pending work-poll subscriptions."""


class _PollWaiters:
    def __init__(self) -> None:
        self._condition = Condition()
        self._subscribers: dict[str, tuple[_PollSignal, int]] = {}
        self._closed = False

    @contextmanager
    def subscribe(self, session_id: str) -> Iterator[_PollSignal]:
        with self._condition:
            if self._closed:
                raise QueueServiceError("coordinator is stopping")
            signal, count = self._subscribers.get(session_id, (_PollSignal(), 0))
            self._subscribers[session_id] = signal, count + 1
        try:
            yield signal
        finally:
            with self._condition:
                _, count = self._subscribers[session_id]
                if count == 1:
                    del self._subscribers[session_id]
                    self._condition.notify_all()
                else:
                    self._subscribers[session_id] = signal, count - 1

    def notify(self, session_id: str) -> None:
        with self._condition:
            subscriber = self._subscribers.get(session_id)
        if subscriber is not None:
            subscriber[0].notify()

    def notify_all(self) -> None:
        with self._condition:
            signals = tuple(item[0] for item in self._subscribers.values())
        for signal in signals:
            signal.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            signals = tuple(item[0] for item in self._subscribers.values())
        for signal in signals:
            signal.close()

    def drain(self) -> None:
        # Call without the daemon cycle lock: handlers need it for shutdown
        # detection and finish their exact poll cleanup before unsubscribing.
        with self._condition:
            self._condition.wait_for(lambda: not self._subscribers)
