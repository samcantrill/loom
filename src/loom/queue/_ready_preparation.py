"""Bounded preparation IO with one writer per run/stage and no launch authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from time import monotonic, monotonic_ns
from pathlib import Path
from typing import Any, TYPE_CHECKING, Literal, cast

from loom.pipeline.execution import StageWorkerRequest
from loom.serialization import PlainData

from ._phase_timing import milestone


if TYPE_CHECKING:
    from loom.artifacts import ArtifactRef
    from loom.pipeline.orchestration import StageWorkRecord
    from loom.pipeline.planning import FingerprintContext, StagePlan
    from loom.pipeline.runtime import ResolvedStageRuntimeOptions
    from loom.pipeline.specs import StageSpec
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from ._remote_stage_execution import _RemoteArtifact


@dataclass(frozen=True)
class _PreparedRequest:
    value: Any
    available_ns: int


@dataclass
class _Pending:
    identity: str
    future: Future[Any]
    retry_at: float = 0
    queued_ns: int | None = None


@dataclass
class _StagePreparation:
    identity: str
    resource_class: Literal["cpu", "gpu"] | None = None
    work_id: str | None = None
    speculative: bool = False
    phases: dict[str, _Pending] = field(default_factory=dict)
    retiring: bool = False

    def finished(self) -> bool:
        return all(item.future.done() for item in self.phases.values())

    def prepared_request(self) -> _PreparedRequest | None:
        pending = self.phases.get("request")
        if pending is None:
            return None
        future = pending.future
        if not future.done() or future.cancelled() or future.exception() is not None:
            return None
        return future.result()


class ReadyPreparationPool:
    """Only the scheduling thread mutates membership; workers return evidence.

    Each callable owns its filesystem readers and immutable admitted inputs.
    Request/workspace writes are permitted, never attempts, claims or submission.
    A changed request waits for all old phases before preparing its successor.
    Capacity counts stages, not phases. Completed prerequisites stay owned until
    dispatch, cancellation or supersession; evicting them can livelock dispatch.
    """

    def __init__(self, wake: Callable[[], None], *, max_active_stages: int = 32, max_workers: int = 2,
                 on_ready: Callable[[str], None] | None = None):
        if max_active_stages < 1:
            raise ValueError("max_active_stages must be positive")
        self._workers = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="loom-ready-inputs")
        self._pending: dict[tuple[str, str], _StagePreparation] = {}
        self._capacity = max_active_stages
        self._max_workers = max_workers
        self._on_ready = on_ready
        self._wake = wake
        self._closed = False

    def can_anticipate(self, key: tuple[str, str]) -> bool:
        return self.anticipation_wait(key) is None

    def anticipation_wait(self, key: tuple[str, str]) -> str | None:
        """Admit one early build on a free worker and retain up to four early requests."""
        if key in self._pending:
            return "preparation_owner_held"
        if self._closed or self._max_workers < 2 or len(self._pending) >= self._capacity - 1:
            return "preparation_capacity"
        early = [stage for stage in self._pending.values() if stage.speculative]
        if any(not stage.finished() for stage in early):
            return "early_build_pending"
        if len(early) >= 4:
            return "early_retention_limit"
        busy = sum(not phase.future.done() for stage in self._pending.values() for phase in stage.phases.values())
        return "preparation_capacity" if busy >= self._max_workers else None

    def owns_request(self, work_id: str) -> bool:
        return any(stage.work_id == work_id and not stage.retiring and "request" in stage.phases
                   for stage in self._pending.values())

    def request_queued_ns(self, key: tuple[str, str], work_id: str) -> int | None:
        """Return the actual queue stamp of the retained request for this exact work."""
        stage = self._pending.get(key)
        if stage is None or stage.retiring or stage.work_id != work_id:
            return None
        request = stage.phases.get("request")
        return None if request is None else request.queued_ns

    def request_available_ns(self, key: tuple[str, str], work_id: str) -> int | None:
        """Return the monotonic completion time for the exact successful request."""
        stage = self._pending.get(key)
        if stage is None or stage.retiring or stage.work_id != work_id:
            return None
        request = stage.prepared_request()
        return None if request is None else request.available_ns

    def request_for_descriptors(
        self, key: tuple[str, str], work_id: str,
    ) -> tuple[bool, StageWorkerRequest | None]:
        """Return a completed request when its descriptor phase can begin."""
        stage = self._pending.get(key)
        if stage is None or stage.retiring or stage.work_id != work_id:
            return False, None
        if "input-descriptors" in stage.phases:
            return True, None
        if stage.speculative and any(
            not pending.finished() for pending in self._pending.values() if pending.speculative
        ):
            return True, None
        request = stage.prepared_request()
        return True, None if request is None else request.value

    def poll(
        self, key: tuple[str, str], identity: str,
        prepare: Callable[[], Any], *, phase: str = "request",
        resource_class: Literal["cpu", "gpu"] | None = None,
        work_id: str | None = None, speculative: bool = False,
        attempt_id: str | None = None, admission_id: str | None = None,
    ) -> tuple[Any | None, str | None]:
        if self._closed:
            return None, "stage_preparation_cancelled"
        self._reap_retired()
        stage = self._pending.get(key)
        if stage is not None and (stage.retiring or (phase == "request" and
                (stage.identity != identity or stage.resource_class != resource_class))):
            self.discard(key)
            if key in self._pending:
                return None, "stage_preparation_superseded"
            stage = None
        if stage is not None and phase == "request" and not speculative:
            stage.speculative = False
        if stage is None:
            if phase != "request":
                return None, "stage_preparation_pending"
            if len(self._pending) >= self._capacity or (speculative and not self.can_anticipate(key)):
                return None, "stage_preparation_capacity"
            if (resource_class is not None and self._capacity > 1
                and sum(item.resource_class == resource_class for item in self._pending.values()) >= self._capacity - 1):
                # Preserve one owner for the other resource class. Completed
                # GPU prerequisites cannot otherwise be evicted while their
                # allocation budget is full. This bounds preparation, not jobs.
                return None, "stage_preparation_capacity"
            stage = _StagePreparation(identity, resource_class, work_id, speculative)
            self._pending[key] = stage
        pending = stage.phases.get(phase)
        if pending is not None and pending.identity != identity:
            if not pending.future.done():
                return None, "stage_preparation_superseded"
            del stage.phases[phase]
            pending = None
        if pending is None:
            queued_ns = None
            if phase == "request":
                queued_ns = monotonic_ns()
                attributes: dict[str, PlainData] = {
                    "request_queued_ns": queued_ns, "stage_work_id": work_id, "attempt_id": attempt_id,
                    "admission_id": admission_id, "run_uri": key[0], "stage_name": key[1],
                }
                if work_id is not None:
                    milestone("request_preparation_queued", details=attributes)

                def build_request() -> _PreparedRequest:
                    if work_id is not None:
                        milestone("request_preparation_worker_started", details=attributes)
                    value = prepare()
                    available_ns = monotonic_ns()
                    if work_id is not None:
                        milestone("worker_request_available", request_available_ns=available_ns, details=attributes)
                    return _PreparedRequest(value, available_ns)

                task: Callable[[], Any] = build_request
            else:
                task = prepare
            future = self._workers.submit(copy_context().run, task)
            pending = _Pending(identity, future, queued_ns=queued_ns)
            stage.phases[phase] = pending
            notify = self._on_ready
            if stage.work_id is None or notify is None:
                future.add_done_callback(lambda _: self._wake())
            else:
                future.add_done_callback(lambda _, owner=stage.work_id: notify(owner))
        if not pending.future.done():
            return None, "stage_preparation_pending"
        try:
            result = pending.future.result()
            return (result.value if phase == "request" else result), None
        except Exception:
            if not pending.retry_at:
                pending.retry_at = monotonic() + 5
            elif monotonic() >= pending.retry_at:
                del stage.phases[phase]
            raise

    def discard(self, key: tuple[str, str]) -> None:
        stage = self._pending.get(key)
        if stage is not None:
            stage.retiring = True
            for item in stage.phases.values():
                item.future.cancel()
            self._reap_retired()

    def poll_observation(
        self, key: tuple[str, str], identity: str,
        poll: Callable[[], tuple[Any, str | None]], *, phase: str,
    ) -> tuple[Any | None, str | None]:
        """Retain evidence from another bounded executor under this stage.

        ``poll`` is nonblocking and transfers only completed evidence. Its
        running operations keep their own execution capacity until they exit.
        A stage must already own its request before admitting another phase.
        """
        stage = self._pending.get(key)
        if self._closed or stage is None or stage.retiring:
            return None, "stage_preparation_pending"
        previous = stage.phases.get(phase)
        if previous is not None:
            if not previous.future.done():
                return None, "stage_preparation_pending"
            if previous.identity == identity:
                return previous.future.result(), None
            del stage.phases[phase]
        value, reason = poll()
        if reason is None:
            completed: Future[Any] = Future()
            completed.set_result(value)
            stage.phases[phase] = _Pending(identity, completed)
        return value, reason

    def preparing_runs(self) -> set[str]:
        return {key[0] for key, stage in self._pending.items() if not stage.retiring}

    def retain_run(self, run_uri: str, stage_names: set[str]) -> None:
        """Drop preparations no longer eligible in this run's authority snapshot."""
        for key in tuple(self._pending):
            if key[0] == run_uri and key[1] not in stage_names:
                self.discard(key)
        self._reap_retired()

    def _reap_retired(self) -> None:
        for key, stage in tuple(self._pending.items()):
            if stage.retiring and stage.finished():
                del self._pending[key]

    def close(self) -> None:
        self._closed = True
        # Do not abandon an in-process writer and let a replacement overwrite
        # the same stage's latest request. Process restart repeats preparation.
        self._workers.shutdown(wait=True, cancel_futures=True)
        self._pending.clear()


