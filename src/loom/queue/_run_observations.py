"""Resume a run's reconciliation on the scheduler after its authority read."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from time import monotonic
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

    _workers = 2
    _admissions = 32

    def __init__(self, wake: Callable[[], None], before_read: Callable[[str], Future[bool] | None] | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="loom-run-observation")
        self._current: OrderedDict[str, RunObservation] = OrderedDict()
        self._retiring: dict[str, Future[AuthoritativeRunSnapshot]] = {}
        self._waiting: dict[str, Callable[[], AuthoritativeRunSnapshot]] = {}
        self._wake = wake
        self._before_read = before_read

    def pending_runs(self) -> frozenset[str]:
        return frozenset(job.admission.run_uri for job in self._current.values())

    def owns(self, admission: LocalDaemonAdmission, epochs: Epochs) -> bool:
        job = self._current.get(admission.admission_id)
        return job is not None and job.admission.revision == admission.revision and job.epochs == epochs

    def invalidate(self, run_uris: set[str], bulk: BulkOperations) -> None:
        for identity, job in tuple(self._current.items()):
            if job.admission.run_uri in run_uris:
                self.discard(identity, bulk)

    def _start_reads(self) -> None:
        occupied = len(self._retiring) + sum(
            item.read is not None and not item.read.done() for item in self._current.values()
        )
        for identity in tuple(self._waiting)[:max(0, self._workers - occupied)]:
            job = self._current[identity]
            job.read = self._executor.submit(self._waiting.pop(identity))
            job.read.add_done_callback(lambda _: self._wake())

    def completed(self) -> tuple[RunObservation, ...]:
        self._retiring = {key: read for key, read in self._retiring.items() if not read.done()}
        self._start_reads()
        ready = tuple(job for job in self._current.values() if job.read is not None and job.read.done())
        if len(ready) > self._workers:
            self._wake()
        return ready[:self._workers]

    def discard(self, identity: str, bulk: BulkOperations) -> None:
        job = self._current.pop(identity, None)
        if job is None:
            return
        job.steps.close()
        self._waiting.pop(identity, None)
        if job.read is not None and not job.read.cancel() and not job.read.done():
            self._retiring[identity] = job.read
        bulk.discard(("run", job.admission.run_uri))

    def has_capacity(self) -> bool:
        return len(self._current) + len(self._retiring) < self._admissions

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
        if identity in self._waiting:
            raise RunObservationPending()
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

        # A long run returns its physical read slot after each slice. Waiting
        # peers get a turn before this run requests its next observation.
        captured = copy_context()
        job.read = None
        audit = self._before_read(admission.run_uri) if self._before_read is not None else None
        def load():
            if audit is not None:
                audit.result()
            return captured.run(job.context[1].open_run, admission.run_uri)
        self._waiting[identity] = load
        self._current.move_to_end(identity)
        self._start_reads()
        raise RunObservationPending()

    def close(self) -> None:
        for job in self._current.values():
            job.steps.close()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._current.clear()
        self._waiting.clear()
        self._retiring.clear()

@dataclass
class _DispatchRead:
    admission: LocalDaemonAdmission
    epochs: Epochs
    future: Future[tuple[float, AuthoritativeRunSnapshot | Exception]]
    requested: bool = False

    def notify_when_ready(self, wake: Callable[[], None]) -> None:
        if not self.requested:
            self.requested = True
            self.future.add_done_callback(lambda _: wake())


class DispatchObservations:
    """Read READY authority without occupying the scheduler or reserving capacity.

    The selector consumes each result once. A read started in anticipation of
    another preparation step only wakes the selector if it asks for that result.
    """

    def __init__(self, wake: Callable[[], None]) -> None:
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-dispatch-observation")
        self._reads: dict[str, _DispatchRead] = {}
        self._retiring: dict[str, Future[tuple[float, AuthoritativeRunSnapshot | Exception]]] = {}
        self._wake = wake

    def _discard(self, identity: str) -> None:
        read = self._reads.pop(identity)
        if not read.future.cancel() and not read.future.done():
            self._retiring[identity] = read.future

    def begin_cycle(self, invalidated: set[str], epochs: Epochs, interval: float) -> None:
        self._retiring = {key: future for key, future in self._retiring.items() if not future.done()}
        for key, read in tuple(self._reads.items()):
            if read.epochs != epochs or read.admission.run_uri in invalidated:
                self._discard(key)
            elif read.future.done() and monotonic() - read.future.result()[0] > (
                max(1.0, interval) if read.requested else interval
            ):
                self._discard(key)

    def _start(
        self, admission: LocalDaemonAdmission, epochs: Epochs, load: Callable[[], AuthoritativeRunSnapshot],
        *, requested: bool,
    ) -> None:
        identity = admission.admission_id
        if identity in self._retiring or len(self._reads) >= 32:
            return
        # Keep a real worker available for demand from another READY run.
        limit = 2 if requested else 1
        if sum(not item.future.done() for item in self._reads.values()) + len(self._retiring) >= limit:
            return

        def capture() -> tuple[float, AuthoritativeRunSnapshot | Exception]:
            try:
                snapshot = load()
            except Exception as error:
                return monotonic(), error
            return monotonic(), snapshot

        future = self._workers.submit(copy_context().run, capture)
        read = _DispatchRead(admission, epochs, future)
        self._reads[identity] = read
        if requested:
            read.notify_when_ready(self._wake)

    def poll(
        self, admission: LocalDaemonAdmission, epochs: Epochs, load: Callable[[], AuthoritativeRunSnapshot],
    ) -> AuthoritativeRunSnapshot | None:
        identity = admission.admission_id
        read = self._reads.get(identity)
        if read is not None and (read.admission.revision != admission.revision or read.epochs != epochs):
            self._discard(identity)
            read = None
        if read is None:
            self._start(admission, epochs, load, requested=True)
            return None
        if not read.future.done():
            read.notify_when_ready(self._wake)
            return None
        del self._reads[identity]
        _, result = read.future.result()
        if isinstance(result, Exception):
            raise result
        self._start(admission, epochs, load, requested=False)
        return result

    def close(self) -> None:
        self._workers.shutdown(wait=True, cancel_futures=True)
        self._reads.clear()
        self._retiring.clear()
