"""Bounded filesystem effects and finite result turns for the Slurm owner.

Only the caller advances protocol state. Workers never mutate agent journals or
make HTTP requests. Restart replays the bound report/chunks; the receiver's
durable offset acknowledgement remains authoritative.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
from time import monotonic
from typing import Any

from loom.pipeline.stores.shared_artifacts import binding as shared_binding
from loom.serialization import PlainData, thaw_plain_data

from ._remote_stage_execution import _RemoteExecutionReport
from ._slurm_result_transport import SharedSlurmResult, SlurmEffectPending
from .errors import QueueConflictError, QueueServiceError


@dataclass
class _Delivery:
    identity: str
    phase: str
    report: _RemoteExecutionReport | None = None
    index: int = 0
    offset: int = 0
    chunk: bytes | None = None


class SlurmStorageProgress:
    """Scheduling-owner state, with independently bounded IO and metadata owners."""

    def __init__(self, *, workers: int = 2, outstanding: int = 8, owners: int = 32):
        if not 0 < workers <= outstanding <= owners:
            raise ValueError("Slurm storage capacities must be positive and ordered")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="loom-agent-slurm-io")
        self._outstanding = outstanding
        self._owners = owners
        self._pending: dict[tuple[str, str], Future[Any]] = {}
        self._deliveries: dict[str, _Delivery] = {}
        self._retry_at: dict[str, float] = {}
        self._closed = False

    def poll(self, assignment: str, kind: str, operation: Callable[[], Any]) -> Any:
        if self._closed:
            raise QueueServiceError("Slurm storage owner is closed")
        key = assignment, kind
        future = self._pending.get(key)
        if future is None:
            if len(self._pending) >= self._outstanding:
                raise SlurmEffectPending(0.05)
            future = self._executor.submit(operation)
            self._pending[key] = future
        if not future.done():
            raise SlurmEffectPending(0.05)
        del self._pending[key]
        return future.result()

    def forget_delivery(self, assignment: str) -> None:
        # An old read must actually exit before cleanup can remove its files.
        key = assignment, "delivery"
        future = self._pending.get(key)
        if future is not None:
            if not future.done():
                raise SlurmEffectPending(0.05)
            del self._pending[key]
        self._deliveries.pop(assignment, None)
        self._retry_at.pop(assignment, None)

    def defer_delivery(self, assignment: str, seconds: float) -> None:
        self._retry_at[assignment] = monotonic() + seconds

    def retire(self, transport: SharedSlurmResult, *, discard_result: bool) -> None:
        delivery = self._deliveries.get(transport.assignment_id)
        # A completed commit exchange independently authorizes transport cleanup.
        # Do not lose that fact when final release races a finite cleanup turn.
        discard_result = discard_result or delivery is not None and delivery.phase == "cleanup"
        self.forget_delivery(transport.assignment_id)
        probe_key = transport.assignment_id, "terminal-probe"
        probe = self._pending.get(probe_key)
        if probe is not None:
            if not probe.done():
                raise SlurmEffectPending(0.05)
            del self._pending[probe_key]

        def cleanup():
            transport._require_root()
            if transport.path.exists() and (
                discard_result or not (transport.path / "manifest.json").exists()
            ):
                transport.cleanup()

        self.poll(transport.assignment_id, "retirement", cleanup)

    def advance(
        self, transport: SharedSlurmResult, identity: Mapping[str, PlainData],
        call: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
        *, finish_only: bool = False,
    ) -> None:
        assignment = transport.assignment_id
        if monotonic() < self._retry_at.get(assignment, 0):
            return
        encoded = json.dumps(thaw_plain_data(identity), sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = json.loads(encoded)  # Immutable per-effect snapshot across IO.
        delivery = self._deliveries.get(assignment)
        if delivery is None:
            if len(self._deliveries) >= self._owners:
                raise SlurmEffectPending(0.05)
            delivery = _Delivery(encoded, "commit" if finish_only else "inspect")
            self._deliveries[assignment] = delivery
        elif delivery.identity != encoded:
            raise QueueConflictError("Slurm result progress identity conflicts")
        # Finish-only is the coordinator's retained committed result. Replaying
        # commit is safe even if a previous process removed some transport bytes.
        if finish_only and delivery.phase not in {"commit", "cleanup"}:
            self.forget_delivery(assignment)
            delivery = _Delivery(encoded, "commit")
            self._deliveries[assignment] = delivery
        binding = {"assignment_id": assignment, "identity": thaw_plain_data(identity)}
        if delivery.phase == "inspect":
            report = self.poll(assignment, "delivery", lambda: transport.inspect_if_available(identity))
            if report is None:
                del self._deliveries[assignment]
                self._retry_at[assignment] = monotonic() + 5
                return
            delivery.report = report
            delivery.phase = "report"
            return
        if delivery.phase == "report":
            assert delivery.report is not None
            call({**binding, "result_operation": "report", "report": delivery.report.to_dict()})
            delivery.phase = "output"
            return
        if delivery.phase == "output":
            assert delivery.report is not None
            outputs = tuple(item for item in delivery.report.outputs if shared_binding(item.metadata) is None)
            if delivery.index == len(outputs):
                delivery.phase = "commit"
                return
            item = outputs[delivery.index]
            offset = delivery.offset
            if delivery.chunk is None:
                delivery.chunk = self.poll(
                    assignment, "delivery",
                    lambda: transport.read_chunk(item.transfer_id, item.size_bytes, offset),
                )
            chunk = delivery.chunk
            response = call({
                **binding, "result_operation": "output", "transfer_id": item.transfer_id,
                "offset": offset, "data": base64.b64encode(chunk).decode(),
                "final": offset + len(chunk) == item.size_bytes,
            })
            received = response.get("received")
            if type(received) is not int or not offset + len(chunk) <= received <= item.size_bytes:
                raise QueueConflictError("SLURM result output acknowledgement conflicts")
            delivery.offset = received
            delivery.chunk = None
            if received == item.size_bytes:
                delivery.index += 1
                delivery.offset = 0
            return
        if delivery.phase == "commit":
            try:
                transport.acknowledge_commit(identity, call)
            except SlurmEffectPending as pending:
                self.defer_delivery(assignment, pending.retry_after_seconds)
                raise
            delivery.phase = "cleanup"
            return
        assert delivery.phase == "cleanup"

        def cleanup():
            transport._require_root()
            if transport.path.exists():
                transport.cleanup()

        self.poll(assignment, "delivery", cleanup)
        del self._deliveries[assignment]
        self._retry_at[assignment] = monotonic() + 5

    def close(self) -> None:
        self._closed = True
        # A Python timeout cannot revoke a worker's filesystem ownership.
        self._executor.shutdown(wait=True)
        self._pending.clear()
        self._deliveries.clear()
        self._retry_at.clear()