def prepare_ready_request(
    *, root: Path, record: StageWorkRecord, snapshot: AuthoritativeRunSnapshot,
    stage: StageSpec, stage_plan: StagePlan, fingerprint_context: FingerprintContext,
    runtime: ResolvedStageRuntimeOptions, produced: Mapping[str, Mapping[str, ArtifactRef]],
) -> StageWorkerRequest:
    from loom.pipeline.execution import prepare_stage_attempt
    from loom.pipeline.stores import LocalRunStore
    from loom.pipeline.status import StageStatus
    from loom.pipeline.stores.input_lineage import validate_worker_inputs
    from loom.pipeline._project_contracts import validate_admitted_worker
    from .errors import QueueConflictError, QueueServiceError

    store = LocalRunStore(root)
    attempt = next(a for s in snapshot.stages for a in s.attempts if a.attempt_id == record.attempt_id)
    try:
        raw = store.read_stage_worker_request(record.run_uri, record.stage_name, attempt=None)
        retained = None if raw is None else StageWorkerRequest.from_dict(raw)
    except ValueError as error:
        raise QueueServiceError("retained worker request is invalid") from error
    if retained is not None:
        if retained.attempt != record.attempt:
            prior_interrupted = any(
                a.attempt == retained.attempt and a.status in {StageStatus.FAILED, StageStatus.CANCELLED}
                for s in snapshot.stages if s.stage_name == record.stage_name for a in s.attempts
            )
            if not prior_interrupted or retained.attempt + 1 != record.attempt:
                raise QueueConflictError("managed retry worker request conflicts")
            retained = None
    if retained is None:
        request = prepare_stage_attempt(
            stage_state=store, stage_workspaces=store, local_paths=store,
            reliability=store, prepared_runs=store, config=store,
            run_status=snapshot.status, run_uri=record.run_uri, stage=stage,
            stage_plan=stage_plan, produced_outputs=produced,
            input_bindings=attempt.input_bindings, authority_attempt=attempt,
            fingerprint_context=fingerprint_context, resolved_runtime=runtime,
            metadata={"managed_output_predecessor": next((s.latest_commit.commit_id
                for s in snapshot.stages if s.stage_name == record.stage_name and s.latest_commit is not None), None)},
        )
    else:
        request = retained
        try:
            validate_admitted_worker(store, request, stage, config=store, local_paths=store)
        except ValueError as error:
            raise QueueServiceError("retained worker request differs from admitted work") from error
    try:
        validate_worker_inputs(request, attempt.input_bindings)
    except ValueError as error:
        raise QueueServiceError("worker request differs from retained input bindings") from error
    return request


