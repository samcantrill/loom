"""Bounded disposable byte proofs; reconciliation alone applies completions."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from loom.artifacts import ArtifactRef
from loom.serialization import PlainData

from ._bulk_operations import BulkOperations


@dataclass(frozen=True)
class PendingResult:
    claim: Mapping[str, Any]
    epochs: tuple[str | None, str | None]
    result: Mapping[str, PlainData]
    future: Future[None]


class ResultVerifications:
    """At most two actual audits, no queued backlog or durable authority."""

    def __init__(self, wake: Callable[[], None]) -> None:
        self.bulk = BulkOperations(wake)
        self._pending: dict[str, PendingResult] = {}
        self._closed = False

    def submit(self, claim: Mapping[str, Any], epochs: tuple[str | None, str | None],
               result: Mapping[str, PlainData], outputs: Mapping[str, ArtifactRef],
               verify: Callable[[Mapping[str, ArtifactRef]], None]) -> None:
        identity = claim["claim_id"]
        if self._closed or identity in self._pending or len(self._pending) >= 2:
            return
        future = self.bulk.submit(
            identity, "action_result_byte_verification", verify, dict(outputs)
        )
        if future is None:
            return
        self._pending[identity] = PendingResult(dict(claim), epochs, dict(result), future)

    def completed(self) -> tuple[PendingResult, ...]:
        completed = tuple(item for item in self._pending.values() if item.future.done())
        for item in completed:
            del self._pending[item.claim["claim_id"]]
        return completed

    def running(self) -> bool:
        return self.bulk.running()

    def close(self) -> None:
        self._closed = True
        self.bulk.close()
