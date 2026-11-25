"""Process-local pacing; durable operation records still own recovery identity."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
import json
import logging
import math
from random import uniform
from time import monotonic

from .errors import _AcceptedTimeError


_LOGGER = logging.getLogger(__name__)


@dataclass
class _RecoveryRetry:
    """Bound one failed owner independently, without delaying maintenance."""

    attempts: int = 0
    state: object = None
    signature: object = None
    reported_at: float = -math.inf
    retry_at: float = 0.0

    def observe_progress(self, state: object) -> None:
        if state != self.state:
            self.attempts = 0
            self.retry_at = 0.0
            self.state = state

    def ready(self, state: object) -> bool:
        self.observe_progress(state)
        return monotonic() >= self.retry_at

    def failed(
        self, error: Exception, *, operation_id: str | None, state: object,
        assignment_id: str | None = None, admission_id: str | None = None,
        protocol_operation: str | None = None,
    ) -> float:
        self.observe_progress(state)
        self.attempts += 1
        now = monotonic()
        delay = uniform(0.8, 1.0) * min(5.0, 0.1 * 2 ** min(self.attempts - 1, 6))
        self.retry_at = now + delay
        cause = error.__cause__ or error
        default_step = "resume_retained_assignment" if assignment_id else "reconcile_admission"
        step = getattr(error, "_agent_external_step", default_step)
        dispatched = getattr(error, "possibly_dispatched", None)
        signature = (step, type(cause).__name__, dispatched, state)
        if signature != self.signature or now - self.reported_at >= 30:
            context = {"assignment_id": assignment_id} if assignment_id else {"admission_id": admission_id}
            label = "retained assignment recovery pending" if assignment_id else "admission reconciliation pending"
            if protocol_operation is not None:
                context = {"protocol_operation": protocol_operation, "assignment_id": assignment_id}
                label = "agent transport recovery pending"
            _LOGGER.warning("%s: %s", label, json.dumps({
                **context, "operation_id": operation_id, "step": step,
                **(cause.details() if isinstance(cause, _AcceptedTimeError) else {}),
                "cause_type": type(cause).__name__, "possibly_dispatched": dispatched,
                "retry_count": self.attempts, "retry_delay_seconds": delay,
                "next_retry_monotonic": self.retry_at,
            }, sort_keys=True))
            self.signature = signature
            self.reported_at = now
        return delay

class RecoveryWorkers:
    """Two physical recovery attempts, deduplicated until their results are consumed."""

    def __init__(self, wake: Callable[[], None], name: str) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=name)
        self._pending: dict[str, tuple[str, object, Future[bool]]] = {}
        self._wake = wake
        self._not_before: dict[str, tuple[object, float]] = {}

    def full(self) -> bool:
        return len(self._pending) >= 2

    def submit(self, identity: str, owner_id: str, state: object, apply: Callable[[], bool]) -> None:
        paced = self._not_before.get(identity)
        if identity in self._pending or (paced is not None and paced[0] == state and monotonic() < paced[1]):
            return
        future = self._executor.submit(copy_context().run, apply)
        self._pending[identity] = owner_id, state, future
        future.add_done_callback(lambda _: self._wake())

    def completed(self, interval: float) -> list[tuple[str, str, object, Future[bool]]]:
        now = monotonic()
        for identity, (_, deadline) in tuple(self._not_before.items()):
            if now >= deadline:
                del self._not_before[identity]
        ready = [(identity, owner_id, state, future)
                 for identity, (owner_id, state, future) in self._pending.items() if future.done()]
        for identity, _, state, _ in ready:
            del self._pending[identity]
            self._not_before[identity] = state, now + interval
        return ready

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._pending.clear()
        self._not_before.clear()
