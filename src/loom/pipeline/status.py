"""Static status value objects for pipeline and stage state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, cast

from loom.ids import RunID, StageID
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp

from .errors import StatusSerializationError

STATUS_SCHEMA_VERSION = 1


class RunStatus(StrEnum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


def parse_run_status(value: object) -> RunStatus:
    if not isinstance(value, str):
        raise StatusSerializationError("run status must be a string")
    try:
        return RunStatus(value)
    except ValueError as exc:
        raise StatusSerializationError(f"invalid run status '{value}'") from exc


def parse_stage_status(value: object) -> StageStatus:
    if not isinstance(value, str):
        raise StatusSerializationError("stage status must be a string")
    try:
        return StageStatus(value)
    except ValueError as exc:
        raise StatusSerializationError(f"invalid stage status '{value}'") from exc


def _validate_status_schema_version(value: object) -> int:
    if value is None:
        raise StatusSerializationError("schema_version is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatusSerializationError("schema_version must be a positive integer")
    if value != STATUS_SCHEMA_VERSION:
        raise StatusSerializationError(f"unsupported schema_version '{value}', expected {STATUS_SCHEMA_VERSION}")
    return value


def _validate_timestamp(value: object, *, field: str) -> str:
    if value is None:
        raise StatusSerializationError(f"{field} is required")
    if not isinstance(value, str):
        raise StatusSerializationError(f"{field} must be a string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise StatusSerializationError(f"{field} must be a valid loom timestamp: {exc}") from exc
    return value


def _validate_timestamp_or_none(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StatusSerializationError(f"{field} must be a string or null")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise StatusSerializationError(f"{field} must be a valid loom timestamp: {exc}") from exc
    return value


def _validate_status_message(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StatusSerializationError(f"{field} must be a string")
    return value


def _validate_attempts(value: object) -> int:
    if value is None:
        raise StatusSerializationError("attempts is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatusSerializationError("attempts must be a positive integer")
    if value <= 0:
        raise StatusSerializationError("attempts must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class RunStatusRecord:
    run_id: RunID
    status: RunStatus
    created_at: str
    updated_at: str
    schema_version: int = STATUS_SCHEMA_VERSION
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise StatusSerializationError("run_id must be a non-empty string")
        object.__setattr__(self, "status", parse_run_status(self.status.value if isinstance(self.status, RunStatus) else self.status))
        _validate_timestamp(self.created_at, field="created_at")
        _validate_timestamp(self.updated_at, field="updated_at")
        _validate_timestamp_or_none(self.started_at, field="started_at")
        _validate_timestamp_or_none(self.finished_at, field="finished_at")
        _validate_status_message(self.message, field="message")
        _validate_status_schema_version(self.schema_version)
        try:
            object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))
        except PlainDataError as exc:
            raise StatusSerializationError(f"metadata must be plain-data-compatible: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunStatusRecord":
        if not isinstance(data, Mapping):
            raise StatusSerializationError("RunStatusRecord.from_dict expects a mapping")
        allowed = {
            "run_id",
            "status",
            "created_at",
            "updated_at",
            "schema_version",
            "started_at",
            "finished_at",
            "message",
            "metadata",
        }
        unknown = set(data) - allowed
        if unknown:
            raise StatusSerializationError(
                f"RunStatusRecord.from_dict received unknown field(s): {', '.join(sorted(unknown))}",
            )
        required = {"run_id", "status", "created_at", "updated_at", "schema_version"}
        missing = required - set(data)
        if missing:
            raise StatusSerializationError(
                f"RunStatusRecord.from_dict missing required field(s): {', '.join(sorted(missing))}",
            )

        return cls(
            run_id=cast(str, data["run_id"]),
            status=parse_run_status(data["status"]),
            created_at=_validate_timestamp(data["created_at"], field="created_at"),
            updated_at=_validate_timestamp(data["updated_at"], field="updated_at"),
            schema_version=_validate_status_schema_version(data["schema_version"]),
            started_at=_validate_timestamp_or_none(data.get("started_at"), field="started_at"),
            finished_at=_validate_timestamp_or_none(data.get("finished_at"), field="finished_at"),
            message=_validate_status_message(data.get("message"), field="message"),
            metadata=cast(Mapping[str, Any], ensure_plain_data(data.get("metadata", {}), path="metadata")),
        )


@dataclass(frozen=True, slots=True)
class StageStatusRecord:
    run_id: RunID
    stage_id: StageID
    status: StageStatus
    created_at: str
    updated_at: str
    schema_version: int = STATUS_SCHEMA_VERSION
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int = 1
    message: str | None = None
    owner: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise StatusSerializationError("run_id must be a non-empty string")
        if not isinstance(self.stage_id, str) or not self.stage_id:
            raise StatusSerializationError("stage_id must be a non-empty string")
        object.__setattr__(self, "status", parse_stage_status(self.status.value if isinstance(self.status, StageStatus) else self.status))
        _validate_timestamp(self.created_at, field="created_at")
        _validate_timestamp(self.updated_at, field="updated_at")
        _validate_timestamp_or_none(self.started_at, field="started_at")
        _validate_timestamp_or_none(self.finished_at, field="finished_at")
        _validate_status_message(self.message, field="message")
        _validate_status_schema_version(self.schema_version)
        _validate_attempts(self.attempts)
        try:
            object.__setattr__(self, "owner", ensure_plain_data(dict(self.owner), path="owner"))
            object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))
        except PlainDataError as exc:
            raise StatusSerializationError(f"owner/metadata must be plain-data-compatible: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempts": self.attempts,
            "message": self.message,
            "owner": dict(self.owner),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageStatusRecord":
        if not isinstance(data, Mapping):
            raise StatusSerializationError("StageStatusRecord.from_dict expects a mapping")
        allowed = {
            "run_id",
            "stage_id",
            "status",
            "created_at",
            "updated_at",
            "schema_version",
            "started_at",
            "finished_at",
            "attempts",
            "message",
            "owner",
            "metadata",
        }
        unknown = set(data) - allowed
        if unknown:
            raise StatusSerializationError(
                f"StageStatusRecord.from_dict received unknown field(s): {', '.join(sorted(unknown))}",
            )
        required = {"run_id", "stage_id", "status", "created_at", "updated_at", "schema_version", "attempts"}
        missing = required - set(data)
        if missing:
            raise StatusSerializationError(
                f"StageStatusRecord.from_dict missing required field(s): {', '.join(sorted(missing))}",
            )

        return cls(
            run_id=cast(str, data["run_id"]),
            stage_id=cast(str, data["stage_id"]),
            status=parse_stage_status(data["status"]),
            created_at=_validate_timestamp(data["created_at"], field="created_at"),
            updated_at=_validate_timestamp(data["updated_at"], field="updated_at"),
            schema_version=_validate_status_schema_version(data["schema_version"]),
            started_at=_validate_timestamp_or_none(data.get("started_at"), field="started_at"),
            finished_at=_validate_timestamp_or_none(data.get("finished_at"), field="finished_at"),
            attempts=_validate_attempts(data["attempts"]),
            message=_validate_status_message(data.get("message"), field="message"),
            owner=cast(Mapping[str, Any], ensure_plain_data(data.get("owner", {}), path="owner")),
            metadata=cast(Mapping[str, Any], ensure_plain_data(data.get("metadata", {}), path="metadata")),
        )


__all__ = [
    "RunStatus",
    "StageStatus",
    "RunStatusRecord",
    "StageStatusRecord",
    "parse_run_status",
    "parse_stage_status",
    "STATUS_SCHEMA_VERSION",
]
