"""Bounded preparation IO with one writer per run/stage and no launch authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from time import monotonic
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast

from loom.pipeline.execution import StageWorkerRequest
from loom.serialization import PlainData


if TYPE_CHECKING:
    from loom.artifacts import ArtifactRef
    from loom.pipeline.orchestration import StageWorkRecord
    from loom.pipeline.planning import FingerprintContext, StagePlan
    from loom.pipeline.runtime import ResolvedStageRuntimeOptions
    from loom.pipeline.specs import StageSpec
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from ._remote_stage_execution import _RemoteArtifact


@dataclass
class _Pending:
    identity: str
    future: Future[Any]
    retry_at: float = 0


class ReadyPreparationPool:
    """Only the scheduling thread mutates membership; workers return evidence.

    Each callable owns its filesystem readers and immutable admitted inputs.
    Request/workspace writes are permitted, never attempts, claims or submission.
    A changed request waits for an old writer before preparing its successor.
    """

    def __init__(self, wake: Callable[[], None]):
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-ready-inputs")
        self._pending: dict[tuple[str, str], _Pending] = {}
        self._wake = wake
        self._closed = False

    def poll(
        self, key: tuple[str, str], identity: str,
        prepare: Callable[[], Any],
    ) -> tuple[Any | None, str | None]:
        if self._closed:
            return None, "stage_preparation_cancelled"
        pending = self._pending.get(key)
        if pending is not None and pending.identity != identity:
            if not pending.future.done():
                return None, "stage_preparation_superseded"
            del self._pending[key]
            pending = None
        if pending is None:
            if len(self._pending) >= 8:
                finished = next((k for k, item in self._pending.items() if item.future.done()), None)
                if finished is None:
                    return None, "stage_preparation_capacity"
                del self._pending[finished]
            future = self._workers.submit(copy_context().run, prepare)
            pending = _Pending(identity, future)
            self._pending[key] = pending
            future.add_done_callback(lambda _: self._wake())
        if not pending.future.done():
            return None, "stage_preparation_pending"
        try:
            return pending.future.result(), None
        except Exception:
            if not pending.retry_at:
                pending.retry_at = monotonic() + 5
            elif monotonic() >= pending.retry_at:
                del self._pending[key]
            raise

    def discard(self, key: tuple[str, str]) -> None:
        pending = self._pending.get(key)
        if pending is not None and pending.future.done():
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
    from .errors import QueueConflictError

    store = LocalRunStore(root)
    attempt = next(a for s in snapshot.stages for a in s.attempts if a.attempt_id == record.attempt_id)
    raw = store.read_stage_worker_request(record.run_uri, record.stage_name, attempt=None)
    if raw is not None:
        previous = StageWorkerRequest.from_dict(raw)
        if previous.attempt != record.attempt:
            prior_failed = any(
                a.attempt == previous.attempt and a.status is StageStatus.FAILED
                for s in snapshot.stages if s.stage_name == record.stage_name for a in s.attempts
            )
            if not prior_failed or previous.attempt + 1 != record.attempt:
                raise QueueConflictError("managed retry worker request conflicts")
            raw = None
    if raw is None:
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
        request = StageWorkerRequest.from_dict(raw)
        validate_admitted_worker(store, request, stage, config=store, local_paths=store)
    validate_worker_inputs(request, attempt.input_bindings)
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
