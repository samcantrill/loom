"""Resource reference primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, cast

from loom.errors import FingerprintError, ResourceError, ValidationError
from loom.fingerprints import validate_digest
from loom.ids import Checksum, CodecKey, ResourceType
from loom.serialization import PlainData, ensure_plain_data


class ResourceRefError(ResourceError, ValidationError):
    """Error raised when a resource reference is invalid."""


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """Metadata describing a resource."""

    uri: str
    resource_type: ResourceType
    codec_key: CodecKey | None = None
    schema_version: int = 1
    checksum: Checksum | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str) or not self.uri:
            raise ResourceRefError("uri must be a non-empty string")
        if not isinstance(self.resource_type, str) or not self.resource_type:
            raise ResourceRefError("resource_type must be a non-empty string")
        if self.codec_key is not None and (not isinstance(self.codec_key, str) or not self.codec_key):
            raise ResourceRefError("codec_key must be None or a non-empty string")
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ResourceRefError("schema_version must be a positive integer")
        if self.checksum is not None:
            object.__setattr__(self, "checksum", _ensure_digest(self.checksum))
        object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "resource_type": self.resource_type,
            "codec_key": self.codec_key,
            "schema_version": self.schema_version,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ResourceRef":
        if not isinstance(data, dict):
            raise ResourceRefError("ResourceRef.from_dict expects mapping")
        required = {"uri", "resource_type"}
        allowed = required | {"codec_key", "schema_version", "checksum", "metadata"}
        unknown = set(data) - allowed
        if unknown:
            raise ResourceRefError(f"ResourceRef.from_dict received unknown fields: {', '.join(sorted(unknown))}")
        missing = required - set(data)
        if missing:
            raise ResourceRefError(f"ResourceRef.from_dict missing required field(s): {', '.join(sorted(missing))}")

        return cls(
            uri=_require_str(data.get("uri"), "uri"),
            resource_type=_require_str(data.get("resource_type"), "resource_type"),
            codec_key=_ensure_codec_key(data.get("codec_key", None)),
            schema_version=_require_schema_version(data.get("schema_version", 1)),
            checksum=_ensure_digest(data.get("checksum")),
            metadata=cast(Mapping[str, PlainData], ensure_plain_data(data.get("metadata", {}), path="metadata")),
        )


def _ensure_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResourceRefError(f"{field} must be a non-empty string")
    return value


def _require_str(value: Any, field: str) -> str:
    if value is None:
        raise ResourceRefError(f"{field} is required")
    return _ensure_str(value, field)


def _ensure_codec_key(value: Any) -> str | None:
    if value is None:
        return None
    return _require_str(value, "codec_key")


def _require_schema_version(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ResourceRefError("schema_version must be a positive integer")
    return value


def _ensure_digest(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return validate_digest(value)
    except FingerprintError as exc:
        raise ResourceRefError(f"checksum must be a valid digest: {exc}") from exc


__all__ = ["ResourceRef", "ResourceRefError"]
