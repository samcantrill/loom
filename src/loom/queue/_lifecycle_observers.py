"""Coordinator-local, best-effort observation of committed native lifecycle facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import logging
from threading import RLock
from typing import Any, cast

from loom.pipeline.event_sinks import (
    EventObserverLinkRecord,
    EventSinkFailureRecord,
    EventSinkRegistration,
    EventSinkRegistry,
)
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot, BackendRevision
from loom.serialization import PlainData
from .errors import QueueConfigError, QueueServiceError

_LOG = logging.getLogger(__name__)
_MUTATIONS = frozenset(
    {
        "transition_run",
        "transition_stage",
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


class LifecycleObservers:
    """One process's explicit callbacks; no history replay or delivery queue."""

    def __init__(self, specs: Sequence[Mapping[str, object]] = ()) -> None:
        self._specs = tuple(specs)
        self._registry = EventSinkRegistry()
        self._started = False
        self._lock = RLock()
        self._prepared: list[
            tuple[Any, AuthoritativeRunSnapshot, AuthoritativeRunSnapshot]
        ] = []
        self._observations: list[tuple[Any, str, dict[str, Any]]] = []

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

    def flush_prepared(self, run_uri: str | None = None) -> None:
        # Emit on the coordinator between readiness windows: observer revisions
        # must not invalidate an in-flight preparation cursor. The transient
        # facts carry their original commit revision and time; crash loss is
        # intentionally best effort, with no durable delivery queue.
        with self._lock:
            pending = [
                item
                for item in self._prepared
                if run_uri is None or item[2].run_uri == run_uri
            ]
            self._prepared = [
                item
                for item in self._prepared
                if run_uri is not None and item[2].run_uri != run_uri
            ]
            observations = [
                item
                for item in self._observations
                if run_uri is None or item[1] == run_uri
            ]
            self._observations = [
                item
                for item in self._observations
                if run_uri is not None and item[1] != run_uri
            ]
        for store, before, after in pending:
            self.transitions(store, before, after)
        for store, uri, fact in observations:
            self.emit(store, uri, **fact)

    def defer_emit(self, store: Any, run_uri: str, **fact: Any) -> None:
        with self._lock:
            self._observations.append((store, run_uri, fact))

    def emit(
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
            with self._lock:
                if any(
                    item.event_id == event_id
                    for item in store.list_audit_events(run_uri)
                ):
                    return
                if revision.created_at is None:
                    raise QueueServiceError(
                        "native event occurrence time is unavailable"
                    )
                record = store.append_audit_event(
                    run_uri,
                    PipelineEvent(
                        scope=EventScope.run()
                        if stage_name is None
                        else EventScope.stage(stage_name),
                        event_type=event_type,
                        event_id=event_id,
                        timestamp=revision.created_at,
                        payload=dict(payload or {}),
                    ),
                )
                _project_event(record)
                self._registry.dispatch(record, _ObserverContext(store, record))
        except Exception:
            # Audit/delivery failure is diagnostic, never scientific failure.
            _LOG.exception(
                "native lifecycle event or observer evidence was not retained"
            )

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
            self.emit(
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
            self.emit(
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


def _project_event(record: PipelineEventRecord) -> None:
    from loom.pipeline.stores import LocalRunStore, run_uri_to_path

    try:
        LocalRunStore(run_uri_to_path(record.run_uri).parent).append_event(
            record.run_uri,
            PipelineEvent(
                scope=record.scope,
                event_type=record.event_type,
                timestamp=record.timestamp,
                event_id=record.event_id,
                payload=record.payload,
            ),
        )
    except Exception:
        _LOG.exception(
            "native event local projection failed; authority evidence remains retained"
        )


class _ObserverContext:
    def __init__(self, store: Any, record: PipelineEventRecord) -> None:
        self._store, self.run_uri = store, record.run_uri
        self.event_reference = record.to_event_reference()

    def record_event_sink_failure(self, failure: EventSinkFailureRecord) -> None:
        self._write("append_event_sink_failure", failure)

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None:
        self._write("append_event_observer_link", link)

    def _write(self, method: str, fact: Any) -> None:
        try:
            if fact.event_reference != self.event_reference:
                raise QueueServiceError("observer fact event identity conflicts")
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
        store.list_audit_events(run_uri)

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._store, name)
        if name not in _MUTATIONS:
            return method

        def commit(*args: Any, **kwargs: Any) -> Any:
            with self._observers._lock:
                before = self._store.open_run(self._run_uri)
                result = method(*args, **kwargs)
                after = self._store.open_run(self._run_uri)
                self._observers._prepared.append((self._store, before, after))
                return result

        return commit


class _ObservedRetryAuthority(_ObservedAuthority):
    def resume_failed_admission(self, *args: Any, **kwargs: Any) -> Any:
        return self.__getattr__("resume_failed_admission")(*args, **kwargs)
