"""Process-local serialization of publication work; durable owners hold authority."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition, Lock
from _thread import LockType

from .errors import QueueServiceError


class PublicationGuards:
    """Serialize one assignment without holding up unrelated control traffic."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._pending: dict[str, tuple[LockType, int]] = {}
        self._closed = False

    @contextmanager
    def hold(self, assignment_id: str) -> Iterator[None]:
        with self._condition:
            if self._closed:
                raise QueueServiceError("coordinator is stopping")
            guard, count = self._pending.get(assignment_id, (Lock(), 0))
            self._pending[assignment_id] = guard, count + 1
        try:
            # Never wait for assignment work while holding the coordinator lock.
            with guard:
                yield
        finally:
            with self._condition:
                _, count = self._pending[assignment_id]
                if count == 1:
                    del self._pending[assignment_id]
                    self._condition.notify_all()
                else:
                    self._pending[assignment_id] = guard, count - 1

    def close(self) -> None:
        with self._condition:
            self._closed = True

    def drain(self) -> None:
        # Shutdown calls this after releasing the coordinator lock: active
        # verifiers need that lock to refuse stale acceptance and finish.
        with self._condition:
            self._condition.wait_for(lambda: not self._pending)
