"""Pipeline event model foundations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp

EVENT_SCHEMA_VERSION = 2
LEGACY_EVENT_SCHEMA_VERSION = 1

_IDENTIFIER_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


class PipelineEventError(ValueError):
    """Raised when pipeline event records are malformed."""


class EventScopeKind(StrEnum):
    RUN = "RUN"
    STAGE = "STAGE"


@dataclass(frozen=True, slots=True)
class EventScope:
    kind: EventScopeKind
    stage_name: str | None = None

    def __post_init__(self) -> None:
        kind = _coerce_scope_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is EventScopeKind.RUN:
            if self.stage_name is not None:
                raise PipelineEventError("RUN event scope must not include stage_name")
        else:
            object.__setattr__(
                self,
                "stage_name",
                _require_non_empty_string(self.stage_name, field="stage_name"),
            )

    @classmethod
    def run(cls) -> "EventScope":
        return cls(kind=EventScopeKind.RUN)

    @classmethod
    def stage(cls, stage_name: str) -> "EventScope":
        return cls(kind=EventScopeKind.STAGE, stage_name=stage_name)

    def to_dict(self) -> dict[str, PlainData]:
        return {"kind": self.kind.value, "stage_name": self.stage_name}

    @classmethod
    def from_dict(cls, data: object) -> "EventScope":
        mapping = _require_mapping(data, field="EventScope")
        _reject_unknown(mapping, allowed={"kind", "stage_name"}, field="EventScope")
        if "kind" not in mapping:
            raise PipelineEventError("EventScope.kind is required")
        return cls(
            kind=_coerce_scope_kind(mapping["kind"]),
            stage_name=_optional_string(mapping.get("stage_name"), field="stage_name"),
        )


@dataclass(frozen=True, slots=True)
class EventResourceRef:
    """Plain-data reference to a Loom runtime resource mentioned by an event."""

    kind: str
    identifiers: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _validate_identifier(self.kind, field="kind"))
        identifiers = _plain_mapping(self.identifiers, field="identifiers")
        if not identifiers:
            raise PipelineEventError("identifiers must be a non-empty mapping")
        object.__setattr__(
            self,
            "identifiers",
            freeze_plain_data(identifiers, path="identifiers"),
        )

    @classmethod
    def run(cls, run_uri: str) -> "EventResourceRef":
        return cls(
            kind="run",
            identifiers={
                "run_uri": _require_non_empty_string(run_uri, field="run_uri")
            },
        )

    @classmethod
    def stage(cls, run_uri: str, stage_name: str) -> "EventResourceRef":
        return cls(
            kind="stage",
            identifiers={
                "run_uri": _require_non_empty_string(run_uri, field="run_uri"),
                "stage_name": _require_non_empty_string(stage_name, field="stage_name"),
            },
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "identifiers": thaw_plain_data(self.identifiers, path="identifiers"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "EventResourceRef":
        if isinstance(data, EventResourceRef):
            return data
        mapping = _require_mapping(data, field="EventResourceRef")
        _reject_unknown(
            mapping, allowed={"kind", "identifiers"}, field="EventResourceRef"
        )
        return cls(
            kind=_require_non_empty_string(
                _required(mapping, "kind", field="EventResourceRef"), field="kind"
            ),
            identifiers=_plain_mapping(
                _required(mapping, "identifiers", field="EventResourceRef"),
                field="identifiers",
            ),
        )


@dataclass(frozen=True, slots=True)
class EventReference:
    """Plain-data reference to a durable or non-durable runtime event."""

    event_id: str
    run_uri: str
    event_type: str
    occurred_at: str
    durability: str
    sequence: int | None = None
    dispatch_sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _require_non_empty_string(self.event_id, field="event_id")
        )
        object.__setattr__(
            self, "run_uri", _require_non_empty_string(self.run_uri, field="run_uri")
        )
        object.__setattr__(self, "event_type", _validate_event_type(self.event_type))
        object.__setattr__(
            self,
            "occurred_at",
            _timestamp(self.occurred_at, field="occurred_at"),
        )
        durability = _require_non_empty_string(self.durability, field="durability")
        if durability == "durable":
            object.__setattr__(
                self,
                "sequence",
                _positive_int(self.sequence, field="sequence"),
            )
            if self.dispatch_sequence is not None:
                raise PipelineEventError(
                    "durable EventReference must not include dispatch_sequence"
                )
        elif durability == "non_durable":
            object.__setattr__(
                self,
                "dispatch_sequence",
                _positive_int(self.dispatch_sequence, field="dispatch_sequence"),
            )
            if self.sequence is not None:
                raise PipelineEventError(
                    "non_durable EventReference must not include sequence"
                )
        else:
            raise PipelineEventError("durability must be 'durable' or 'non_durable'")
        object.__setattr__(self, "durability", durability)

    def to_dict(self) -> dict[str, PlainData]:
        payload: dict[str, PlainData] = {
            "event_id": self.event_id,
            "run_uri": self.run_uri,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "durability": self.durability,
        }
        if self.durability == "durable":
            payload["sequence"] = self.sequence
        else:
            payload["dispatch_sequence"] = self.dispatch_sequence
        return payload

    @classmethod
    def from_dict(cls, data: object) -> "EventReference":
        if isinstance(data, EventReference):
            return data
        mapping = _require_mapping(data, field="EventReference")
        _reject_unknown(
            mapping,
            allowed={
                "event_id",
                "run_uri",
                "event_type",
                "occurred_at",
                "durability",
                "sequence",
                "dispatch_sequence",
            },
            field="EventReference",
        )
        return cls(
            event_id=_require_non_empty_string(
                _required(mapping, "event_id", field="EventReference"),
                field="event_id",
            ),
            run_uri=_require_non_empty_string(
                _required(mapping, "run_uri", field="EventReference"),
                field="run_uri",
            ),
            event_type=_validate_event_type(
                _required(mapping, "event_type", field="EventReference")
            ),
            occurred_at=_timestamp(
                _required(mapping, "occurred_at", field="EventReference"),
                field="occurred_at",
            ),
            durability=_require_non_empty_string(
                _required(mapping, "durability", field="EventReference"),
                field="durability",
            ),
            sequence=cast(int | None, mapping.get("sequence")),
            dispatch_sequence=cast(int | None, mapping.get("dispatch_sequence")),
        )


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    scope: EventScope
    event_type: str
    payload: Mapping[str, PlainData] = field(default_factory=dict)
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, EventScope):
            raise PipelineEventError("PipelineEvent.scope must be an EventScope")
        object.__setattr__(self, "event_type", _validate_event_type(self.event_type))
        object.__setattr__(
            self,
            "payload",
            freeze_plain_data(
                _plain_mapping(self.payload, field="payload"), path="payload"
            ),
        )
        object.__setattr__(
            self,
            "timestamp",
            _optional_timestamp(self.timestamp, field="timestamp"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "scope": self.scope.to_dict(),
            "event_type": self.event_type,
            "payload": thaw_plain_data(self.payload, path="payload"),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True, init=False)
class PipelineEventRecord:
    """Canonical durable pipeline event record.

    New records serialize as schema-version 2. Schema-version 1 records remain
    readable through explicit projection helpers for existing local logs and
    offline evidence manifests.
    """

    run_uri: str
    sequence: int
    occurred_at: str
    event_type: str
    primary_resource: EventResourceRef
    related_resources: tuple[EventResourceRef, ...]
    payload: Mapping[str, PlainData]
    event_id: str
    causal_predecessor: EventResourceRef | EventReference | None
    schema_version: int

    def __init__(
        self,
        *,
        run_uri: str,
        sequence: int,
        event_type: str,
        payload: Mapping[str, PlainData] | None = None,
        occurred_at: str | None = None,
        timestamp: str | None = None,
        primary_resource: EventResourceRef | Mapping[str, object] | None = None,
        related_resources: (
            tuple[EventResourceRef | Mapping[str, object], ...]
            | list[EventResourceRef | Mapping[str, object]]
            | None
        ) = None,
        causal_predecessor: (
            EventResourceRef | EventReference | Mapping[str, object] | None
        ) = None,
        event_id: str | None = None,
        scope: EventScope | None = None,
        schema_version: int = EVENT_SCHEMA_VERSION,
    ) -> None:
        if schema_version != EVENT_SCHEMA_VERSION:
            raise PipelineEventError(
                f"unsupported schema_version {schema_version!r}, "
                f"expected {EVENT_SCHEMA_VERSION}"
            )
        run_uri_text = _require_non_empty_string(run_uri, field="run_uri")
        sequence_int = _positive_int(sequence, field="sequence")
        timestamp_text = _resolve_occurred_at(
            occurred_at=occurred_at, timestamp=timestamp
        )
        if primary_resource is None:
            if scope is None:
                primary = EventResourceRef.run(run_uri_text)
                related: tuple[EventResourceRef, ...] = ()
            else:
                primary, related = _resources_from_scope(
                    run_uri=run_uri_text, scope=scope
                )
        else:
            primary = EventResourceRef.from_dict(primary_resource)
            related = ()
        if related_resources is not None:
            related = tuple(
                EventResourceRef.from_dict(resource) for resource in related_resources
            )
        object.__setattr__(self, "schema_version", EVENT_SCHEMA_VERSION)
        object.__setattr__(self, "run_uri", run_uri_text)
        object.__setattr__(self, "sequence", sequence_int)
        object.__setattr__(self, "occurred_at", timestamp_text)
        object.__setattr__(self, "event_type", _validate_event_type(event_type))
        object.__setattr__(self, "primary_resource", primary)
        object.__setattr__(self, "related_resources", related)
        object.__setattr__(
            self,
            "payload",
            freeze_plain_data(
                _plain_mapping({} if payload is None else payload, field="payload"),
                path="payload",
            ),
        )
        object.__setattr__(
            self,
            "event_id",
            _require_non_empty_string(
                compatibility_event_id(run_uri_text, sequence_int)
                if event_id is None
                else event_id,
                field="event_id",
            ),
        )
        object.__setattr__(
            self,
            "causal_predecessor",
            _optional_causal_predecessor(causal_predecessor),
        )

    @property
    def timestamp(self) -> str:
        """Compatibility alias for schema-v1 callers."""

        return self.occurred_at

    @property
    def scope(self) -> EventScope:
        """Compatibility projection for run and stage event records."""

        return _scope_from_resource(self.primary_resource)

    def to_dict(self) -> dict[str, PlainData]:
        payload: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_uri": self.run_uri,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "event_type": self.event_type,
            "primary_resource": self.primary_resource.to_dict(),
            "related_resources": [
                resource.to_dict() for resource in self.related_resources
            ],
            "payload": thaw_plain_data(self.payload, path="payload"),
        }
        if self.causal_predecessor is not None:
            payload["causal_predecessor"] = self.causal_predecessor.to_dict()
        return payload

    def to_schema_v1_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": LEGACY_EVENT_SCHEMA_VERSION,
            "run_uri": self.run_uri,
            "sequence": self.sequence,
            "timestamp": self.occurred_at,
            "scope": self.scope.to_dict(),
            "event_type": self.event_type,
            "payload": thaw_plain_data(self.payload, path="payload"),
        }

    def to_event_reference(self) -> EventReference:
        return EventReference(
            event_id=self.event_id,
            run_uri=self.run_uri,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            durability="durable",
            sequence=self.sequence,
        )

    @classmethod
    def from_dict(cls, data: object) -> "PipelineEventRecord":
        mapping = _require_mapping(data, field="PipelineEventRecord")
        schema_version = _positive_int(
            _required(mapping, "schema_version", field="PipelineEventRecord"),
            field="schema_version",
        )
        if schema_version == LEGACY_EVENT_SCHEMA_VERSION:
            return cls.from_schema_v1_dict(mapping)
        if schema_version != EVENT_SCHEMA_VERSION:
            raise PipelineEventError(
                "PipelineEventRecord.from_dict: unsupported schema_version "
                f"{schema_version!r}, expected {EVENT_SCHEMA_VERSION}"
            )
        _reject_unknown(
            mapping,
            allowed={
                "schema_version",
                "event_id",
                "run_uri",
                "sequence",
                "occurred_at",
                "event_type",
                "primary_resource",
                "related_resources",
                "payload",
                "causal_predecessor",
            },
            field="PipelineEventRecord",
        )
        return cls(
            run_uri=_require_non_empty_string(
                _required(mapping, "run_uri", field="PipelineEventRecord"),
                field="run_uri",
            ),
            sequence=_positive_int(
                _required(mapping, "sequence", field="PipelineEventRecord"),
                field="sequence",
            ),
            occurred_at=_timestamp(
                _required(mapping, "occurred_at", field="PipelineEventRecord"),
                field="occurred_at",
            ),
            event_type=_validate_event_type(
                _required(mapping, "event_type", field="PipelineEventRecord")
            ),
            primary_resource=EventResourceRef.from_dict(
                _required(mapping, "primary_resource", field="PipelineEventRecord")
            ),
            related_resources=_resource_refs_from_sequence(
                _required(mapping, "related_resources", field="PipelineEventRecord")
            ),
            payload=_plain_mapping(
                _required(mapping, "payload", field="PipelineEventRecord"),
                field="payload",
            ),
            causal_predecessor=_optional_causal_predecessor(
                cast(
                    EventResourceRef | EventReference | Mapping[str, object] | None,
                    mapping.get("causal_predecessor"),
                )
            ),
            event_id=_require_non_empty_string(
                _required(mapping, "event_id", field="PipelineEventRecord"),
                field="event_id",
            ),
        )

    @classmethod
    def from_schema_v1_dict(cls, data: object) -> "PipelineEventRecord":
        mapping = _require_mapping(data, field="PipelineEventRecord.schema_v1")
        _reject_unknown(
            mapping,
            allowed={
                "schema_version",
                "run_uri",
                "sequence",
                "timestamp",
                "scope",
                "event_type",
                "payload",
            },
            field="PipelineEventRecord.schema_v1",
        )
        schema_version = _positive_int(
            _required(mapping, "schema_version", field="PipelineEventRecord"),
            field="schema_version",
        )
        if schema_version != LEGACY_EVENT_SCHEMA_VERSION:
            raise PipelineEventError(
                "PipelineEventRecord.from_schema_v1_dict: unsupported "
                f"schema_version {schema_version!r}, expected "
                f"{LEGACY_EVENT_SCHEMA_VERSION}"
            )
        run_uri = _require_non_empty_string(
            _required(mapping, "run_uri", field="PipelineEventRecord"),
            field="run_uri",
        )
        sequence = _positive_int(
            _required(mapping, "sequence", field="PipelineEventRecord"),
            field="sequence",
        )
        primary, related = _resources_from_scope(
            run_uri=run_uri,
            scope=EventScope.from_dict(
                _required(mapping, "scope", field="PipelineEventRecord")
            ),
        )
        return cls(
            run_uri=run_uri,
            sequence=sequence,
            occurred_at=_timestamp(
                _required(mapping, "timestamp", field="PipelineEventRecord"),
                field="timestamp",
            ),
            event_type=_validate_event_type(
                _required(mapping, "event_type", field="PipelineEventRecord")
            ),
            primary_resource=primary,
            related_resources=related,
            payload=_plain_mapping(
                _required(mapping, "payload", field="PipelineEventRecord"),
                field="payload",
            ),
            event_id=compatibility_event_id(run_uri, sequence),
        )


def compatibility_event_id(run_uri: str, sequence: int) -> str:
    """Return the deterministic event id used for projected schema-v1 records."""

    run_uri_text = _require_non_empty_string(run_uri, field="run_uri")
    sequence_int = _positive_int(sequence, field="sequence")
    digest = hashlib.sha256(
        f"{run_uri_text}\0{sequence_int}".encode("utf-8")
    ).hexdigest()[:32]
    return f"evt_v1_{digest}"


def _coerce_scope_kind(value: object) -> EventScopeKind:
    if isinstance(value, EventScopeKind):
        return value
    if not isinstance(value, str):
        raise PipelineEventError("EventScope.kind must be a string")
    try:
        return EventScopeKind(value)
    except ValueError as exc:
        raise PipelineEventError(f"invalid EventScope.kind {value!r}") from exc


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PipelineEventError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise PipelineEventError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, *, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise PipelineEventError(
            f"{field} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise PipelineEventError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _reject_unknown(
    mapping: Mapping[str, object], *, allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise PipelineEventError(f"{field} contains unknown field(s): {fields}")


def _required(mapping: Mapping[str, object], key: str, *, field: str) -> object:
    if key not in mapping:
        raise PipelineEventError(f"{field}.{key} is required")
    return mapping[key]


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PipelineEventError(f"{field} must be a positive integer")
    if value <= 0:
        raise PipelineEventError(f"{field} must be a positive integer")
    return value


def _require_non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PipelineEventError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field=field)


def _timestamp(value: object, *, field: str) -> str:
    text = _require_non_empty_string(value, field=field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise PipelineEventError(
            f"{field} must be a valid loom timestamp: {exc}"
        ) from exc
    return text


def _optional_timestamp(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, field=field)


def _resolve_occurred_at(*, occurred_at: str | None, timestamp: str | None) -> str:
    if occurred_at is not None and timestamp is not None and occurred_at != timestamp:
        raise PipelineEventError("occurred_at and timestamp must match when both set")
    return _timestamp(
        occurred_at if occurred_at is not None else timestamp,
        field="occurred_at",
    )


def _validate_identifier(value: object, *, field: str) -> str:
    text = _require_non_empty_string(value, field=field)
    if _IDENTIFIER_RE.fullmatch(text) is None:
        raise PipelineEventError(
            f"{field} must be a lower-case dot-separated identifier"
        )
    return text


def _validate_event_type(value: object) -> str:
    return _validate_identifier(value, field="event_type")


def _resources_from_scope(
    *, run_uri: str, scope: EventScope
) -> tuple[EventResourceRef, tuple[EventResourceRef, ...]]:
    if not isinstance(scope, EventScope):
        raise PipelineEventError("scope must be an EventScope")
    if scope.kind is EventScopeKind.RUN:
        return EventResourceRef.run(run_uri), ()
    if scope.stage_name is None:
        raise PipelineEventError("stage event scope must include stage_name")
    return EventResourceRef.stage(run_uri, scope.stage_name), (
        EventResourceRef.run(run_uri),
    )


def _scope_from_resource(resource: EventResourceRef) -> EventScope:
    identifiers = _plain_mapping(resource.identifiers, field="identifiers")
    if resource.kind == "run":
        _require_matching_run_uri(identifiers)
        return EventScope.run()
    if resource.kind == "stage":
        _require_matching_run_uri(identifiers)
        return EventScope.stage(
            _require_non_empty_string(identifiers.get("stage_name"), field="stage_name")
        )
    raise PipelineEventError(
        "scope compatibility alias is only available for run and stage resources"
    )


def _require_matching_run_uri(identifiers: Mapping[str, PlainData]) -> None:
    _require_non_empty_string(identifiers.get("run_uri"), field="run_uri")


def _resource_refs_from_sequence(
    value: object,
) -> tuple[EventResourceRef, ...]:
    if not isinstance(value, (list, tuple)):
        raise PipelineEventError("related_resources must be a list")
    return tuple(EventResourceRef.from_dict(item) for item in value)


def _optional_causal_predecessor(
    value: EventResourceRef | EventReference | Mapping[str, object] | None,
) -> EventResourceRef | EventReference | None:
    if value is None:
        return None
    if isinstance(value, (EventResourceRef, EventReference)):
        return value
    mapping = _require_mapping(value, field="causal_predecessor")
    looks_like_resource = {"kind", "identifiers"}.issubset(mapping)
    looks_like_reference = {"event_id", "durability"}.issubset(mapping)
    if looks_like_resource and looks_like_reference:
        raise PipelineEventError("causal_predecessor mapping is ambiguous")
    if looks_like_resource:
        return EventResourceRef.from_dict(mapping)
    if looks_like_reference:
        return EventReference.from_dict(mapping)
    raise PipelineEventError(
        "causal_predecessor must be an EventResourceRef or EventReference"
    )


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "LEGACY_EVENT_SCHEMA_VERSION",
    "PipelineEventError",
    "EventScopeKind",
    "EventScope",
    "EventResourceRef",
    "EventReference",
    "PipelineEvent",
    "PipelineEventRecord",
    "compatibility_event_id",
]
