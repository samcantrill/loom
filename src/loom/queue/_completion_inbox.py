"""Small owner identities passed from IO workers to the scheduling thread."""
from collections import OrderedDict
from collections.abc import Callable, Hashable
from threading import Lock


class CompletionInbox[K: Hashable]:
    """Coalesce notifications. Only the consumer reconciles current owner state."""

    def __init__(self, wake: Callable[[], None], *, maximum: int | None = 256) -> None:
        self._wake = wake
        self._maximum = maximum
        self._lock = Lock()
        self._pending: OrderedDict[K, None] = OrderedDict()

    def offer(self, owner: K) -> None:
        with self._lock:
            # Durable admissions and attempts remain discoverable if a burst
            # fills the hint queue. Process-local consumers bound membership
            # at their own admission boundary and request lossless delivery.
            if self._maximum is None or len(self._pending) < self._maximum:
                self._pending.setdefault(owner, None)

    def post(self, owner: K) -> None:
        self.offer(owner)
        self._wake()

    def take(self, limit: int = 32) -> tuple[K, ...]:
        with self._lock:
            ready = tuple(self._pending.popitem(last=False)[0]
                          for _ in range(min(limit, len(self._pending))))
            more = bool(self._pending)
        if more:
            self._wake()
        return ready
