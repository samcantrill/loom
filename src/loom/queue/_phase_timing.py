"""Bounded process-local timing diagnostics, independent of lifecycle authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from loom.serialization import PlainData


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
