"""Run lock model foundations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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

LOCK_SCHEMA_VERSION = 1


class RunLockValidationError(ValueError):
    """Raised when run lock records are malformed."""


@dataclass(frozen=True, slots=True)
class RunLockRecord:
    run_uri: str
    token: str
    acquired_at: str
    owner: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = LOCK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        object.__setattr__(
            self, "run_uri", _require_non_empty_string(self.run_uri, field="run_uri")
        )
        object.__setattr__(
            self, "token", _require_non_empty_string(self.token, field="token")
        )
        object.__setattr__(
            self, "acquired_at", _timestamp(self.acquired_at, field="acquired_at")
        )
        object.__setattr__(
            self,
            "owner",
            freeze_plain_data(_plain_mapping(self.owner, field="owner"), path="owner"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "token": self.token,
            "acquired_at": self.acquired_at,
            "owner": thaw_plain_data(self.owner, path="owner"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunLockRecord":
        try:
            mapping = load_versioned_document(
                data,
                current_version=LOCK_SCHEMA_VERSION,
                required={"run_uri", "token", "acquired_at", "owner"},
                optional=(),
                path="RunLockRecord",
            )
        except SchemaVersionError as exc:
            raise RunLockValidationError(f"RunLockRecord.from_dict: {exc}") from exc
        return cls(
            schema_version=_require_schema_version(mapping["schema_version"]),
            run_uri=_require_non_empty_string(mapping["run_uri"], field="run_uri"),
            token=_require_non_empty_string(mapping["token"], field="token"),
            acquired_at=_timestamp(mapping["acquired_at"], field="acquired_at"),
            owner=_plain_mapping(mapping["owner"], field="owner"),
        )


def _require_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunLockValidationError("schema_version must be a positive integer")
    if value != LOCK_SCHEMA_VERSION:
        raise RunLockValidationError(
            f"unsupported schema_version {value!r}, expected {LOCK_SCHEMA_VERSION}"
        )
    return value


def _require_non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunLockValidationError(f"{field} must be a non-empty string")
    return value


def _timestamp(value: object, *, field: str) -> str:
    text = _require_non_empty_string(value, field=field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise RunLockValidationError(
            f"{field} must be a valid loom timestamp: {exc}"
        ) from exc
    return text


def _plain_mapping(value: object, *, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise RunLockValidationError(
            f"{field} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise RunLockValidationError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = ["LOCK_SCHEMA_VERSION", "RunLockRecord", "RunLockValidationError"]
