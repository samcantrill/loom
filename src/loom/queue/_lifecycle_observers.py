"""Coordinator-local, best-effort observation of committed native lifecycle facts."""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
import logging
from threading import Lock
from time import monotonic
from typing import Any, NamedTuple, cast

from loom.pipeline.event_sinks import (
    EventObserverLinkRecord,
    EventSinkFailureRecord,
    EventSinkRegistration,
    EventSinkRegistry,
)
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot, BackendRevision
from loom.serialization import PlainData
from ._publication_guards import PublicationGuards
from .errors import QueueConfigError, QueueServiceError

_LOG = logging.getLogger(__name__)
_MUTATIONS = frozenset(
    {
        "transition_run",
        "transition_stage",
        "bind_action_result",
        "ensure_prepared_attempt",
        "confirm_execution_started",
        "finalize_cancellation",
        "record_managed_attempt_terminal",
        "record_output_commit",
        "close_managed_attempt_fence",
        "resume_failed_admission",
    }
)
_NAMES = {"RUNNING": "started", "SUCCEEDED": "completed", "PENDING": "planned"}


def parse_event_sinks(value: object) -> tuple[Mapping[str, object], ...]:
    """Validate protected specifications as data without importing factory code."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise QueueConfigError("event_sinks must be an ordered list")
    registry = EventSinkRegistry()
    specs = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "factory"}:
            raise QueueConfigError("event sink requires name and factory")
        factory = item["factory"]
        if not isinstance(factory, dict) or not isinstance(
            factory.get("_target_"), str
        ):
            raise QueueConfigError("event sink factory requires an installed _target_")
        target = factory["_target_"]
        if "." not in target or any(
            not part.isidentifier() for part in target.split(".")
        ):
            raise QueueConfigError("event sink factory target is invalid")
        try:
            registry.register(item["name"], lambda event, context: None)
        except ValueError as exc:
            raise QueueConfigError("event sink name is invalid or duplicated") from exc
        specs.append(dict(item))
    return tuple(specs)


class _Callback(NamedTuple):
    run_uri: str
    future: Future["_ObserverContext"]
    queued_at: float


class LifecycleObservers:
    """Run-ordered audit facts and process-local callback delivery."""

    def __init__(self, specs: Sequence[Mapping[str, object]] = ()) -> None:
        self._specs = tuple(specs)
        self._registry = EventSinkRegistry()
        self._started = False
        self._lock = Lock()
        self._run_guards = PublicationGuards()
        self._observations: dict[str, deque[tuple[Any, dict[str, Any], float]]] = {}
        self._deliveries: deque[_Callback] = deque()
        self._worker: ThreadPoolExecutor | None = None
        self._audit_worker: ThreadPoolExecutor | None = None
        self._audit: tuple[str, Future[bool]] | None = None
        self._wake: Callable[[], None] | None = None
        self._applying_since: float | None = None

    def enable_delivery(self, wake: Callable[[], None]) -> None:
        self._wake = wake
        self._audit_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loom-audit")
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loom-observer")

    def offer_audit(
        self, run_uri: str | None = None, *, excluded: frozenset[str] = frozenset(),
    ) -> Future[bool] | None:
        """Offer one bounded write batch, or attach to this run's active batch.

        Only the scheduling owner calls this method. A captured snapshot for a
        run excludes a second audit until its next revision-safe point.
        """
        if self._audit_worker is None:
            return None
        if self._audit is not None:
            uri, future = self._audit
            if not future.done():
                return future if run_uri == uri else None
            future.result()
            self._audit = None
        with self._lock:
            candidates = (entry.run_uri for entry in self._deliveries if entry.future.done())
            def eligible(uri: str) -> bool:
                return uri not in excluded and (run_uri is None or run_uri == uri)
            uri = next((uri for uri in candidates if eligible(uri)), None)
            if uri is None and len(self._deliveries) < 16:
                uri = next((uri for uri in self._observations if eligible(uri)), None)
        if uri is None:
            return None
        future = self._audit_worker.submit(self.flush_prepared, uri)
        self._audit = (uri, future)
        wake = self._wake
        if wake is not None:
            future.add_done_callback(lambda _: wake())
        return future

    def backlog(self) -> dict[str, int]:
        with self._lock:
            now = monotonic()
            # Each run queue is FIFO. Its head is sufficient even for verbose runs.
            oldest = min((queue[0][2] for queue in self._observations.values()), default=now)
            oldest = min(oldest, min((item.queued_at for item in self._deliveries), default=now))
            if self._applying_since is not None:
                oldest = min(oldest, self._applying_since)
            return {
                "oldest_pending_ms": int((now - oldest) * 1000),
                "pending_facts": sum(len(queue) for queue in self._observations.values()),
                "pending_callbacks": len(self._deliveries),
                "applying": int(self._applying_since is not None),
            }

    def close_delivery(self) -> None:
        # The coordinator has stopped scheduling and still owns its root. Drain
        # submitted callbacks and apply their revision-bearing evidence here.
        if self._worker is None:
            return
        if self._audit_worker is not None:
            self._audit_worker.shutdown(wait=True)
            self._audit_worker = None
            self._audit = None
        while True:
            self.flush_prepared()
            with self._lock:
                waiting = next((item.future for item in self._deliveries if not item.future.done()), None)
                if not self._observations and not self._deliveries:
                    break
            if waiting is not None:
                from concurrent.futures import wait
                wait((waiting,))
        self._worker.shutdown()
        self._worker = None
        self._wake = None

    def start(self) -> None:
        """Construct only after the coordinator's root and identity guards."""
        from .deployment import _trusted_target

        if self._started:
            return
        registry = EventSinkRegistry()
        for spec in self._specs:
            registration = _trusted_target(spec["factory"], "event sink factory")  # type: ignore[arg-type]
            if not isinstance(registration, EventSinkRegistration):
                raise QueueConfigError(
                    "event sink factory must return EventSinkRegistration"
                )
            registry.register(
                cast(str, spec["name"]),
                registration.sink,
                subscription=registration.subscription,
            )  # type: ignore[arg-type]
        self._registry = registry
        self._started = True

    def authority(self, store: Any, run_uri: str) -> Any:
        from .coordinator_authority import ManagedAdmissionRetryAuthority

        wrapper = (
            _ObservedRetryAuthority
            if isinstance(store, ManagedAdmissionRetryAuthority)
            else _ObservedAuthority
        )
        return wrapper(store, self, run_uri)

    def flush_prepared(self, run_uri: str | None = None) -> bool:
        # A single audit worker runs between this run's readiness windows.
        deadline = monotonic() + 0.1
        for _ in range(32):
            selected = None
            with self._lock:
                completed = next((entry for entry in self._deliveries
                                  if entry.future.done() and (run_uri is None or entry.run_uri == run_uri)), None)
                if completed is not None:
                    self._deliveries.remove(completed)
                    self._applying_since = completed.queued_at
                else:
                    uri = next(iter(self._observations), None) if run_uri is None else run_uri
                    if len(self._deliveries) >= 16 or uri not in self._observations:
                        break
                    assert uri is not None
                    queue = self._observations.pop(uri)
                    store, fact, self._applying_since = queue.popleft()
                    selected = (store, uri, fact)
                    if queue:
                        self._observations[uri] = queue
            try:
                if completed is not None:
                    self._apply_callback_evidence(completed.future.result())
                elif selected is not None:
                    store, uri, fact = selected
                    self._emit_at_safe_point(store, uri, **fact)
            except Exception:
                _LOG.exception("native lifecycle observation failed")
            finally:
                with self._lock:
                    self._applying_since = None
            if monotonic() >= deadline:
                break
        with self._lock:
            return bool((self._observations and len(self._deliveries) < 16)
                        or any(item.future.done() for item in self._deliveries))

    def defer_emit(self, store: Any, run_uri: str, **fact: Any) -> None:
        with self._lock:
            self._observations.setdefault(run_uri, deque()).append((store, fact, monotonic()))

    def emit(self, store: Any, run_uri: str, **fact: Any) -> None:
        # Standalone publication has no coordinator worker or readiness window.
        if self._worker is None:
            self._emit_at_safe_point(store, run_uri, **fact)
        else:
            self.defer_emit(store, run_uri, **fact)
            if self._wake is not None:
                self._wake()

    def _emit_at_safe_point(
        self,
        store: Any,
        run_uri: str,
        *,
        event_type: str,
        revision: BackendRevision,
        stage_name: str | None = None,
        identity: str | None = None,
        payload: Mapping[str, PlainData] | None = None,
    ) -> None:
        """Append after the triggering commit, dispatch only a new exact event."""
        identity = identity or revision.token
        event_id = sha256(
            f"{run_uri}\0{stage_name}\0{event_type}\0{identity}".encode()
        ).hexdigest()
        try:
            with self._run_guards.hold(run_uri):
                find = getattr(store, "_find_audit_event", None)
                existing = (
                    find(run_uri, event_id) if callable(find) else next(
                        (item for item in store.list_audit_events(run_uri)
                         if item.event_id == event_id), None,
                    )
                )
                if existing is not None:
                    return
                if revision.created_at is None:
                    raise QueueServiceError(
                        "native event occurrence time is unavailable"
                    )
                event = PipelineEvent(
                    scope=EventScope.run()
                    if stage_name is None
                    else EventScope.stage(stage_name),
                    event_type=event_type,
                    event_id=event_id,
                    timestamp=revision.created_at,
                    payload=dict(payload or {}),
                )
                record = store.append_audit_event(run_uri, event)
            if self._worker is None:
                self._deliver(store, record, event, deferred=False)
            else:
                future = self._worker.submit(self._deliver, store, record, event, deferred=True)
                with self._lock:
                    queued_at = self._applying_since
                    self._deliveries.append(_Callback(run_uri, future, monotonic() if queued_at is None else queued_at))
                wake = self._wake
                if wake is not None:
                    future.add_done_callback(lambda _: wake())
        except Exception:
            # Audit/delivery failure is diagnostic, never scientific failure.
            _LOG.exception(
                "native lifecycle event or observer evidence was not retained"
            )

    def _deliver(self, store: Any, record: PipelineEventRecord, event: PipelineEvent, *, deferred: bool) -> _ObserverContext:
        _project_event(record.run_uri, event)
        context = _ObserverContext(store, record, deferred=deferred)
        self._registry.dispatch(record, context)
        return context

    def _apply_callback_evidence(self, context: _ObserverContext) -> None:
        if context.pending:
            with self._run_guards.hold(context.run_uri):
                for method, fact in context.pending:
                    context.persist(method, fact)

    def transitions(
        self,
        store: Any,
        before: AuthoritativeRunSnapshot,
        after: AuthoritativeRunSnapshot,
    ) -> None:
        if before.status != after.status:
            name = _NAMES.get(after.status.name, after.status.name.lower())
            if after.status.name == "PLANNED" and before.status.name not in {
                "CREATED",
                "PLANNED",
            }:
                name = "opened"
            self.defer_emit(
                store,
                after.run_uri,
                event_type=f"run.{name}",
                revision=after.revision,
                payload={
                    "previous_status": before.status.value,
                    "status": after.status.value,
                },
            )
        old = {stage.stage_name: stage for stage in before.stages}
        for stage in after.stages:
            previous = old.get(stage.stage_name)
            if previous is not None and previous.status == stage.status:
                continue
            name = _NAMES.get(stage.status.name, stage.status.name.lower())
            self.defer_emit(
                store,
                after.run_uri,
                event_type=f"stage.{name}",
                revision=stage.revision,
                stage_name=stage.stage_name,
                payload={
                    "status": stage.status.value,
                    "reason": None if stage.reason is None else stage.reason.to_dict(),
                },
            )