def inspect_recovery_predecessors(
    references: tuple[Mapping[str, PlainData], ...], roots: Mapping[str, PlainData],
) -> bool:
    """Verify captured closures without holding authority locks or connections."""
    from ._shared_recovery import resolve

    for reference in references:
        resolve(reference, roots)
    return True


def describe_inputs(request: StageWorkerRequest) -> tuple[tuple[_RemoteArtifact, Path], ...]:
    """Inspect bytes independent of the later selected assignment/transfer ID."""
    import hashlib
    from ._remote_stage_execution import _RemoteArtifact, _resident_input_refs, MAX_TRANSFER_BYTES
    from loom.pipeline.stores.shared_artifacts import binding
    from .errors import QueueServiceError

    from loom.pipeline.planning import StageFingerprintRecord
    refs = _resident_input_refs(request.inputs, cast(StageFingerprintRecord, request.fingerprint).to_dict(), request.metadata)
    inspected = []
    total = 0
    for name, ref in sorted(refs.items()):
        descriptor, path = _RemoteArtifact.from_local_ref(
            transfer_id="input-" + hashlib.sha256((name + "\0" + ref.artifact_id).encode()).hexdigest(),
            logical_name=name, ref=ref,
        )
        if binding(descriptor.metadata) is None:
            total += descriptor.size_bytes
        if total > MAX_TRANSFER_BYTES:
            raise QueueServiceError("assignment inputs exceed the configured bound")
        inspected.append((descriptor, path))
    return tuple(inspected)
