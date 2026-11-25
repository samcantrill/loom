"""Best-effort process diagnostics. Durable operation evidence has its own writer."""

from __future__ import annotations

import atexit
from collections import deque
from collections.abc import Callable
import json
import os
import sys
from threading import Condition, Thread
from typing import TextIO

from loom.serialization import PlainData


def _emit(stream: TextIO, value: dict[str, PlainData]) -> None:
    line = json.dumps({"diagnostic": "loom.phase_timings", **value}) + "\n"
    if stream is sys.__stderr__:
        # A stuck descriptor must not own Python's buffered stderr lock at exit.
        data = memoryview(line.encode(stream.encoding or "utf-8"))
        while data:
            written = os.write(stream.fileno(), data)
            data = data[written:]
    else:
        stream.write(line)


class DiagnosticWriter:
    def __init__(
        self, capacity: int = 256,
        emit: Callable[[TextIO, dict[str, PlainData]], None] = _emit,
    ) -> None:
        self._capacity = capacity
        self._emit = emit
        self._condition = Condition()
        self._queue: deque[tuple[TextIO, dict[str, PlainData], bool]] = deque()
        self._running = False
        self._writing = False
        self._omitted = 0
        self._qualification_omitted = 0

    def _omit(self, qualification: bool) -> None:
        self._omitted += 1
        self._qualification_omitted += int(qualification)

    def submit(self, value: dict[str, PlainData], *, qualification: bool) -> None:
        with self._condition:
            if len(self._queue) >= self._capacity:
                self._omit(qualification)
                return
            if not self._running:
                try:
                    Thread(target=self._run, name="loom-phase-diagnostics", daemon=True).start()
                except RuntimeError:
                    self._omit(qualification)
                    return
                self._running = True
            self._queue.append((sys.stderr, value, qualification))
            self._condition.notify_all()

    def counts(self) -> dict[str, PlainData]:
        with self._condition:
            return {
                "omitted_records": self._omitted,
                "omitted_qualification_records": self._qualification_omitted,
            }

    def flush(self, timeout: float = 2.0) -> bool:
        """Bound graceful process-exit draining when the destination is stalled."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._queue and not self._writing, timeout)

    def _run(self) -> None:
        while True:
            with self._condition:
                # Release the worker between bursts in short-lived applications.
                if not self._condition.wait_for(lambda: self._queue, timeout=60):
                    self._running = False
                    return
                stream, value, qualification = self._queue.popleft()
                self._writing = True
                counts = self.counts()
            try:
                self._emit(stream, {**value, **counts})
            except Exception:
                with self._condition:
                    self._omit(qualification)
            finally:
                with self._condition:
                    self._writing = False
                    self._condition.notify_all()


diagnostics = DiagnosticWriter()
atexit.register(diagnostics.flush)
