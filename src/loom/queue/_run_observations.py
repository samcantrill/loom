"""Resume a run's reconciliation on the scheduler after its authority read."""
from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Generator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from time import monotonic_ns
from typing import TYPE_CHECKING, Any

from ._completion_inbox import CompletionInbox
from ._phase_timing import milestone

if TYPE_CHECKING:
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from ._bulk_operations import BulkOperations
    from ._context_preparation import PreparedAdmissionContext
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import LocalDaemonExecutionOutcome


type Epochs = tuple[str | None, str | None]
# A bare yield requests the fresh run snapshot and its audit safe point.
# A callable requests only its original operation, preserving the revision window.
type ObservationSteps[T] = Generator[Callable[[], Any] | None, Any, T]
type RunSteps = ObservationSteps["LocalDaemonExecutionOutcome"]
type TerminalSteps = ObservationSteps["LocalDaemonExecutionOutcome | None"]


class RunObservationPending(Exception):
    """The remaining run work belongs to a later scheduling turn."""


@dataclass
class RunObservation:
    admission: LocalDaemonAdmission
    epochs: Epochs
    context: PreparedAdmissionContext
    steps: RunSteps
    seen: set[tuple[tuple[str, ...], str, str]] = field(default_factory=set)
    read: Future[Any] | None = None

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
        self._retiring: dict[str, Future[Any]] = {}
        self._waiting: dict[str, Callable[[], Any]] = {}
        self._before_read = before_read
        self._completed = CompletionInbox[tuple[str, int, Epochs]](wake, maximum=None)
        self._ready: dict[str, None] = {}

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
            token = identity, job.admission.revision, job.epochs
            job.read.add_done_callback(lambda _, owner=token: self._completed.post(owner))

    def completed(self) -> tuple[RunObservation, ...]:
        self._retiring = {key: read for key, read in self._retiring.items() if not read.done()}
        self._start_reads()
        for identity, revision, epochs in self._completed.take(self._admissions):
            job = self._current.get(identity)
            if (job is not None and job.admission.revision == revision and job.epochs == epochs
                and job.read is not None and job.read.done()):
                self._ready[identity] = None
        # Retain an offered completion until its owner actually consumes it.
        # A retry deadline or interrupted scheduler turn can defer application.
        return tuple(self._current[identity] for identity in self._ready)

    def discard(self, identity: str, bulk: BulkOperations) -> None:
        self._ready.pop(identity, None)
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
        self._ready.pop(identity, None)
        if identity in self._waiting:
            raise RunObservationPending()
        scope = ("run", admission.run_uri)
        try:
            with bulk.offering(scope, across_turns=job.seen):
                if job.read is None:
                    request = next(job.steps)
                elif job.read.done():
                    try:
                        result = job.read.result()
                    except Exception as error:
                        request = job.steps.throw(error)
                    else:
                        request = job.steps.send(result)
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
        audit = self._before_read(admission.run_uri) if request is None and self._before_read is not None else None
        def load():
            if audit is not None:
                audit.result()
            if request is None:
                return captured.run(job.context[1].open_run, admission.run_uri)
            return captured.run(request)
        self._waiting[identity] = load
        self._current.move_to_end(identity)
        self._start_reads()
        raise RunObservationPending()

    def close(self) -> None:
        for job in self._current.values():
            job.steps.close()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._current.clear()
        self._ready.clear()
        self._waiting.clear()
        self._retiring.clear()

@dataclass
class _DispatchRead:
    admission: LocalDaemonAdmission
    epochs: Epochs
    future: Future[tuple[int, AuthoritativeRunSnapshot | Exception]]
    work_ids: set[str] = field(default_factory=set)
    selected: set[str] = field(default_factory=set)


