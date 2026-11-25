"""Bounded producer byte proofs and their exact completion transactions."""
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
        self._applying: dict[str, Future[None]] = {}
        self._closed = False

    def submit(self, claim: Mapping[str, Any], epochs: tuple[str | None, str | None],
               result: Mapping[str, PlainData], outputs: Mapping[str, ArtifactRef],
               verify: Callable[[Mapping[str, ArtifactRef]], None]) -> None:
        identity = claim["claim_id"]
        if (self._closed or identity in self._pending or identity in self._applying
                or len(self._pending) + len(self._applying) >= 2):
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

    def advance(self, apply: Callable[[PendingResult], None]) -> None:
        """Offer completed proofs without waiting for final authority or commit."""
        for identity, future in tuple(self._applying.items()):
            if future.done():
                del self._applying[identity]
                future.result()
        for identity, proof in tuple(self._pending.items()):
            if not proof.future.done():
                continue
            with self.bulk.offering(("producer-proof", identity)):
                future = self.bulk.submit(identity, "action_result_completion", apply, proof)
            if future is not None:
                self._applying[identity] = future
                del self._pending[identity]

    def running(self) -> bool:
        return self.bulk.running()

    def close(self) -> None:
        self._closed = True
        self.bulk.close()
