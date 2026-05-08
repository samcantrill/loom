"""Backend-neutral submitted-operation records and predicates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import cast

from loom.serialization import PlainData, ensure_plain_data, load_versioned_document
from loom.serialization.errors import PlainDataError, SchemaVersionError
from loom.timestamps import parse_timestamp

SUBMITTED_OPERATION_SCHEMA_VERSION = 1
SUBMITTED_OPERATION_METADATA_KEY = "submitted_operation"

_SAFE_SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ACTIVE_STATES = frozenset(
    {
        "SUBMITTED",
        "PARTIAL",
        "CANCELLING",
        "UNKNOWN",
    }
)
_TERMINAL_STATES = frozenset({"CANCELLED", "COMPLETED", "FAILED"})
_ACTIVE_SUMMARY_KEYS = frozenset(
    {
        "active",
        "pending",
        "prepared",
        "submitting",
        "submitted",
        "running",
        "partial",
        "cancelling",
        "unknown",
    }
)


class SubmittedOperationError(ValueError):
    """Raised when a submitted-operation record is invalid."""


class SubmittedOperationState(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SubmittedOperationRecord:
    """Persisted backend-neutral summary for one submitted operation."""

    run_uri: str
    submission_id: str
    backend: str
    mode: str
    created_at: str
    updated_at: str
    state: SubmittedOperationState
    manifest_relative_path: str
    summary_counts: Mapping[str, int] = field(default_factory=dict)
    backend_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = SUBMITTED_OPERATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.run_uri, field="run_uri")
        object.__setattr__(
            self,
            "submission_id",
            validate_submission_id(self.submission_id),
        )
        _validate_non_empty_string(self.backend, field="backend")
        _validate_non_empty_string(self.mode, field="mode")
        _validate_timestamp(self.created_at, field="created_at")
        _validate_timestamp(self.updated_at, field="updated_at")
        object.__setattr__(
            self,
            "state",
            parse_submitted_operation_state(
                self.state.value
                if isinstance(self.state, SubmittedOperationState)
                else self.state
            ),
        )
        object.__setattr__(
            self,
            "manifest_relative_path",
            validate_manifest_relative_path(self.manifest_relative_path),
        )
        object.__setattr__(
            self,
            "summary_counts",
            _validate_summary_counts(self.summary_counts),
        )
        object.__setattr__(
            self,
            "backend_metadata",
            _validate_plain_mapping(self.backend_metadata, field="backend_metadata"),
        )
        if self.schema_version != SUBMITTED_OPERATION_SCHEMA_VERSION:
            raise SubmittedOperationError(
                f"unsupported schema_version '{self.schema_version}', expected "
                f"{SUBMITTED_OPERATION_SCHEMA_VERSION}"
            )

    @property
    def active(self) -> bool:
        return is_active_submitted_operation(self)

    @property
    def terminal(self) -> bool:
        return is_terminal_submitted_operation(self)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "submission_id": self.submission_id,
            "backend": self.backend,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": self.state.value,
            "manifest_relative_path": self.manifest_relative_path,
            "summary_counts": dict(self.summary_counts),
            "backend_metadata": dict(self.backend_metadata),
        }

    def to_summary_dict(self) -> dict[str, PlainData]:
        return {
            "submission_id": self.submission_id,
            "backend": self.backend,
            "mode": self.mode,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "manifest_relative_path": self.manifest_relative_path,
            "summary_counts": dict(self.summary_counts),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: object) -> "SubmittedOperationRecord":
        try:
            payload = load_versioned_document(
                data,
                current_version=SUBMITTED_OPERATION_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "submission_id",
                    "backend",
                    "mode",
                    "created_at",
                    "updated_at",
                    "state",
                    "manifest_relative_path",
                    "summary_counts",
                },
                optional={"backend_metadata"},
            )
        except SchemaVersionError as exc:
            raise SubmittedOperationError(
                f"SubmittedOperationRecord.from_dict: {exc}"
            ) from exc
        return cls(
            schema_version=SUBMITTED_OPERATION_SCHEMA_VERSION,
            run_uri=cast(str, payload["run_uri"]),
            submission_id=cast(str, payload["submission_id"]),
            backend=cast(str, payload["backend"]),
            mode=cast(str, payload["mode"]),
            created_at=cast(str, payload["created_at"]),
            updated_at=cast(str, payload["updated_at"]),
            state=parse_submitted_operation_state(payload["state"]),
            manifest_relative_path=cast(str, payload["manifest_relative_path"]),
            summary_counts=_validate_summary_counts(payload["summary_counts"]),
            backend_metadata=_validate_plain_mapping(
                payload.get("backend_metadata", {}),
                field="backend_metadata",
            ),
        )


def parse_submitted_operation_state(value: object) -> SubmittedOperationState:
    if not isinstance(value, str):
        raise SubmittedOperationError("state must be a string")
    try:
        return SubmittedOperationState(value)
    except ValueError as exc:
        raise SubmittedOperationError(
            f"invalid submitted-operation state '{value}'"
        ) from exc


def validate_submission_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_SUBMISSION_ID_RE.fullmatch(value):
        raise SubmittedOperationError(
            "submission_id must be a non-empty safe identifier containing only "
            "letters, digits, '_', '.', or '-'"
        )
    return value


def validate_manifest_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SubmittedOperationError(
            "manifest_relative_path must be a non-empty string"
        )
    if value.strip() != value:
        raise SubmittedOperationError(
            "manifest_relative_path must not contain leading or trailing whitespace"
        )
    if "\\" in value:
        raise SubmittedOperationError("manifest_relative_path must use '/' separators")
    if value.startswith("/"):
        raise SubmittedOperationError("manifest_relative_path must be relative")
    if "//" in value:
        raise SubmittedOperationError(
            "manifest_relative_path must not contain empty path segments"
        )
    if value == "." or value.startswith("./") or "/./" in value or value.endswith("/."):
        raise SubmittedOperationError(
            "manifest_relative_path must not contain empty, '.', or '..' path segments"
        )
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise SubmittedOperationError(
            "manifest_relative_path must not contain whitespace or control characters"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath("."):
        raise SubmittedOperationError("manifest_relative_path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SubmittedOperationError(
            "manifest_relative_path must not contain empty, '.', or '..' path segments"
        )
    return path.as_posix()


def is_active_submitted_operation(record: SubmittedOperationRecord) -> bool:
    if record.state.value in _ACTIVE_STATES:
        return True
    return _summary_indicates_active(record.summary_counts)


def is_terminal_submitted_operation(record: SubmittedOperationRecord) -> bool:
    return record.state.value in _TERMINAL_STATES and not _summary_indicates_active(
        record.summary_counts
    )


def sort_submitted_operations(
    records: object,
) -> tuple[SubmittedOperationRecord, ...]:
    if not isinstance(records, tuple):
        records = tuple(records)  # type: ignore[arg-type]
    return tuple(
        sorted(
            cast(tuple[SubmittedOperationRecord, ...], records),
            key=lambda record: (record.created_at, record.submission_id),
        )
    )


def latest_submitted_operation(
    records: object,
) -> SubmittedOperationRecord | None:
    ordered = sort_submitted_operations(records)
    return ordered[-1] if ordered else None


def latest_active_submitted_operation(
    records: object,
) -> SubmittedOperationRecord | None:
    active = tuple(
        record for record in sort_submitted_operations(records) if record.active
    )
    return active[-1] if active else None


def submitted_stage_metadata(
    *,
    record: SubmittedOperationRecord,
    stage_name: str,
    attempt: int,
    continuation_executor: str,
    stage_metadata: Mapping[str, PlainData] | None = None,
) -> dict[str, PlainData]:
    """Build shared metadata that ties a submitted stage to a registry record."""

    if not isinstance(stage_name, str) or not stage_name:
        raise SubmittedOperationError("stage_name must be a non-empty string")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise SubmittedOperationError("attempt must be a positive integer")
    if not isinstance(continuation_executor, str) or not continuation_executor:
        raise SubmittedOperationError(
            "continuation_executor must be a non-empty string"
        )
    metadata = _validate_plain_mapping(stage_metadata or {}, field="stage_metadata")
    return {
        SUBMITTED_OPERATION_METADATA_KEY: {
            "run_uri": record.run_uri,
            "submission_id": record.submission_id,
            "backend": record.backend,
            "mode": record.mode,
            "manifest_relative_path": record.manifest_relative_path,
            "stage_name": stage_name,
            "attempt": attempt,
            "continuation_executor": continuation_executor,
            "stage_metadata": metadata,
        }
    }


def _summary_indicates_active(summary_counts: Mapping[str, int]) -> bool:
    for key, count in summary_counts.items():
        if key.lower() in _ACTIVE_SUMMARY_KEYS and count > 0:
            return True
    return False


def _validate_non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SubmittedOperationError(f"{field} must be a non-empty string")
    return value


def _validate_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SubmittedOperationError(f"{field} must be a string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise SubmittedOperationError(
            f"{field} must be a valid loom timestamp: {exc}"
        ) from exc
    return value


def _validate_summary_counts(value: object) -> dict[str, int]:
    normalized = _validate_plain_mapping(value, field="summary_counts")
    counts: dict[str, int] = {}
    for key, count in normalized.items():
        if not isinstance(key, str) or not key:
            raise SubmittedOperationError(
                "summary_counts keys must be non-empty strings"
            )
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SubmittedOperationError(
                f"summary_counts[{key!r}] must be a non-negative integer"
            )
        counts[key] = count
    return counts


def _validate_plain_mapping(value: object, *, field: str) -> dict[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise SubmittedOperationError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, dict):
        raise SubmittedOperationError(f"{field} must be a mapping")
    return normalized


__all__ = [
    "SUBMITTED_OPERATION_METADATA_KEY",
    "SUBMITTED_OPERATION_SCHEMA_VERSION",
    "SubmittedOperationError",
    "SubmittedOperationRecord",
    "SubmittedOperationState",
    "is_active_submitted_operation",
    "is_terminal_submitted_operation",
    "latest_active_submitted_operation",
    "latest_submitted_operation",
    "parse_submitted_operation_state",
    "sort_submitted_operations",
    "submitted_stage_metadata",
    "validate_manifest_relative_path",
    "validate_submission_id",
]
