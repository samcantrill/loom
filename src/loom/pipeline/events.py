"""Pipeline event model foundations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError
from loom.timestamps import parse_timestamp

EVENT_SCHEMA_VERSION = 1

_EVENT_TYPE_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


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
            freeze_plain_data(_plain_mapping(self.payload, field="payload"), path="payload"),
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


@dataclass(frozen=True, slots=True)
class PipelineEventRecord:
    run_id: str
    sequence: int
    timestamp: str
    scope: EventScope
    event_type: str
    payload: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        object.__setattr__(
            self, "run_id", _require_non_empty_string(self.run_id, field="run_id")
        )
        object.__setattr__(
            self,
            "sequence",
            _positive_int(self.sequence, field="sequence"),
        )
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp, field="timestamp"))
        if not isinstance(self.scope, EventScope):
            raise PipelineEventError("PipelineEventRecord.scope must be an EventScope")
        object.__setattr__(self, "event_type", _validate_event_type(self.event_type))
        object.__setattr__(
            self,
            "payload",
            freeze_plain_data(_plain_mapping(self.payload, field="payload"), path="payload"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "scope": self.scope.to_dict(),
            "event_type": self.event_type,
            "payload": thaw_plain_data(self.payload, path="payload"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PipelineEventRecord":
        try:
            mapping = load_versioned_document(
                data,
                current_version=EVENT_SCHEMA_VERSION,
                required={
                    "run_id",
                    "sequence",
                    "timestamp",
                    "scope",
                    "event_type",
                    "payload",
                },
                optional=(),
                path="PipelineEventRecord",
            )
        except SchemaVersionError as exc:
            raise PipelineEventError(f"PipelineEventRecord.from_dict: {exc}") from exc
        return cls(
            schema_version=_require_schema_version(mapping["schema_version"]),
            run_id=_require_non_empty_string(mapping["run_id"], field="run_id"),
            sequence=_positive_int(mapping["sequence"], field="sequence"),
            timestamp=_timestamp(mapping["timestamp"], field="timestamp"),
            scope=EventScope.from_dict(mapping["scope"]),
            event_type=_validate_event_type(mapping["event_type"]),
            payload=_plain_mapping(mapping["payload"], field="payload"),
        )


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


def _require_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PipelineEventError("schema_version must be a positive integer")
    if value != EVENT_SCHEMA_VERSION:
        raise PipelineEventError(
            f"unsupported schema_version {value!r}, expected {EVENT_SCHEMA_VERSION}"
        )
    return value


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
        raise PipelineEventError(f"{field} must be a valid loom timestamp: {exc}") from exc
    return text


def _optional_timestamp(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, field=field)


def _validate_event_type(value: object) -> str:
    text = _require_non_empty_string(value, field="event_type")
    if _EVENT_TYPE_RE.fullmatch(text) is None:
        raise PipelineEventError(
            "event_type must be a lower-case dot-separated identifier"
        )
    return text


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "PipelineEventError",
    "EventScopeKind",
    "EventScope",
    "PipelineEvent",
    "PipelineEventRecord",
]
