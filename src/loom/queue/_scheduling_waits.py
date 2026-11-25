"""Process-local observations of coordinator scheduling waits, independent of authority."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic_ns

from loom.serialization import PlainData


@dataclass(frozen=True, slots=True)
class _Wait:
    boundary: str
    since: str
    start_ns: int


class SchedulingWaits:
    """Keep the latest boundaries in the bounded READY and admission windows."""

    def __init__(self) -> None:
        self._waits: OrderedDict[tuple[str, str | None], _Wait] = OrderedDict()
        self._lock = Lock()

    def record(self, run_uri: str, stage_name: str | None, boundary: str) -> None:
        key = run_uri, stage_name
        with self._lock:
            wait = self._waits.get(key)
            if wait is None or wait.boundary != boundary:
                self._waits[key] = _Wait(boundary, datetime.now(timezone.utc).isoformat(), monotonic_ns())
            self._waits.move_to_end(key)
            if len(self._waits) > 288:
                self._waits.popitem(last=False)

    def clear(self, run_uri: str, stage_name: str | None) -> None:
        with self._lock:
            self._waits.pop((run_uri, stage_name), None)

    def retain(self, run_uri: str, eligible: set[str]) -> None:
        with self._lock:
            for key in tuple(self._waits):
                if key[0] == run_uri and key[1] not in eligible:
                    del self._waits[key]

    def observed(self, run_uri: str) -> list[PlainData]:
        with self._lock:
            now = monotonic_ns()
            return [{"stage": stage, "boundary": wait.boundary, "since": wait.since,
                     "elapsed_nanoseconds": now - wait.start_ns}
                    for (uri, stage), wait in self._waits.items() if uri == run_uri]