def _project_event(run_uri: str, event: PipelineEvent) -> None:
    from loom.pipeline.stores import LocalRunStore, run_uri_to_path

    try:
        LocalRunStore(run_uri_to_path(run_uri).parent).append_event(run_uri, event)
    except Exception:
        _LOG.exception(
            "native event local projection failed; authority evidence remains retained"
        )


class _ObserverContext:
    def __init__(self, store: Any, record: PipelineEventRecord, *, deferred: bool = False) -> None:
        self.pending: list[tuple[str, Any]] = []
        self._deferred = deferred
        self._store, self.run_uri = store, record.run_uri
        self.event_reference = record.to_event_reference()

    def record_event_sink_failure(self, failure: EventSinkFailureRecord) -> None:
        self._write("append_event_sink_failure", failure)

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None:
        self._write("append_event_observer_link", link)

    def _write(self, method: str, fact: Any) -> None:
        if fact.event_reference != self.event_reference:
            raise QueueServiceError("observer fact event identity conflicts")
        if self._deferred:
            self.pending.append((method, fact))
        else:
            self.persist(method, fact)

    def persist(self, method: str, fact: Any) -> None:
        try:
            getattr(self._store, method)(self.run_uri, fact)
            from loom.pipeline.stores import LocalRunStore, run_uri_to_path

            projection = LocalRunStore(run_uri_to_path(self.run_uri).parent)
            getattr(projection, method)(self.run_uri, fact)
        except Exception:
            _LOG.exception(
                "native observer fact persistence failed; evidence is unavailable"
            )
            raise


