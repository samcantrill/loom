"""Opt-in timing for one request for a freshly loaded admission context."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import count
from time import monotonic_ns
from typing import TYPE_CHECKING

from loom.serialization import PlainData
from ._phase_timing import milestone

if TYPE_CHECKING:
    from ._context_preparation import PreparedAdmissionContext
    from .local_daemon import LocalDaemonAdmission

_request_ids = count(1)


@dataclass(slots=True)
class ContextTiming:
    admission: LocalDaemonAdmission
    epochs: tuple[str | None, str | None]
    source: str
    request_id: int = field(default_factory=lambda: next(_request_ids))
    installed_ns: int | None = None
    resume_work_id: str | None = None
    advanced: bool = False
    discarded: bool = False

    def event(self, action: str, **details: PlainData) -> None:
        milestone(
            action, operation_id=self.admission.authority_operation_id,
            admission_id=self.admission.admission_id, admission_revision=self.admission.revision,
            coordinator_epoch=self.epochs[0], scheduling_epoch=self.epochs[1],
            context_request_id=self.request_id, source=self.source, details=details,
        )

    def installed(self) -> None:
        if self.installed_ns is None:
            self.installed_ns = monotonic_ns()

    def identity(self) -> dict[str, PlainData]:
        return {"context_request_id": self.request_id, "admission_revision": self.admission.revision,
                "coordinator_epoch": self.epochs[0], "scheduling_epoch": self.epochs[1]}

    def advance(self, consumer: str) -> None:
        # First use and retirement are owned by the scheduling thread.
        if not self.advanced and not self.discarded:
            self.advanced = True
            self.event("context_consumer_advanced", consumer=consumer)

    def discard(self, owner: str, reason: str) -> None:
        if not self.discarded:
            self.discarded = True
            self.event("context_discarded", owner=owner, reason=reason)


# Available only inside the loader. The scoped authority carries the identity
# to its actual consumer, including a run generator resumed on a later turn.
current_load: ContextVar[ContextTiming | None] = ContextVar("loom_context_load", default=None)


def timing_for(context: PreparedAdmissionContext) -> ContextTiming | None:
    return getattr(context[1], "_context_timing", None)