class DispatchObservations:
    """Keep a demanded read until dispatch or request preparation consumes it."""

    def __init__(self, wake: Callable[[], None]) -> None:
        self._hint_after = ""
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-dispatch-observation")
        self._reads: dict[str, _DispatchRead] = {}
        self._retiring: dict[str, Future[tuple[int, AuthoritativeRunSnapshot | Exception]]] = {}
        self._consumed: dict[str, tuple[int, Epochs, AuthoritativeRunSnapshot]] = {}
        self._wake = wake

    def requested_runs(self) -> set[str]:
        return {read.admission.run_uri for read in self._reads.values() if read.work_ids}

    def requested_admissions(self) -> set[str]:
        return {key for key, read in self._reads.items() if read.work_ids}

    def invalidate_admission(self, identity: str) -> None:
        self._consumed.pop(identity, None)
        read = self._reads.pop(identity, None)
        if read is not None and not read.future.cancel() and not read.future.done():
            self._retiring[identity] = read.future

    def begin_cycle(
        self, invalidated: set[str], epochs: Epochs, interval: float,
        revisions: Mapping[str, int], ready_ids: Callable[[set[str]], set[str]],
        offer: Callable[[str], None],
    ) -> None:
        self._consumed.clear()
        self._retiring = {key: future for key, future in self._retiring.items() if not future.done()}
        completed = []
        ready = ready_ids({work for read in self._reads.values() for work in read.work_ids})
        for key, read in tuple(self._reads.items()):
            if read.epochs != epochs or read.admission.run_uri in invalidated:
                self.invalidate_admission(key)
            elif read.work_ids:
                read.work_ids.intersection_update(ready)
                read.selected.intersection_update(read.work_ids)
                if revisions.get(key) != read.admission.revision or not read.work_ids:
                    self.invalidate_admission(key)
                elif read.future.done():
                    # Hints can coalesce or overflow. The owner offers its outstanding
                    # work again until the scheduler actually takes the result.
                    completed.extend(read.work_ids)
            elif read.future.done() and monotonic_ns() - read.future.result()[0] > interval * 1e9:
                self.invalidate_admission(key)

        if completed:
            completed.sort()
            start = bisect_right(completed, self._hint_after)
            # Rotate even when a permanently blocked peer cannot consume its hint.
            for offset in range(min(32, len(completed))):
                self._hint_after = completed[(start + offset) % len(completed)]
                offer(self._hint_after)

    def selected(self, admission_id: str, work_id: str) -> bool:
        read = self._reads.get(admission_id)
        return read is not None and work_id in read.selected

    def retire_work(self, admission_id: str, work_id: str) -> None:
        read = self._reads.get(admission_id)
        if read is not None and work_id in read.work_ids:
            read.selected.discard(work_id)
            read.work_ids.remove(work_id)
            if not read.work_ids:
                self.invalidate_admission(admission_id)

    def snapshot_for_preparation(self, admission: LocalDaemonAdmission, epochs: Epochs) -> AuthoritativeRunSnapshot | None:
        read = self._reads.get(admission.admission_id)
        if (read is None or read.admission.revision != admission.revision or read.epochs != epochs
            or not read.future.done()):
            return None
        _, result = read.future.result()
        return None if isinstance(result, Exception) else result

    def transferred(self, admission: LocalDaemonAdmission, epochs: Epochs, work_id: str) -> None:
        """Request preparation now owns this work. Peers still own their handoff."""
        read = self._reads.get(admission.admission_id)
        if (read is None or work_id not in read.work_ids or not read.future.done()
            or read.epochs != epochs or read.admission.revision != admission.revision):
            return
        completed, result = read.future.result()
        if isinstance(result, Exception):
            return  # The selection owner handles failed authority reads and retry.
        consumed = monotonic_ns()
        milestone("dispatch_observation_consumed", admission_id=admission.admission_id,
                  stage_work_id=work_id, completed_ns=completed, consumed_ns=consumed,
                  completion_wait_ns=consumed - completed)
        self._consumed[admission.admission_id] = admission.revision, epochs, result
        read.selected.discard(work_id)
        read.work_ids.remove(work_id)
        if not read.work_ids:
            del self._reads[admission.admission_id]

    def _start(
        self, admission: LocalDaemonAdmission, epochs: Epochs, load: Callable[[], AuthoritativeRunSnapshot],
        work_ids: set[str], selected: str | None = None,
    ) -> None:
        identity = admission.admission_id
        if identity in self._retiring or len(self._reads) >= 32:
            return
        limit = 2 if work_ids else 1
        if sum(not item.future.done() for item in self._reads.values()) + len(self._retiring) >= limit:
            return

        def capture() -> tuple[int, AuthoritativeRunSnapshot | Exception]:
            try:
                snapshot = load()
            except Exception as error:
                return monotonic_ns(), error
            return monotonic_ns(), snapshot

        future = self._workers.submit(copy_context().run, capture)
        self._reads[identity] = _DispatchRead(admission, epochs, future, work_ids, {selected} if selected is not None else set())
        if work_ids:
            future.add_done_callback(lambda _: self._wake())

    def poll(
        self, admission: LocalDaemonAdmission, epochs: Epochs, load: Callable[[], AuthoritativeRunSnapshot],
        *, work_id: str, peers: set[str],
    ) -> AuthoritativeRunSnapshot | None:
        identity = admission.admission_id
        previous = self._consumed.get(identity)
        if previous is not None and previous[:2] == (admission.revision, epochs):
            if identity not in self._reads:
                self._start(admission, epochs, load, set())
            return previous[2]
        read = self._reads.get(identity)
        if read is not None and (read.admission.revision != admission.revision or read.epochs != epochs):
            self.invalidate_admission(identity)
            read = None
        if read is None:
            self._start(admission, epochs, load, peers | {work_id}, work_id)
            return None
        if not read.work_ids:
            read.work_ids.update(peers)
            read.future.add_done_callback(lambda _: self._wake())
        read.work_ids.add(work_id)
        read.selected.add(work_id)
        if not read.future.done():
            return None
        _, result = read.future.result()
        if isinstance(result, Exception):
            self.invalidate_admission(identity)
            raise result
        return result

    def close(self) -> None:
        self._workers.shutdown(wait=True, cancel_futures=True)
        self._reads.clear()
        self._retiring.clear()