class _ObservedAuthority:
    def __init__(self, store: Any, observers: LifecycleObservers, run_uri: str) -> None:
        self._store, self._observers, self._run_uri = store, observers, run_uri
        for name in (
            "list_audit_events",
            "append_audit_event",
            "append_event_sink_failure",
            "read_event_sink_failures",
            "append_event_observer_link",
            "read_event_observer_links",
        ):
            if not callable(getattr(store, name, None)):
                raise QueueServiceError(
                    "selected authority lacks native observer capability"
                )
        # Authenticate/probe before admission or execution mutations, including empty runs.
        find = getattr(store, "_find_audit_event", None)
        if callable(find):
            find(run_uri, "")
        else:
            store.list_audit_events(run_uri)

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._store, name)
        if name not in _MUTATIONS:
            return method

        def commit(*args: Any, **kwargs: Any) -> Any:
            with self._observers._run_guards.hold(self._run_uri):
                if name == "ensure_prepared_attempt":
                    # This operation only prepares one PENDING attempt. Its
                    # durable receipt already carries the exact stage/revision;
                    # two whole-run snapshots per stage made large independent
                    # graphs quadratic and retained all those snapshots in RAM.
                    result = method(*args, **kwargs)
                    attempt = result.attempt
                    self._observers.defer_emit(
                        self._store, self._run_uri,
                        event_type="stage.planned", stage_name=attempt.stage_name,
                        revision=attempt.revision,
                        payload={"status": attempt.status.value, "reason": None},
                    )
                    return result
                before = self._store.open_run(self._run_uri)
                result = method(*args, **kwargs)
                after = self._store.open_run(self._run_uri)
                self._observers.transitions(self._store, before, after)
                return result

        return commit


class _ObservedRetryAuthority(_ObservedAuthority):
    def resume_failed_admission(self, *args: Any, **kwargs: Any) -> Any:
        return self.__getattr__("resume_failed_admission")(*args, **kwargs)
