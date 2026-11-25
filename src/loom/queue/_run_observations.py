"""Resume a run's reconciliation on the scheduler after its authority read."""
from __future__ import annotations

from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from ._bulk_operations import BulkOperations
    from ._context_preparation import PreparedAdmissionContext
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import LocalDaemonExecutionOutcome


type Epochs = tuple[str | None, str | None]
type RunSteps = Generator[None, "AuthoritativeRunSnapshot", "LocalDaemonExecutionOutcome"]
type TerminalSteps = Generator[None, "AuthoritativeRunSnapshot", "LocalDaemonExecutionOutcome | None"]


class RunObservationPending(Exception):
    """The remaining run work belongs to a later scheduling turn."""


@dataclass
class RunObservation:
    admission: LocalDaemonAdmission
    epochs: Epochs
    context: PreparedAdmissionContext
    steps: RunSteps
    seen: set[tuple[tuple[str, ...], str, str]] = field(default_factory=set)
    read: Future[AuthoritativeRunSnapshot] | None = None

    def result(self) -> PreparedAdmissionContext:
        return self.context


class RunObservations:
    """Keep a mutable reconciliation on its scheduler thread across read boundaries.

    A superseded read can outlive its generator. It continues to occupy its
    original worker and admission until the actual read returns.
    """

    _capacity = 2

    def __init__(self, wake: Callable[[], None]) -> None:
        self._executor = ThreadPoolExecutor(max_workers=self._capacity, thread_name_prefix="loom-run-observation")
        self._current: dict[str, RunObservation] = {}
        self._retiring: dict[str, Future[AuthoritativeRunSnapshot]] = {}
        self._wake = wake

    def owns(self, admission: LocalDaemonAdmission, epochs: Epochs) -> bool:
        job = self._current.get(admission.admission_id)
        return job is not None and job.admission.revision == admission.revision and job.epochs == epochs

    def invalidate(self, run_uris: set[str], bulk: BulkOperations) -> None:
        for identity, job in tuple(self._current.items()):
            if job.admission.run_uri in run_uris:
                self.discard(identity, bulk)

    def completed(self) -> tuple[RunObservation, ...]:
        self._retiring = {key: read for key, read in self._retiring.items() if not read.done()}
        return tuple(job for job in self._current.values() if job.read is not None and job.read.done())

    def discard(self, identity: str, bulk: BulkOperations) -> None:
        job = self._current.pop(identity, None)
        if job is None:
            return
        job.steps.close()
        if job.read is not None and not job.read.cancel() and not job.read.done():
            self._retiring[identity] = job.read
        bulk.discard(("run", job.admission.run_uri))

    def has_capacity(self) -> bool:
        return len(self._current) + len(self._retiring) < self._capacity

    def awaiting_read(self, admission: LocalDaemonAdmission, epochs: Epochs, bulk: BulkOperations) -> bool:
        identity = admission.admission_id
        if self.owns(admission, epochs):
            return True
        self.discard(identity, bulk)
        return identity in self._retiring

    def can_start(self, identity: str) -> bool:
        return identity not in self._retiring and self.has_capacity()

    def advance(
        self, admission: LocalDaemonAdmission, epochs: Epochs, context: PreparedAdmissionContext,
        create: Callable[[], RunSteps], bulk: BulkOperations,
    ) -> LocalDaemonExecutionOutcome:
        identity = admission.admission_id
        if not self.owns(admission, epochs):
            self.discard(identity, bulk)
            if not self.can_start(identity):
                raise RunObservationPending()
            self._current[identity] = RunObservation(admission, epochs, context, create())
        job = self._current[identity]
        scope = ("run", admission.run_uri)
        try:
            with bulk.offering(scope, across_turns=job.seen):
                if job.read is None:
                    next(job.steps)
                elif job.read.done():
                    job.steps.send(job.read.result())
                else:
                    raise RunObservationPending()
        except StopIteration as settled:
            del self._current[identity]
            bulk.finish_offering(scope, job.seen)
            return settled.value
        except RunObservationPending:
            raise
        except BaseException:
            self.discard(identity, bulk)
            raise

        job.read = self._executor.submit(copy_context().run, job.context[1].open_run, admission.run_uri)
        job.read.add_done_callback(lambda _: self._wake())
        raise RunObservationPending()

    def close(self) -> None:
        for job in self._current.values():
            job.steps.close()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._current.clear()
        self._retiring.clear()
