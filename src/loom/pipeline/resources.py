"""Runtime resource foundation models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from loom.serialization import (
    PlainData,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError

from .errors import RuntimeResourceError

RESOURCE_SCHEMA_VERSION = 1

_RESOURCE_FIELDS = frozenset({"cpus", "memory_mb", "gpus", "custom"})
_DEFERRED_RESOURCE_FIELDS = frozenset(
    {
        "wall_time_seconds",
        "timeout_seconds",
        "timeout",
        "executor",
        "runtime",
        "retry",
        "slurm",
        "partition",
        "account",
        "qos",
        "gres",
        "sbatch_args",
        "container",
        "docker",
        "apptainer",
        "image",
        "remote_store",
        "store",
        "profile",
        "env",
        "environment",
    }
)


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    cpus: int | None = None
    memory_mb: int | None = None
    gpus: int | None = None
    custom: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = RESOURCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        object.__setattr__(
            self,
            "cpus",
            _optional_positive_int(self.cpus, field="cpus"),
        )
        object.__setattr__(
            self,
            "memory_mb",
            _optional_positive_int(self.memory_mb, field="memory_mb"),
        )
        object.__setattr__(
            self,
            "gpus",
            _optional_non_negative_int(self.gpus, field="gpus"),
        )
        object.__setattr__(
            self,
            "custom",
            freeze_plain_data(_plain_mapping(self.custom, field="custom"), path="custom"),
        )
        _reject_deferred_fields(self.custom, path="custom")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
            "gpus": self.gpus,
            "custom": thaw_plain_data(self.custom, path="custom"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ResourceRequest":
        try:
            mapping = load_versioned_document(
                data,
                current_version=RESOURCE_SCHEMA_VERSION,
                required={"cpus", "memory_mb", "gpus", "custom"},
                optional=(),
                path="ResourceRequest",
            )
        except SchemaVersionError as exc:
            raise RuntimeResourceError(f"ResourceRequest.from_dict: {exc}") from exc
        return cls(
            schema_version=_require_schema_version(mapping["schema_version"]),
            cpus=_optional_positive_int(mapping["cpus"], field="cpus"),
            memory_mb=_optional_positive_int(mapping["memory_mb"], field="memory_mb"),
            gpus=_optional_non_negative_int(mapping["gpus"], field="gpus"),
            custom=_plain_mapping(mapping["custom"], field="custom"),
        )


def parse_resource_request(data: object | None) -> ResourceRequest:
    """Parse authored stage resources without requiring a schema wrapper."""

    if data is None:
        return ResourceRequest()
    mapping = _plain_mapping(data, field="resources")
    _reject_deferred_fields(mapping, path="resources")
    unknown = set(mapping) - _RESOURCE_FIELDS
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"resources contains unknown field(s): {fields}")
    custom = _plain_mapping(mapping.get("custom", {}), field="resources.custom")
    _reject_deferred_fields(custom, path="resources.custom")
    return ResourceRequest(
        cpus=_optional_positive_int(mapping.get("cpus"), field="resources.cpus"),
        memory_mb=_optional_positive_int(
            mapping.get("memory_mb"), field="resources.memory_mb"
        ),
        gpus=_optional_non_negative_int(mapping.get("gpus"), field="resources.gpus"),
        custom=custom,
    )


def _require_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError("schema_version must be a positive integer")
    if value != RESOURCE_SCHEMA_VERSION:
        raise RuntimeResourceError(
            f"unsupported schema_version {value!r}, expected {RESOURCE_SCHEMA_VERSION}"
        )
    return value


def _optional_positive_int(value: object | None, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError(f"{field} must be a positive integer or null")
    if value <= 0:
        raise RuntimeResourceError(f"{field} must be a positive integer")
    return value


def _optional_non_negative_int(value: object | None, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError(f"{field} must be a non-negative integer or null")
    if value < 0:
        raise RuntimeResourceError(f"{field} must be a non-negative integer")
    return value


def _plain_mapping(value: object, *, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = thaw_plain_data(value, path=field)
    except PlainDataError as exc:
        raise RuntimeResourceError(
            f"{field} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _reject_deferred_fields(mapping: Mapping[str, object], *, path: str) -> None:
    deferred = set(mapping) & _DEFERRED_RESOURCE_FIELDS
    if deferred:
        fields = ", ".join(sorted(deferred))
        raise RuntimeResourceError(
            f"{path} uses deferred local-v0 resource field(s) not supported in v0: {fields}"
        )


__all__ = ["RESOURCE_SCHEMA_VERSION", "ResourceRequest", "parse_resource_request"]
