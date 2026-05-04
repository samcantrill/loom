"""Runtime request foundation models."""

from __future__ import annotations

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

from .errors import RuntimeResourceError
from .resources import ResourceRequest

RUNTIME_SCHEMA_VERSION = 1

_RUNTIME_FIELDS = frozenset({"kind", "resources", "metadata", "schema_version"})
_DEFERRED_RUNTIME_FIELDS = frozenset(
    {
        "executor",
        "scheduler",
        "slurm",
        "container",
        "docker",
        "apptainer",
        "remote_store",
        "retry",
        "timeout",
        "timeout_seconds",
        "profile",
        "env",
        "environment",
    }
)


class RuntimeKind(StrEnum):
    LOCAL = "LOCAL"


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    kind: RuntimeKind = RuntimeKind.LOCAL
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = RUNTIME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        object.__setattr__(self, "kind", _coerce_runtime_kind(self.kind))
        if not isinstance(self.resources, ResourceRequest):
            raise RuntimeResourceError("RuntimeRequest.resources must be a ResourceRequest")
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(_plain_mapping(self.metadata, field="metadata"), path="metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "resources": self.resources.to_dict(),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RuntimeRequest":
        mapping = _runtime_mapping(data, path="RuntimeRequest")
        _reject_deferred_fields(mapping, path="RuntimeRequest")
        unknown = set(mapping) - _RUNTIME_FIELDS
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(f"RuntimeRequest contains unknown field(s): {fields}")
        try:
            document = load_versioned_document(
                mapping,
                current_version=RUNTIME_SCHEMA_VERSION,
                required={"kind", "resources", "metadata"},
                optional=(),
                path="RuntimeRequest",
            )
        except SchemaVersionError as exc:
            raise RuntimeResourceError(f"RuntimeRequest.from_dict: {exc}") from exc
        return cls(
            schema_version=_require_schema_version(document["schema_version"]),
            kind=_coerce_runtime_kind(document["kind"]),
            resources=ResourceRequest.from_dict(document["resources"]),
            metadata=_plain_mapping(document["metadata"], field="metadata"),
        )


def parse_runtime_request(data: object | None) -> RuntimeRequest:
    if data is None:
        return RuntimeRequest()
    return RuntimeRequest.from_dict(data)


def _coerce_runtime_kind(value: object) -> RuntimeKind:
    if isinstance(value, RuntimeKind):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError("RuntimeRequest.kind must be a string")
    try:
        kind = RuntimeKind(value)
    except ValueError as exc:
        raise RuntimeResourceError(
            f"unsupported RuntimeRequest.kind {value!r}; only LOCAL is supported in v0"
        ) from exc
    if kind is not RuntimeKind.LOCAL:
        raise RuntimeResourceError("only LOCAL runtime is supported in v0")
    return kind


def _require_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError("schema_version must be a positive integer")
    if value != RUNTIME_SCHEMA_VERSION:
        raise RuntimeResourceError(
            f"unsupported schema_version {value!r}, expected {RUNTIME_SCHEMA_VERSION}"
        )
    return value


def _runtime_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, *, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise RuntimeResourceError(
            f"{field} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _reject_deferred_fields(mapping: Mapping[str, object], *, path: str) -> None:
    deferred = set(mapping) & _DEFERRED_RUNTIME_FIELDS
    if deferred:
        fields = ", ".join(sorted(deferred))
        raise RuntimeResourceError(
            f"{path} uses deferred runtime field(s) not supported in local v0: {fields}"
        )


__all__ = [
    "RUNTIME_SCHEMA_VERSION",
    "RuntimeKind",
    "RuntimeRequest",
    "parse_runtime_request",
]
