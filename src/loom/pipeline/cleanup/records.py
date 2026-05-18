"""Plain-data cleanup records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar, cast

from loom.pipeline.cleanup.errors import CleanupRecordError
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp

CLEANUP_RECORD_SCHEMA_VERSION = 1

_E = TypeVar("_E", bound=StrEnum)


class CleanupTargetKind(StrEnum):
    """Kinds of cleanup targets supported by public cleanup records."""

    LOCAL_PATH = "local_path"
    REMOTE_REF = "remote_ref"
    EXTERNAL_REF = "external_ref"


class CleanupReportEntryStatus(StrEnum):
    """Dry-run report entry status values."""

    SELECTED = "selected"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class CleanupResultOutcome(StrEnum):
    """Mutating cleanup result outcome values."""

    DELETED = "deleted"
    SKIPPED = "skipped"
    REJECTED = "rejected"
    FAILED = "failed"


class CleanupDeleteMode(StrEnum):
    """Structured delete modes for explicit cleanup intent."""

    DELETE_SELECTED_TARGETS = "delete_selected_targets"


@dataclass(frozen=True, slots=True)
class CleanupTargetRef:
    """Provider-neutral reference to one cleanup target."""

    kind: CleanupTargetKind
    uri: str
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    target_id: str | None = None
    ownership_key: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "kind", _coerce_enum(self.kind, CleanupTargetKind, "kind")
        )
        object.__setattr__(self, "uri", _non_empty_string(self.uri, "uri"))
        object.__setattr__(
            self, "target_id", _optional_string(self.target_id, "target_id")
        )
        object.__setattr__(
            self,
            "ownership_key",
            _optional_string(self.ownership_key, "ownership_key"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "uri": self.uri,
            "target_id": self.target_id,
            "ownership_key": self.ownership_key,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupTargetRef":
        mapping = _mapping(data, "CleanupTargetRef")
        _reject_unknown(
            mapping,
            {"schema_version", "kind", "uri", "target_id", "ownership_key", "metadata"},
            "CleanupTargetRef",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            kind=_coerce_enum(_required(mapping, "kind"), CleanupTargetKind, "kind"),
            uri=_non_empty_string(_required(mapping, "uri"), "uri"),
            target_id=_optional_string(mapping.get("target_id"), "target_id"),
            ownership_key=_optional_string(
                mapping.get("ownership_key"), "ownership_key"
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CleanupManagedRoot:
    """Trusted local root under which cleanup targets may be considered."""

    root_id: str
    uri: str
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    ownership_key: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "root_id", _non_empty_string(self.root_id, "root_id"))
        object.__setattr__(self, "uri", _non_empty_string(self.uri, "uri"))
        object.__setattr__(
            self,
            "ownership_key",
            _optional_string(self.ownership_key, "ownership_key"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "root_id": self.root_id,
            "uri": self.uri,
            "ownership_key": self.ownership_key,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupManagedRoot":
        mapping = _mapping(data, "CleanupManagedRoot")
        _reject_unknown(
            mapping,
            {"schema_version", "root_id", "uri", "ownership_key", "metadata"},
            "CleanupManagedRoot",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            root_id=_non_empty_string(_required(mapping, "root_id"), "root_id"),
            uri=_non_empty_string(_required(mapping, "uri"), "uri"),
            ownership_key=_optional_string(
                mapping.get("ownership_key"), "ownership_key"
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CleanupReportEntry:
    """One candidate entry in a cleanup dry-run report."""

    candidate_id: str
    target: CleanupTargetRef
    status: CleanupReportEntryStatus
    reason_code: str
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    message: str | None = None
    selector_explanations: tuple[Mapping[str, PlainData], ...] = ()
    safety_decision: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "candidate_id", _non_empty_string(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "target", _target_ref(self.target, "target"))
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, CleanupReportEntryStatus, "status"),
        )
        object.__setattr__(
            self, "reason_code", _non_empty_string(self.reason_code, "reason_code")
        )
        object.__setattr__(self, "message", _optional_string(self.message, "message"))
        object.__setattr__(
            self,
            "selector_explanations",
            _tuple_plain_mappings(
                self.selector_explanations, "selector_explanations"
            ),
        )
        object.__setattr__(
            self,
            "safety_decision",
            _plain_mapping(self.safety_decision, "safety_decision"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "target": self.target.to_dict(),
            "status": self.status.value,
            "reason_code": self.reason_code,
            "message": self.message,
            "selector_explanations": [
                thaw_plain_data(explanation, path="selector_explanations[]")
                for explanation in self.selector_explanations
            ],
            "safety_decision": thaw_plain_data(
                self.safety_decision, path="safety_decision"
            ),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupReportEntry":
        mapping = _mapping(data, "CleanupReportEntry")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "candidate_id",
                "target",
                "status",
                "reason_code",
                "message",
                "selector_explanations",
                "safety_decision",
                "metadata",
            },
            "CleanupReportEntry",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            candidate_id=_non_empty_string(
                _required(mapping, "candidate_id"), "candidate_id"
            ),
            target=CleanupTargetRef.from_dict(_required(mapping, "target")),
            status=_coerce_enum(
                _required(mapping, "status"), CleanupReportEntryStatus, "status"
            ),
            reason_code=_non_empty_string(
                _required(mapping, "reason_code"), "reason_code"
            ),
            message=_optional_string(mapping.get("message"), "message"),
            selector_explanations=_tuple_plain_mappings(
                _sequence(mapping.get("selector_explanations", ())),
                "selector_explanations",
            ),
            safety_decision=_plain_mapping(
                mapping.get("safety_decision", {}), "safety_decision"
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Side-effect-free cleanup report record."""

    report_id: str
    run_uri: str
    created_at: str
    entries: tuple[CleanupReportEntry, ...] = ()
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    dry_run: bool = True
    selector: Mapping[str, PlainData] = field(default_factory=dict)
    summary: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "report_id", _non_empty_string(self.report_id, "report_id"))
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "entries", _tuple_of_entries(self.entries))
        if not isinstance(self.dry_run, bool):
            raise CleanupRecordError("dry_run must be a bool")
        object.__setattr__(self, "selector", _plain_mapping(self.selector, "selector"))
        object.__setattr__(self, "summary", _plain_mapping(self.summary, "summary"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "run_uri": self.run_uri,
            "created_at": self.created_at,
            "dry_run": self.dry_run,
            "selector": thaw_plain_data(self.selector, path="selector"),
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": thaw_plain_data(self.summary, path="summary"),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupReport":
        mapping = _mapping(data, "CleanupReport")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "report_id",
                "run_uri",
                "created_at",
                "dry_run",
                "selector",
                "entries",
                "summary",
                "metadata",
            },
            "CleanupReport",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            report_id=_non_empty_string(_required(mapping, "report_id"), "report_id"),
            run_uri=_non_empty_string(_required(mapping, "run_uri"), "run_uri"),
            created_at=_timestamp(_required(mapping, "created_at"), "created_at"),
            dry_run=_bool(mapping.get("dry_run", True), "dry_run"),
            selector=_plain_mapping(mapping.get("selector", {}), "selector"),
            entries=tuple(
                CleanupReportEntry.from_dict(entry)
                for entry in _sequence(mapping.get("entries", ()))
            ),
            summary=_plain_mapping(mapping.get("summary", {}), "summary"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CleanupDeleteIntent:
    """Explicit structured intent for destructive cleanup operations."""

    intent_id: str
    requested_by: str
    requested_at: str
    reason: str
    mode: CleanupDeleteMode = CleanupDeleteMode.DELETE_SELECTED_TARGETS
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    confirmed: bool = True
    candidate_ids: tuple[str, ...] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "intent_id", _non_empty_string(self.intent_id, "intent_id"))
        object.__setattr__(
            self, "requested_by", _non_empty_string(self.requested_by, "requested_by")
        )
        object.__setattr__(
            self, "requested_at", _timestamp(self.requested_at, "requested_at")
        )
        object.__setattr__(self, "reason", _non_empty_string(self.reason, "reason"))
        object.__setattr__(self, "mode", _coerce_enum(self.mode, CleanupDeleteMode, "mode"))
        if self.confirmed is not True:
            raise CleanupRecordError("confirmed cleanup delete intent must be true")
        object.__setattr__(self, "candidate_ids", _string_tuple(self.candidate_ids, "candidate_ids"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "reason": self.reason,
            "mode": self.mode.value,
            "confirmed": self.confirmed,
            "candidate_ids": list(self.candidate_ids),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupDeleteIntent":
        mapping = _mapping(data, "CleanupDeleteIntent")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "intent_id",
                "requested_by",
                "requested_at",
                "reason",
                "mode",
                "confirmed",
                "candidate_ids",
                "metadata",
            },
            "CleanupDeleteIntent",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            intent_id=_non_empty_string(_required(mapping, "intent_id"), "intent_id"),
            requested_by=_non_empty_string(
                _required(mapping, "requested_by"), "requested_by"
            ),
            requested_at=_timestamp(_required(mapping, "requested_at"), "requested_at"),
            reason=_non_empty_string(_required(mapping, "reason"), "reason"),
            mode=_coerce_enum(
                mapping.get("mode", CleanupDeleteMode.DELETE_SELECTED_TARGETS.value),
                CleanupDeleteMode,
                "mode",
            ),
            confirmed=_bool(mapping.get("confirmed", True), "confirmed"),
            candidate_ids=_string_tuple(
                _sequence(mapping.get("candidate_ids", ())), "candidate_ids"
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CleanupResultEntry:
    """One mutating cleanup outcome entry."""

    candidate_id: str
    target: CleanupTargetRef
    outcome: CleanupResultOutcome
    reason_code: str
    completed_at: str
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    message: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "candidate_id", _non_empty_string(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "target", _target_ref(self.target, "target"))
        object.__setattr__(
            self, "outcome", _coerce_enum(self.outcome, CleanupResultOutcome, "outcome")
        )
        object.__setattr__(
            self, "reason_code", _non_empty_string(self.reason_code, "reason_code")
        )
        object.__setattr__(
            self, "completed_at", _timestamp(self.completed_at, "completed_at")
        )
        object.__setattr__(self, "message", _optional_string(self.message, "message"))
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "target": self.target.to_dict(),
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "completed_at": self.completed_at,
            "message": self.message,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupResultEntry":
        mapping = _mapping(data, "CleanupResultEntry")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "candidate_id",
                "target",
                "outcome",
                "reason_code",
                "completed_at",
                "message",
                "detail",
            },
            "CleanupResultEntry",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            candidate_id=_non_empty_string(
                _required(mapping, "candidate_id"), "candidate_id"
            ),
            target=CleanupTargetRef.from_dict(_required(mapping, "target")),
            outcome=_coerce_enum(
                _required(mapping, "outcome"), CleanupResultOutcome, "outcome"
            ),
            reason_code=_non_empty_string(
                _required(mapping, "reason_code"), "reason_code"
            ),
            completed_at=_timestamp(_required(mapping, "completed_at"), "completed_at"),
            message=_optional_string(mapping.get("message"), "message"),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Append-only result record for a mutating cleanup operation."""

    result_id: str
    run_uri: str
    created_at: str
    intent: CleanupDeleteIntent
    entries: tuple[CleanupResultEntry, ...] = ()
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    summary: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "result_id", _non_empty_string(self.result_id, "result_id"))
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        if not isinstance(self.intent, CleanupDeleteIntent):
            raise CleanupRecordError("intent must be a CleanupDeleteIntent")
        object.__setattr__(self, "entries", _tuple_of_result_entries(self.entries))
        object.__setattr__(self, "summary", _plain_mapping(self.summary, "summary"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "run_uri": self.run_uri,
            "created_at": self.created_at,
            "intent": self.intent.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": thaw_plain_data(self.summary, path="summary"),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupResult":
        mapping = _mapping(data, "CleanupResult")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "result_id",
                "run_uri",
                "created_at",
                "intent",
                "entries",
                "summary",
                "metadata",
            },
            "CleanupResult",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            result_id=_non_empty_string(_required(mapping, "result_id"), "result_id"),
            run_uri=_non_empty_string(_required(mapping, "run_uri"), "run_uri"),
            created_at=_timestamp(_required(mapping, "created_at"), "created_at"),
            intent=CleanupDeleteIntent.from_dict(_required(mapping, "intent")),
            entries=tuple(
                CleanupResultEntry.from_dict(entry)
                for entry in _sequence(mapping.get("entries", ()))
            ),
            summary=_plain_mapping(mapping.get("summary", {}), "summary"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CleanupRecordError(f"{path}.from_dict expects mapping")
    return value


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise CleanupRecordError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], path: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise CleanupRecordError(
            f"{path}: unknown field(s): {', '.join(sorted(unknown))}"
        )


def _require_schema_version(value: object, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != CLEANUP_RECORD_SCHEMA_VERSION
    ):
        raise CleanupRecordError(
            f"{field} must be {CLEANUP_RECORD_SCHEMA_VERSION}"
        )
    return value


def _coerce_enum(value: object, enum_type: type[_E], field: str) -> _E:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            choices = ", ".join(item.value for item in enum_type)
            raise CleanupRecordError(f"{field} must be one of: {choices}") from exc
    choices = ", ".join(item.value for item in enum_type)
    raise CleanupRecordError(f"{field} must be one of: {choices}")


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CleanupRecordError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _timestamp(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise CleanupRecordError(f"{field} must be a UTC loom timestamp") from exc
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CleanupRecordError(f"{field} must be a bool")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise CleanupRecordError(f"{field} must be a mapping")
    try:
        return cast(
            Mapping[str, PlainData],
            freeze_plain_data(value, path=field),
        )
    except Exception as exc:
        raise CleanupRecordError(f"{field} must contain plain data") from exc


def _tuple_plain_mappings(
    values: Iterable[object], field: str
) -> tuple[Mapping[str, PlainData], ...]:
    return tuple(_plain_mapping(value, f"{field}[]") for value in values)


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise CleanupRecordError("expected a sequence")
    return value


def _string_tuple(values: Iterable[object], field: str) -> tuple[str, ...]:
    return tuple(_non_empty_string(value, f"{field}[]") for value in values)


def _target_ref(value: object, field: str) -> CleanupTargetRef:
    if not isinstance(value, CleanupTargetRef):
        raise CleanupRecordError(f"{field} must be a CleanupTargetRef")
    return value


def _tuple_of_entries(
    values: Iterable[CleanupReportEntry],
) -> tuple[CleanupReportEntry, ...]:
    entries = tuple(values)
    if any(not isinstance(entry, CleanupReportEntry) for entry in entries):
        raise CleanupRecordError("entries must contain CleanupReportEntry values")
    return entries


def _tuple_of_result_entries(
    values: Iterable[CleanupResultEntry],
) -> tuple[CleanupResultEntry, ...]:
    entries = tuple(values)
    if any(not isinstance(entry, CleanupResultEntry) for entry in entries):
        raise CleanupRecordError("entries must contain CleanupResultEntry values")
    return entries


__all__ = [
    "CLEANUP_RECORD_SCHEMA_VERSION",
    "CleanupDeleteIntent",
    "CleanupDeleteMode",
    "CleanupManagedRoot",
    "CleanupReport",
    "CleanupReportEntry",
    "CleanupReportEntryStatus",
    "CleanupResult",
    "CleanupResultEntry",
    "CleanupResultOutcome",
    "CleanupTargetKind",
    "CleanupTargetRef",
]
