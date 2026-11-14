"""Disposable bounded input inspection; durable owners alone authorize dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
import logging
from threading import Event, Lock
from time import monotonic

from loom.fingerprints import hash_mapping
from loom.serialization import PlainData, freeze_plain_data

from .errors import QueueServiceError
from .shared_execution import (
    InputValidationIOError, InputValidationProgress, require_bindings,
)


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationObservation:
    reason: str | None
    progress: InputValidationProgress | None = None
    error: Exception | None = None


@dataclass
class _Inspection:
    work_id: str
    identity: str
    run_uri: str | None = None
    stage_name: str | None = None
    reason: str | None = "input_validation_pending"
    cancelled: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    progress: InputValidationProgress | None = None
    future: Future[None] | None = None
    retry_at: float = 0
    failures: int = 0

    def report(self, progress: InputValidationProgress) -> None:
        with self.lock:
            self.progress = progress

    def observed(self, reason: str | None, error: Exception | None = None) -> ValidationObservation:
        with self.lock:
            self.reason = reason
            return ValidationObservation(reason, self.progress, error)


class InputValidationPool:
    """Scheduling-thread-owned cache of current inspections, never launch grants.

    Running superseded work still consumes capacity until it actually exits.
    Successful observations must be consumed only after current durable owners
    have revalidated the captured stage/attempt/configuration identity. Restart
    creates a fresh pool and repeats inspection; no result files are retained.
    """

    def __init__(self, wake: Callable[[], None], *, workers: int = 2, max_pending: int = 8):
        if workers < 1 or max_pending < workers:
            raise ValueError("validation capacity must cover positive worker count")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="loom-input-validation")
        self._max_pending = max_pending
        self._wake = wake
        self._current: dict[str, _Inspection] = {}
        self._retired: list[_Inspection] = []
        self._closed = False
        self._visible: tuple[_Inspection, ...] = ()

    def discard(self, work_id: str) -> None:
        item = self._current.pop(work_id, None)
        self._visible = tuple(self._current.values())
        if item is not None:
            item.cancelled.set()
            assert item.future is not None
            item.future.cancel()
            if not item.future.done():
                self._retired.append(item)

    def retain(self, current: Callable[[str], bool]) -> None:
        """Cancel obsolete work without waiting or releasing running-worker slots."""
        for work_id in tuple(self._current):
            if not current(work_id):
                self.discard(work_id)
        self._retired = [item for item in self._retired if item.future is not None and not item.future.done()]

    def poll(
        self, work_id: str, identity: Mapping[str, PlainData],
        required: Mapping[str, PlainData], roots: Mapping[str, PlainData],
    ) -> ValidationObservation:
        # Snapshot before crossing threads. Root paths/qualifications and the
        # selected scope are part of validity, not just the profile name.
        frozen_scope = freeze_plain_data(required)
        frozen_roots = freeze_plain_data(roots)
        digest = hash_mapping({"identity": identity, "scope": frozen_scope, "roots": frozen_roots})
        item = self._current.get(work_id)
        if item is not None and item.identity != digest:
            self.discard(work_id)
            item = None
        self._retired = [old for old in self._retired if old.future is not None and not old.future.done()]
        if self._closed:
            return ValidationObservation("input_validation_cancelled")
        if item is None:
            if len(self._current) + len(self._retired) >= self._max_pending:
                finished = next((key for key, old in self._current.items()
                                 if old.future is not None and old.future.done()), None)
                if finished is None:
                    return ValidationObservation("input_validation_capacity")
                self.discard(finished)
            worker = identity.get("worker_request", {})
            worker = worker if isinstance(worker, Mapping) else {}
            item = _Inspection(work_id, digest, worker.get("run_uri"), worker.get("stage_name"))
            self._current[work_id] = item
            self._visible = tuple(self._current.values())
            self._start(item, frozen_scope, frozen_roots)
        assert item.future is not None
        if not item.future.done():
            return item.observed("input_validation_pending")
        try:
            item.future.result()
        except CancelledError as error:
            return item.observed("input_validation_cancelled", error)
        except (QueueServiceError, OSError) as error:
            # Inputs can be repaired in place. Retry both invalid entries and
            # IO failures, paced per exact request, without permitting launch.
            if not item.retry_at:
                item.failures += 1
                item.retry_at = monotonic() + min(60, 5 * 2 ** min(item.failures - 1, 4))
                _LOGGER.warning("input inspection refused for stage work %s (attempt %s): %s",
                                item.work_id, item.failures, error)
            elif monotonic() >= item.retry_at:
                item.retry_at = 0
                self._start(item, frozen_scope, frozen_roots)
            reason = (
                "input_validation_storage_unavailable"
                if isinstance(error, (InputValidationIOError, OSError))
                else "input_validation_invalid"
            )
            return item.observed(reason, error)
        return item.observed(None)

    def _start(self, item: _Inspection, scope: Mapping[str, PlainData], roots: Mapping[str, PlainData]) -> None:
        item.future = self._executor.submit(
            copy_context().run, require_bindings, scope, roots,
            cancelled=item.cancelled.is_set, progress=item.report,
        )
        item.future.add_done_callback(lambda _: self._wake())

    def observations(self, run_uri: str) -> dict[str, PlainData]:
        """Read process-local diagnostics without a scheduling lock or IO.

        An immutable membership snapshot is published by the scheduling owner;
        each entry's progress has its own short lock. These observations never
        authorize launch and disappear when this coordinator restarts.
        """
        items: list[PlainData] = []
        for item in self._visible:
            if item.run_uri != run_uri:
                continue
            with item.lock:
                progress = item.progress
                items.append({
                    "stage_work_id": item.work_id,
                    "stage": item.stage_name,
                    "reason": item.reason,
                    "progress": None if progress is None else {
                        "entries_examined": progress.entries_examined,
                        "elapsed_seconds": progress.elapsed_seconds,
                        "last_progress_at": progress.last_progress_at,
                    },
                })
        return {"availability": "available", "consistency": "process_local", "inspections": items}

    def close(self) -> None:
        """Stop admission and request cancellation without waiting on NFS IO.

        Python's interpreter exit still joins executor threads. A supervisor
        may need to terminate the process if kernel IO never returns; creating
        replacement pools in the same process is not a shutdown mechanism.
        """
        self._closed = True
        for work_id in tuple(self._current):
            self.discard(work_id)
        self._executor.shutdown(wait=False, cancel_futures=True)
