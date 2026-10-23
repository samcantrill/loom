"""Invocation-local, lossy diagnostics; never a source of maintenance authority."""
from __future__ import annotations

from collections.abc import Callable
import json
import math
import threading
import time
from typing import Any

ProgressSink = Callable[[dict[str, Any]], None]

_ENUMS = {
    "event": {"phase", "heartbeat", "result"},
    "kind": {"runtime-upgrade", "workload-upgrade", "configuration-retirement", "container-policy-addition", "unknown"},
    "action": {"apply", "resume", "abort", "retry-check", "retry-control"},
    "phase": {"preparing", "closing_admission", "settling", "draining", "replacing",
              "checking", "restoring", "reopening_admission", "recovering", "finished"},
    "state": {"running", "complete", "aborted", "waiting", "blocked", "interrupted", "error"},
    "reason_code": {"none", "settlement_pending", "acknowledgement_pending", "check_failed", "publication_pending",
                    "host_unavailable", "coordinator_unavailable", "native_refusal", "input_invalid", "unknown"},
}
_CLOCKS = {"elapsed_seconds", "phase_elapsed_seconds", "preparation_seconds", "admission_closed_seconds"}


def encode(snapshot: dict[str, Any]) -> str:
    """Validate the diagnostic boundary and serialize only its fixed public shape."""
    if set(snapshot) != {"schema_version", *_ENUMS, *_CLOCKS} or snapshot["schema_version"] != 1:
        raise ValueError("invalid progress shape")
    if any(snapshot[key] not in values for key, values in _ENUMS.items()):
        raise ValueError("invalid progress enum")
    for key in _CLOCKS:
        value = snapshot[key]
        if key == "admission_closed_seconds" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid progress duration")
    line = json.dumps(snapshot, allow_nan=False, separators=(",", ":")) + "\n"
    if len(line.encode()) > 1024:
        raise ValueError("oversized progress record")
    return line


class Observation:
    def __init__(self, sink: ProgressSink | None, action: str, *, clock=time.monotonic):
        self.sink = sink
        self.clock = clock
        self.started = self.phase_started = clock()
        self.phase = "preparing" if action == "apply" else "recovering"
        self.kind = "unknown"
        self.action = action
        self.reason = "none"
        self.state = "running"
        self.prepared = 0.0
        self.preparing: float | None = self.started
        self.closed: float | None = None
        self.opened: float | None = None
        self.ended: float | None = None
        self.condition = threading.Condition()
        self.revision = 0
        self.worker: threading.Thread | None = None
        if sink is not None:
            self.worker = threading.Thread(target=self._report, name="loom-upgrade-progress", daemon=True)
            self.worker.start()

    def enter(self, phase: str):
        with self.condition:
            if phase == self.phase:
                return
            now = self.clock()
            if self.preparing is not None:
                self.prepared += now - self.preparing
            self.preparing = now if phase == "preparing" else None
            self.phase, self.phase_started = phase, now
            self.revision += 1
            self.condition.notify()

    def end_preparation(self):
        with self.condition:
            if self.preparing is not None:
                self.prepared += self.clock() - self.preparing
                self.preparing = None

    def gate(self, closed: bool):
        with self.condition:
            if closed and self.closed is None:
                self.closed = self.clock()
            elif not closed and self.closed is not None and self.opened is None:
                self.opened = self.clock()

    def snapshot(self, event="heartbeat") -> dict[str, Any]:
        with self.condition:
            now = self.clock() if self.ended is None else self.ended
            return {
                "schema_version": 1, "event": event, "kind": self.kind,
                "action": self.action, "phase": self.phase, "state": self.state,
                "reason_code": self.reason, "elapsed_seconds": now - self.started,
                "phase_elapsed_seconds": now - self.phase_started,
                "preparation_seconds": self.prepared + (0 if self.preparing is None else now - self.preparing),
                "admission_closed_seconds": None if self.closed is None else
                    (now if self.opened is None else self.opened) - self.closed,
            }

    def finish(self, state: str, reason: str | None = None):
        with self.condition:
            if state in {"complete", "aborted"}:
                self.enter("finished")
            self.state = state
            if reason is not None:
                self.reason = reason
            self.ended = self.clock()
            self.revision += 1
            self.condition.notify()
        # A blocked callback owns no lifecycle resource and cannot delay process exit.
        if self.worker is not None:
            self.worker.join(timeout=0.1)

    def _report(self):
        seen = -1
        heartbeat = time.monotonic() + 5
        try:
            while True:
                with self.condition:
                    while seen == self.revision and self.ended is None:
                        delay = heartbeat - time.monotonic()
                        if delay <= 0:
                            break
                        self.condition.wait(delay)
                    event = "result" if self.ended is not None else "phase" if seen != self.revision else "heartbeat"
                    if event == "heartbeat":
                        heartbeat = time.monotonic() + 5
                    seen = self.revision
                    snapshot = self.snapshot(event)
                # The same validation applies to Python callbacks and CLI output.
                encode(snapshot)
                assert self.sink is not None
                self.sink(snapshot)
                if event == "result":
                    return
        except BaseException:
            return


def phase(operation, name):
    observer = getattr(operation, "observation", None)
    if observer is not None:
        observer.enter(name)


def reason(operation, code):
    observer = getattr(operation, "observation", None)
    if observer is not None:
        observer.reason = code
