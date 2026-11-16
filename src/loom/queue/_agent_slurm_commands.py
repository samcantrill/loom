"""Bounded external calls; only the Slurm owner advances journal continuations."""

from __future__ import annotations

from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

from ._slurm_result_transport import SlurmEffectPending
from .errors import QueueConflictError


@dataclass
class _Command:
    lane: str
    kind: str
    steps: Generator[Callable[[], Any], Any, Any]
    future: Future[Any]


class SlurmCommandProgress:
    """One submission slot and independent observation/cancellation slots.

    Capacity is acquired before advancing an intent across its command boundary.
    A process restart discards continuations, never the durable SUBMITTING record;
    ordinary exact-handle reconciliation owns that uncertainty.
    """

    def __init__(self):
        self._executors = {
            "submit": ThreadPoolExecutor(max_workers=1, thread_name_prefix="loom-slurm-submit"),
            "control": ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-slurm-control"),
        }
        self._limits = {"submit": 1, "control": 8}
        self._pending: dict[str, _Command] = {}

    def contains(self, operation_id: str) -> bool:
        return operation_id in self._pending

    def start(
        self, operation_id: str, lane: Literal["submit", "control"],
        steps: Generator[Callable[[], Any], Any, Any], *, kind: str,
    ) -> None:
        if operation_id in self._pending:
            raise QueueConflictError("SLURM command already has an owner")
        if sum(item.lane == lane for item in self._pending.values()) >= self._limits[lane]:
            steps.close()
            raise SlurmEffectPending(0.05)
        try:
            effect = next(steps)
        except StopIteration:
            return
        self._pending[operation_id] = _Command(lane, kind, steps, self._executors[lane].submit(effect))
        raise SlurmEffectPending(0.05)

    def resume(self, operation_id: str) -> str | None:
        current = self._pending.get(operation_id)
        if current is None:
            return
        if not current.future.done():
            raise SlurmEffectPending(0.05)
        try:
            try:
                result = current.future.result()
            except BaseException as error:
                effect = current.steps.throw(error)
            else:
                effect = current.steps.send(result)
        except StopIteration:
            del self._pending[operation_id]
            return current.kind
        except BaseException:
            del self._pending[operation_id]
            raise
        current.future = self._executors[current.lane].submit(effect)
        raise SlurmEffectPending(0.05)

    def close(self) -> None:
        # Never free a slot because a caller stopped waiting. Commands own it
        # until they actually exit. No worker writes a journal or invokes HTTP.
        for executor in self._executors.values():
            executor.shutdown(wait=True)
        for current in self._pending.values():
            current.steps.close()
        self._pending.clear()
