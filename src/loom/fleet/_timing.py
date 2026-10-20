"""Bounded, best-effort action timings; never maintenance authority."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4


_active: ContextVar[Trace | None] = ContextVar("fleet_action_timing", default=None)
_ACTION = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


class Trace:
    def __init__(self):
        self.invocation = uuid4().hex
        self.records: list[dict] = []
        self.directory: Path | None = None
        self.lock = threading.Lock()

    def add(self, record):
        # Host diagnostics cross a process boundary. Discard malformed or large
        # observations, without changing the authoritative operation outcome.
        try:
            if set(record) != {"action", "started_at", "elapsed_seconds", "outcome", "host"}:
                return
            if not isinstance(record["action"], str) or not _ACTION.fullmatch(record["action"]):
                return
            if record["outcome"] not in {"complete", "error", "waiting", "reused"}:
                return
            seconds = record["elapsed_seconds"]
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                return
            if not isinstance(record["started_at"], str):
                return
            host = record["host"]
            if host is not None and (not isinstance(host, str) or len(host) > 128):
                return
            if len(json.dumps(record).encode()) > 1024:
                return
            with self.lock:
                if len(self.records) < 4096:
                    self.records.append(record)
        except (TypeError, ValueError):
            return

    def flush(self):
        if self.directory is None:
            return
        try:
            path = self.directory / "timings.jsonl"
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "a") as stream:
                for record in self.records:
                    stream.write(json.dumps({"schema_version": 1, "invocation": self.invocation,
                                             **record}, allow_nan=False) + "\n")
        except OSError:
            pass


@contextmanager
def recording():
    trace = Trace()
    token = _active.set(trace)
    try:
        yield trace
    finally:
        _active.reset(token)
        trace.flush()


def bind_directory(directory: Path):
    trace = _active.get()
    if trace is not None:
        trace.directory = directory


def ingest(records, *, host=None):
    trace = _active.get()
    if trace is not None and isinstance(records, list) and len(records) <= 4096:
        for record in records:
            if isinstance(record, dict):
                trace.add({**record, "host": host if host is not None else record.get("host")})


@contextmanager
def measure(action: str, *, host=None):
    trace = _active.get()
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    result = {"outcome": "complete"}
    try:
        yield result
    except BaseException as exc:
        result["outcome"] = "waiting" if getattr(exc, "fleet_pending", False) else "error"
        raise
    finally:
        if trace is not None:
            trace.add({"action": action, "host": host, "started_at": started_at,
                       "elapsed_seconds": time.monotonic() - start,
                       "outcome": result["outcome"]})


def timed(action: str):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            with measure(action) as timing:
                result = function(*args, **kwargs)
                if isinstance(result, dict) and result.get("outcome") == "waiting":
                    timing["outcome"] = "waiting"
                return result
        return invoke
    return decorate
