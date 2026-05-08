"""Prepared-run metadata contracts for durable run continuation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from loom.pipeline.stores.errors import PreparedRunStorePayloadError
from loom.pipeline.stores.prepared_run import (
    PREPARED_RUN_CONFIG_FIELDS,
    PREPARED_RUN_CONTINUATION_WHOLE_RUN,
    PREPARED_RUN_PLAN_FIELDS,
    PREPARED_RUN_PROVENANCE_FIELDS,
    PREPARED_RUN_RUNTIME_FIELDS,
    PREPARED_RUN_SCHEMA_VERSION,
    validate_prepared_run_summary,
    validate_prepared_run_typed_metadata,
)
from loom.serialization import PlainData, load_versioned_document
from loom.serialization.errors import SchemaVersionError

from .errors import RunRequestError

_CONTINUATION_TYPES = frozenset({PREPARED_RUN_CONTINUATION_WHOLE_RUN})


class PreparedRunPayloadError(RunRequestError):
    """Structured error raised when prepared-run metadata is unsafe."""

    def __init__(self, field: str, reason: str, *, category: str) -> None:
        self.field = field
        self.reason = reason
        self.category = category
        super().__init__(
            f"unsafe prepared-run payload at {field}: {reason} ({category})"
        )


@dataclass(frozen=True, slots=True)
class PreparedRunRecord:
    """Schema-versioned, artifact-safe run preparation metadata."""

    schema_version: int
    run_uri: str
    prepared_at: str
    executor_name: str
    continuation_type: str
    plan: Mapping[str, PlainData] = field(default_factory=dict)
    config: Mapping[str, PlainData] = field(default_factory=dict)
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    runtime: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != PREPARED_RUN_SCHEMA_VERSION:
            raise RunRequestError("PreparedRunRecord.schema_version must be 1")
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError("PreparedRunRecord.run_uri must be a non-empty string")
        if not isinstance(self.prepared_at, str) or not self.prepared_at:
            raise RunRequestError(
                "PreparedRunRecord.prepared_at must be a non-empty string"
            )
        if not isinstance(self.executor_name, str) or not self.executor_name:
            raise RunRequestError(
                "PreparedRunRecord.executor_name must be a non-empty string"
            )
        if self.continuation_type not in _CONTINUATION_TYPES:
            valid = ", ".join(sorted(_CONTINUATION_TYPES))
            raise RunRequestError(
                "PreparedRunRecord.continuation_type must be one of: " + valid
            )
        object.__setattr__(
            self,
            "plan",
            _safe_mapping(self.plan, field="plan", allowed=PREPARED_RUN_PLAN_FIELDS),
        )
        object.__setattr__(
            self,
            "config",
            _safe_mapping(
                self.config, field="config", allowed=PREPARED_RUN_CONFIG_FIELDS
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            _safe_mapping(
                self.provenance,
                field="provenance",
                allowed=PREPARED_RUN_PROVENANCE_FIELDS,
            ),
        )
        object.__setattr__(
            self,
            "runtime",
            _safe_mapping(
                self.runtime, field="runtime", allowed=PREPARED_RUN_RUNTIME_FIELDS
            ),
        )
        object.__setattr__(
            self, "metadata", _safe_typed_metadata(self.metadata, field="metadata")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "prepared_at": self.prepared_at,
            "executor_name": self.executor_name,
            "continuation_type": self.continuation_type,
            "plan": dict(self.plan),
            "config": dict(self.config),
            "provenance": dict(self.provenance),
            "runtime": dict(self.runtime),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PreparedRunRecord":
        try:
            mapping = load_versioned_document(
                data,
                current_version=PREPARED_RUN_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "prepared_at",
                    "executor_name",
                    "continuation_type",
                },
                optional={"plan", "config", "provenance", "runtime", "metadata"},
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"PreparedRunRecord.from_dict: {exc}") from exc
        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_uri=_str(mapping["run_uri"], "run_uri"),
            prepared_at=_str(mapping["prepared_at"], "prepared_at"),
            executor_name=_str(mapping["executor_name"], "executor_name"),
            continuation_type=_str(mapping["continuation_type"], "continuation_type"),
            plan=cast(Mapping[str, PlainData], mapping.get("plan", {})),
            config=cast(Mapping[str, PlainData], mapping.get("config", {})),
            provenance=cast(Mapping[str, PlainData], mapping.get("provenance", {})),
            runtime=cast(Mapping[str, PlainData], mapping.get("runtime", {})),
            metadata=cast(Mapping[str, PlainData], mapping.get("metadata", {})),
        )


def _safe_mapping(
    value: Mapping[str, PlainData],
    *,
    field: str,
    allowed: frozenset[str],
) -> dict[str, PlainData]:
    try:
        return validate_prepared_run_summary(value, field=field, allowed=allowed)
    except PreparedRunStorePayloadError as exc:
        raise _payload_error(exc) from exc


def _safe_typed_metadata(
    value: Mapping[str, PlainData],
    *,
    field: str,
) -> dict[str, PlainData]:
    try:
        return validate_prepared_run_typed_metadata(value, field=field)
    except PreparedRunStorePayloadError as exc:
        raise _payload_error(exc) from exc


def _payload_error(exc: PreparedRunStorePayloadError) -> PreparedRunPayloadError:
    return PreparedRunPayloadError(exc.field, exc.reason, category=exc.category)


def _str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunRequestError(f"{field} must be a non-empty string")
    return value


def _int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunRequestError(f"{field} must be an integer")
    return value


__all__ = [
    "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
    "PREPARED_RUN_SCHEMA_VERSION",
    "PreparedRunPayloadError",
    "PreparedRunRecord",
]
