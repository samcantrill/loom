"""Artifact reference primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from loom.errors import ArtifactError, ValidationError
from loom.fingerprints import validate_digest
from loom.ids import ArtifactID, ArtifactType, Checksum, CodecKey, Fingerprint, StageID
from loom.serialization import PlainData, ensure_plain_data
from loom.timestamps import parse_timestamp


class ArtifactValidationError(ArtifactError, ValidationError):
    """Error raised when an artifact reference is invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Metadata describing an artifact."""

    artifact_id: ArtifactID
    uri: str
    artifact_type: ArtifactType
    codec_key: CodecKey | None = None
    schema_version: int = 1
    checksum: Checksum | None = None
    fingerprint: Fingerprint | None = None
    producer_stage: StageID | None = None
    created_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise ArtifactValidationError("artifact_id must be a non-empty string")
        if not isinstance(self.uri, str) or not self.uri:
            raise ArtifactValidationError("uri must be a non-empty string")
        if not isinstance(self.artifact_type, str) or not self.artifact_type:
            raise ArtifactValidationError("artifact_type must be a non-empty string")
        if self.codec_key is not None and (not isinstance(self.codec_key, str) or not self.codec_key):
            raise ArtifactValidationError("codec_key must be None or a non-empty string")
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ArtifactValidationError("schema_version must be a positive integer")
        if self.checksum is not None:
            object.__setattr__(self, "checksum", validate_digest(self.checksum))
        if self.fingerprint is not None:
            object.__setattr__(self, "fingerprint", validate_digest(self.fingerprint))
        if self.producer_stage is not None and (not isinstance(self.producer_stage, str) or not self.producer_stage):
            raise ArtifactValidationError("producer_stage must be None or a non-empty string")
        if self.created_at is not None:
            parse_timestamp(self.created_at)
        object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "schema_version": self.schema_version,
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactRef":
        if not isinstance(data, dict):
            raise ArtifactValidationError("ArtifactRef.from_dict expects mapping")
        required = {"artifact_id", "uri", "artifact_type"}
        allowed = required | {
            "codec_key",
            "schema_version",
            "checksum",
            "fingerprint",
            "producer_stage",
            "created_at",
            "metadata",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ArtifactValidationError(f"ArtifactRef.from_dict received unknown fields: {', '.join(sorted(unknown))}")
        missing = required - set(data)
        if missing:
            raise ArtifactValidationError(f"ArtifactRef.from_dict missing required field(s): {', '.join(sorted(missing))}")

        return cls(
            artifact_id=_require_str(data.get("artifact_id"), "artifact_id"),
            uri=_require_str(data.get("uri"), "uri"),
            artifact_type=_require_str(data.get("artifact_type"), "artifact_type"),
            codec_key=_ensure_codec_key(data.get("codec_key")),
            schema_version=_require_schema_version(data.get("schema_version", 1)),
            checksum=_ensure_digest(data.get("checksum")),
            fingerprint=_ensure_digest(data.get("fingerprint")),
            producer_stage=_ensure_stage_id(data.get("producer_stage")),
            created_at=_ensure_str_or_none(data.get("created_at"), "created_at", parse=True),
            metadata=ensure_plain_data(data.get("metadata", {}), path="metadata"),
        )


def _require_str(value: Any, field: str) -> str:
    if value is None:
        raise ArtifactValidationError(f"{field} is required")
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(f"{field} must be a non-empty string")
    return value


def _ensure_str_or_none(value: Any, field: str, *, parse: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArtifactValidationError(f"{field} must be a string")
    if parse and value:
        parse_timestamp(value)
    return value


def _ensure_codec_key(value: Any) -> str | None:
    if value is None:
        return None
    return _require_str(value, "codec_key")


def _ensure_stage_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError("producer_stage must be None or a non-empty string")
    return value


def _require_schema_version(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactValidationError("schema_version must be a positive integer")
    return value


def _ensure_digest(value: Any) -> str | None:
    if value is None:
        return None
    return validate_digest(value)


__all__ = ["ArtifactRef", "ArtifactValidationError"]
