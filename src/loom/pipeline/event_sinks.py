"""Import-light event sink contracts and observer fact records."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable

from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp


EVENT_SINK_FAILURE_SCHEMA_VERSION = 1
EVENT_OBSERVER_LINK_SCHEMA_VERSION = 1

_SINK_NAME_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
_REFERENCE_KIND_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


class EventSinkError(ValueError):
    """Raised when event sink contracts or observer facts are invalid."""


class EventSinkRegistryError(EventSinkError):
    """Raised when event sink registry operations are invalid."""


@dataclass(frozen=True, slots=True)
class EventObserverExternalRef:
    """Generic external reference recorded by an observing event sink."""

    kind: str
    identifiers: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _validate_reference_kind(self.kind, "kind"))
        identifiers = _plain_mapping(self.identifiers, "identifiers")
        if not identifiers:
            raise EventSinkError("identifiers must be a non-empty mapping")
        object.__setattr__(
            self,
            "identifiers",
            freeze_plain_data(identifiers, path="identifiers"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "identifiers": thaw_plain_data(self.identifiers, path="identifiers"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "EventObserverExternalRef":
        if isinstance(data, EventObserverExternalRef):
            return data
        mapping = _mapping(data, "EventObserverExternalRef")
        _reject_unknown(
            mapping,
            {"kind", "identifiers"},
            "EventObserverExternalRef",
        )
        return cls(
            kind=_validate_reference_kind(
                _required(mapping, "kind", "EventObserverExternalRef"),
                "kind",
            ),
            identifiers=_plain_mapping(
                _required(mapping, "identifiers", "EventObserverExternalRef"),
                "identifiers",
            ),
        )


@dataclass(frozen=True, slots=True)
class EventSinkFailureRecord:
    """Event-adjacent fact for a failed event sink callback."""

    sink_name: str
    run_uri: str
    event_reference: EventReference
    failed_at: str
    failure_type: str
    failure_message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = EVENT_SINK_FAILURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sink_name", _validate_sink_name(self.sink_name))
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "event_reference",
            EventReference.from_dict(self.event_reference),
        )
        if self.event_reference.run_uri != self.run_uri:
            raise EventSinkError("event_reference.run_uri must match run_uri")
        object.__setattr__(self, "failed_at", _timestamp(self.failed_at, "failed_at"))
        object.__setattr__(
            self,
            "failure_type",
            _non_empty_string(self.failure_type, "failure_type"),
        )
        object.__setattr__(
            self,
            "failure_message",
            _non_empty_string(self.failure_message, "failure_message"),
        )
        object.__setattr__(
            self,
            "detail",
            freeze_plain_data(_plain_mapping(self.detail, "detail"), path="detail"),
        )
        if self.schema_version != EVENT_SINK_FAILURE_SCHEMA_VERSION:
            raise EventSinkError(
                f"unsupported schema_version {self.schema_version!r}, expected "
                f"{EVENT_SINK_FAILURE_SCHEMA_VERSION}"
            )

    @classmethod
    def from_exception(
        cls,
        *,
        sink_name: str,
        event_reference: EventReference,
        exc: BaseException,
        failed_at: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> "EventSinkFailureRecord":
        failure_detail: dict[str, PlainData] = {
            "exception_module": type(exc).__module__,
        }
        if detail:
            failure_detail.update(_plain_mapping(detail, "detail"))
        return cls(
            sink_name=sink_name,
            run_uri=event_reference.run_uri,
            event_reference=event_reference,
            failed_at=failed_at or utc_timestamp(),
            failure_type=type(exc).__name__,
            failure_message=str(exc) or type(exc).__name__,
            detail=failure_detail,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sink_name": self.sink_name,
            "run_uri": self.run_uri,
            "event_reference": self.event_reference.to_dict(),
            "failed_at": self.failed_at,
            "failure_type": self.failure_type,
            "failure_message": self.failure_message,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "EventSinkFailureRecord":
        if isinstance(data, EventSinkFailureRecord):
            return data
        mapping = _mapping(data, "EventSinkFailureRecord")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "sink_name",
                "run_uri",
                "event_reference",
                "failed_at",
                "failure_type",
                "failure_message",
                "detail",
            },
            "EventSinkFailureRecord",
        )
        return cls(
            schema_version=_positive_int(
                _required(mapping, "schema_version", "EventSinkFailureRecord"),
                "schema_version",
            ),
            sink_name=_validate_sink_name(
                _required(mapping, "sink_name", "EventSinkFailureRecord")
            ),
            run_uri=_non_empty_string(
                _required(mapping, "run_uri", "EventSinkFailureRecord"),
                "run_uri",
            ),
            event_reference=EventReference.from_dict(
                _required(mapping, "event_reference", "EventSinkFailureRecord")
            ),
            failed_at=_timestamp(
                _required(mapping, "failed_at", "EventSinkFailureRecord"),
                "failed_at",
            ),
            failure_type=_non_empty_string(
                _required(mapping, "failure_type", "EventSinkFailureRecord"),
                "failure_type",
            ),
            failure_message=_non_empty_string(
                _required(mapping, "failure_message", "EventSinkFailureRecord"),
                "failure_message",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class EventObserverLinkRecord:
    """Event-adjacent fact linking a Loom event to an external observer ref."""

    sink_name: str
    run_uri: str
    event_reference: EventReference
    recorded_at: str
    external_ref: EventObserverExternalRef
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = EVENT_OBSERVER_LINK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sink_name", _validate_sink_name(self.sink_name))
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "event_reference",
            EventReference.from_dict(self.event_reference),
        )
        if self.event_reference.run_uri != self.run_uri:
            raise EventSinkError("event_reference.run_uri must match run_uri")
        object.__setattr__(
            self, "recorded_at", _timestamp(self.recorded_at, "recorded_at")
        )
        object.__setattr__(
            self,
            "external_ref",
            EventObserverExternalRef.from_dict(self.external_ref),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(_plain_mapping(self.metadata, "metadata"), path="metadata"),
        )
        if self.schema_version != EVENT_OBSERVER_LINK_SCHEMA_VERSION:
            raise EventSinkError(
                f"unsupported schema_version {self.schema_version!r}, expected "
                f"{EVENT_OBSERVER_LINK_SCHEMA_VERSION}"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sink_name": self.sink_name,
            "run_uri": self.run_uri,
            "event_reference": self.event_reference.to_dict(),
            "recorded_at": self.recorded_at,
            "external_ref": self.external_ref.to_dict(),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "EventObserverLinkRecord":
        if isinstance(data, EventObserverLinkRecord):
            return data
        mapping = _mapping(data, "EventObserverLinkRecord")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "sink_name",
                "run_uri",
                "event_reference",
                "recorded_at",
                "external_ref",
                "metadata",
            },
            "EventObserverLinkRecord",
        )
        return cls(
            schema_version=_positive_int(
                _required(mapping, "schema_version", "EventObserverLinkRecord"),
                "schema_version",
            ),
            sink_name=_validate_sink_name(
                _required(mapping, "sink_name", "EventObserverLinkRecord")
            ),
            run_uri=_non_empty_string(
                _required(mapping, "run_uri", "EventObserverLinkRecord"),
                "run_uri",
            ),
            event_reference=EventReference.from_dict(
                _required(mapping, "event_reference", "EventObserverLinkRecord")
            ),
            recorded_at=_timestamp(
                _required(mapping, "recorded_at", "EventObserverLinkRecord"),
                "recorded_at",
            ),
            external_ref=EventObserverExternalRef.from_dict(
                _required(mapping, "external_ref", "EventObserverLinkRecord")
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@runtime_checkable
class EventObserverLinkRecorder(Protocol):
    """Narrow context surface for recording observer links."""

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None: ...


@runtime_checkable
class EventSinkFailureRecorder(Protocol):
    """Narrow context surface for recording callback failures."""

    def record_event_sink_failure(self, failure: EventSinkFailureRecord) -> None: ...


@runtime_checkable
class EventSinkContext(EventObserverLinkRecorder, Protocol):
    """Observe-only context passed to event sinks."""

    @property
    def run_uri(self) -> str: ...

    @property
    def event_reference(self) -> EventReference: ...


class EventSink(Protocol):
    """Callable observer of a runtime event or event identity."""

    def __call__(
        self,
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class EventSinkCallbackResult:
    """Result for one sink callback in a registry dispatch."""

    sink_name: str
    succeeded: bool
    failure: EventSinkFailureRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sink_name", _validate_sink_name(self.sink_name))
        if not isinstance(self.succeeded, bool):
            raise EventSinkError("succeeded must be a bool")
        if self.succeeded and self.failure is not None:
            raise EventSinkError("successful callback result must not include failure")
        if not self.succeeded and not isinstance(self.failure, EventSinkFailureRecord):
            raise EventSinkError("failed callback result requires failure record")


@dataclass(frozen=True, slots=True)
class EventSinkDispatchResult:
    """Aggregate result for dispatching one event to a registry."""

    event_reference: EventReference
    sink_results: tuple[EventSinkCallbackResult, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_reference", EventReference.from_dict(self.event_reference)
        )
        object.__setattr__(
            self,
            "sink_results",
            _tuple_of_results(self.sink_results),
        )

    @property
    def failures(self) -> tuple[EventSinkFailureRecord, ...]:
        return tuple(
            result.failure
            for result in self.sink_results
            if result.failure is not None
        )

    @property
    def succeeded(self) -> bool:
        return not self.failures


class EventSinkRegistry:
    """Instance-local registry for explicitly supplied event sinks."""

    def __init__(self) -> None:
        self._sinks: dict[str, EventSink] = {}

    def register(self, name: str, sink: EventSink) -> None:
        sink_name = _validate_sink_name(name)
        if sink_name in self._sinks:
            raise EventSinkRegistryError(f"event sink {sink_name!r} is already registered")
        if not callable(sink):
            raise EventSinkRegistryError("event sink must be callable")
        self._sinks[sink_name] = sink

    def names(self) -> tuple[str, ...]:
        return tuple(self._sinks)

    def items(self) -> tuple[tuple[str, EventSink], ...]:
        return tuple(self._sinks.items())

    def dispatch(
        self,
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> EventSinkDispatchResult:
        event_reference = _event_reference(event)
        results: list[EventSinkCallbackResult] = []
        for sink_name, sink in self._sinks.items():
            try:
                sink(event, context)
            except Exception as exc:  # noqa: BLE001 - sink failures are captured.
                failure = EventSinkFailureRecord.from_exception(
                    sink_name=sink_name,
                    event_reference=event_reference,
                    exc=exc,
                )
                recorder = getattr(context, "record_event_sink_failure", None)
                if callable(recorder):
                    try:
                        recorder(failure)
                    except Exception:  # noqa: BLE001 - dispatch stays best-effort.
                        pass
                results.append(
                    EventSinkCallbackResult(
                        sink_name=sink_name,
                        succeeded=False,
                        failure=failure,
                    )
                )
            else:
                results.append(
                    EventSinkCallbackResult(sink_name=sink_name, succeeded=True)
                )
        return EventSinkDispatchResult(
            event_reference=event_reference,
            sink_results=tuple(results),
        )

    def __len__(self) -> int:
        return len(self._sinks)

    def __iter__(self) -> Iterable[tuple[str, EventSink]]:
        return iter(self.items())


def _event_reference(event: PipelineEventRecord | EventReference) -> EventReference:
    if isinstance(event, PipelineEventRecord):
        return event.to_event_reference()
    return EventReference.from_dict(event)


def _validate_sink_name(value: object) -> str:
    return _validate_identifier(value, "sink_name", _SINK_NAME_RE)


def _validate_reference_kind(value: object, field: str) -> str:
    return _validate_identifier(value, field, _REFERENCE_KIND_RE)


def _validate_identifier(value: object, field: str, pattern: re.Pattern[str]) -> str:
    text = _non_empty_string(value, field)
    if not pattern.fullmatch(text):
        raise EventSinkError(
            f"{field} must use lowercase dotted identifier segments"
        )
    return text


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EventSinkError(f"{field} must be a non-empty string")
    return value


def _timestamp(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise EventSinkError(f"{field} must be a valid loom timestamp") from exc
    return text


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EventSinkError(f"{field} must be a positive integer")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EventSinkError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise EventSinkError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise EventSinkError(f"{field} must be plain-data-compatible: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise EventSinkError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _required(mapping: Mapping[str, object], field: str, owner: str) -> object:
    if field not in mapping:
        raise EventSinkError(f"{owner}.{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], owner: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise EventSinkError(
            f"{owner} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _tuple_of_results(
    values: tuple[EventSinkCallbackResult, ...] | list[EventSinkCallbackResult],
) -> tuple[EventSinkCallbackResult, ...]:
    if not isinstance(values, (tuple, list)):
        raise EventSinkError("sink_results must be a sequence")
    if any(not isinstance(value, EventSinkCallbackResult) for value in values):
        raise EventSinkError("sink_results must contain EventSinkCallbackResult values")
    return tuple(values)


__all__ = [
    "EVENT_SINK_FAILURE_SCHEMA_VERSION",
    "EVENT_OBSERVER_LINK_SCHEMA_VERSION",
    "EventSinkError",
    "EventSinkRegistryError",
    "EventObserverExternalRef",
    "EventSinkFailureRecord",
    "EventObserverLinkRecord",
    "EventObserverLinkRecorder",
    "EventSinkFailureRecorder",
    "EventSinkContext",
    "EventSink",
    "EventSinkCallbackResult",
    "EventSinkDispatchResult",
    "EventSinkRegistry",
]
