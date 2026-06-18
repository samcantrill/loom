"""Artifact reference primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from loom.errors import ArtifactError, FingerprintError, ValidationError
from loom.fingerprints import validate_digest
from loom.ids import (
    ArtifactID,
    ArtifactType,
    Checksum,
    CodecKey,
    Fingerprint,
    RunURI,
    StageID,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp


class ArtifactValidationError(ArtifactError, ValidationError):
    """Error raised when an artifact reference is invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactAddress:
    """Address of a stored artifact."""

    run_uri: RunURI
    artifact_id: ArtifactID

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise ArtifactValidationError("run_uri must be a non-empty string")
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise ArtifactValidationError("artifact_id must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"run_uri": self.run_uri, "artifact_id": self.artifact_id}

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactAddress":
        if not isinstance(data, dict):
            raise ArtifactValidationError("ArtifactAddress.from_dict expects mapping")
        required = {"run_uri", "artifact_id"}
        unknown = set(data) - required
        if unknown:
            raise ArtifactValidationError(
                f"ArtifactAddress.from_dict received unknown fields: {', '.join(sorted(unknown))}"
            )
        missing = required - set(data)
        if missing:
            raise ArtifactValidationError(
                f"ArtifactAddress.from_dict missing required field(s): {', '.join(sorted(missing))}"
            )
        return cls(
            run_uri=_require_str(data.get("run_uri"), "run_uri"),
            artifact_id=_require_str(data.get("artifact_id"), "artifact_id"),
        )


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
        if self.codec_key is not None and (
            not isinstance(self.codec_key, str) or not self.codec_key
        ):
            raise ArtifactValidationError(
                "codec_key must be None or a non-empty string"
            )
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ArtifactValidationError("schema_version must be a positive integer")
        if self.checksum is not None:
            object.__setattr__(
                self, "checksum", _ensure_digest(self.checksum, "checksum")
            )
        if self.fingerprint is not None:
            object.__setattr__(
                self, "fingerprint", _ensure_digest(self.fingerprint, "fingerprint")
            )
        if self.producer_stage is not None and (
            not isinstance(self.producer_stage, str) or not self.producer_stage
        ):
            raise ArtifactValidationError(
                "producer_stage must be None or a non-empty string"
            )
        if self.created_at is not None:
            _validate_timestamp(self.created_at, "created_at")
        object.__setattr__(
            self, "metadata", freeze_plain_data(self.metadata, path="metadata")
        )

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
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
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
            raise ArtifactValidationError(
                f"ArtifactRef.from_dict received unknown fields: {', '.join(sorted(unknown))}"
            )
        missing = required - set(data)
        if missing:
            raise ArtifactValidationError(
                f"ArtifactRef.from_dict missing required field(s): {', '.join(sorted(missing))}"
            )

        return cls(
            artifact_id=_require_str(data.get("artifact_id"), "artifact_id"),
            uri=_require_str(data.get("uri"), "uri"),
            artifact_type=_require_str(data.get("artifact_type"), "artifact_type"),
            codec_key=_ensure_codec_key(data.get("codec_key")),
            schema_version=_require_artifact_ref_schema_version(
                data.get("schema_version", 1)
            ),
            checksum=_ensure_digest(data.get("checksum"), "checksum"),
            fingerprint=_ensure_digest(data.get("fingerprint"), "fingerprint"),
            producer_stage=_ensure_stage_id(data.get("producer_stage")),
            created_at=_ensure_str_or_none(
                data.get("created_at"), "created_at", parse=True
            ),
            metadata=cast(Mapping[str, PlainData], data.get("metadata", {})),
        )


class ArtifactLocationKind(str, Enum):
    """Canonical artifact location kinds."""

    MANAGED = "managed"
    EXTERNAL_IMMUTABLE = "external_immutable"
    PUBLISHED_IMMUTABLE = "published_immutable"
    STAGING = "staging"
    CACHE = "cache"
    MATERIALIZED = "materialized"


class RetentionMode(str, Enum):
    """Generic retention intent hints for artifact metadata."""

    KEEP = "keep"
    TEMPORARY = "temporary"
    ARCHIVE = "archive"
    EXTERNAL = "external"


class _AuthorityKind(str, Enum):
    AUTHORITATIVE = "authoritative"
    DERIVED = "derived"


class _Immutability(str, Enum):
    DECLARED = "declared"
    VALIDATED = "validated"


class _LookupStatus(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


_DERIVED_LOCATION_KINDS = frozenset(
    {
        ArtifactLocationKind.STAGING,
        ArtifactLocationKind.CACHE,
        ArtifactLocationKind.MATERIALIZED,
    }
)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Plain-data retention hint for artifact metadata."""

    mode: RetentionMode
    schema_version: int = 1
    expires_at: str | None = None
    reason: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "mode", _require_retention_mode(self.mode, "mode"))
        object.__setattr__(
            self,
            "expires_at",
            _ensure_str_or_none(self.expires_at, "expires_at", parse=True),
        )
        object.__setattr__(
            self, "reason", _ensure_non_empty_optional_string(self.reason, "reason")
        )
        object.__setattr__(
            self, "metadata", _freeze_plain_mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "expires_at": self.expires_at,
            "reason": self.reason,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RetentionPolicy":
        if not isinstance(data, dict):
            raise ArtifactValidationError("RetentionPolicy.from_dict expects mapping")
        required = {"schema_version", "mode"}
        optional = {"expires_at", "reason", "metadata"}
        _validate_fields(
            data, required=required, optional=optional, path="RetentionPolicy"
        )
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            mode=cast(Any, data.get("mode")),
            expires_at=_ensure_str_or_none(
                data.get("expires_at"), "expires_at", parse=True
            ),
            reason=_ensure_non_empty_optional_string(data.get("reason"), "reason"),
            metadata=cast(Mapping[str, PlainData], data.get("metadata", {})),
        )


def normalize_retention_policy(value: object) -> RetentionPolicy | None:
    """Normalize artifact retention metadata into a typed policy hint."""

    if value is None:
        return None
    if isinstance(value, RetentionPolicy):
        return value
    if isinstance(value, str):
        return RetentionPolicy(mode=cast(Any, value))
    if isinstance(value, Mapping):
        data = dict(value)
        data.setdefault("schema_version", 1)
        return RetentionPolicy.from_dict(data)
    raise ArtifactValidationError(
        "retention policy must be a RetentionPolicy, mapping, string, or None"
    )


def retention_policy_from_metadata(
    metadata: Mapping[str, PlainData], *, field: str = "retention"
) -> RetentionPolicy | None:
    """Read a typed retention hint from a plain artifact metadata mapping."""

    if not isinstance(metadata, Mapping):
        raise ArtifactValidationError("metadata must be a mapping")
    return normalize_retention_policy(metadata.get(field))


@dataclass(frozen=True, slots=True)
class ArtifactStoreRef:
    """Backend-neutral store reference for artifact summaries."""

    kind: str
    schema_version: int = 1
    key: str | None = None
    uri: str | None = None
    display_uri: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "kind", _require_non_empty_string(self.kind, "kind"))
        object.__setattr__(
            self, "key", _ensure_non_empty_optional_string(self.key, "key")
        )
        object.__setattr__(
            self, "uri", _ensure_non_empty_optional_string(self.uri, "uri")
        )
        object.__setattr__(
            self,
            "display_uri",
            _ensure_non_empty_optional_string(self.display_uri, "display_uri"),
        )
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "key": self.key,
            "uri": self.uri,
            "display_uri": self.display_uri,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactStoreRef":
        if not isinstance(data, dict):
            raise ArtifactValidationError("ArtifactStoreRef.from_dict expects mapping")
        required = {"schema_version", "kind"}
        optional = {"key", "uri", "display_uri", "details"}
        _validate_fields(
            data, required=required, optional=optional, path="ArtifactStoreRef"
        )
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            kind=cast(Any, data.get("kind")),
            key=data.get("key"),
            uri=data.get("uri"),
            display_uri=data.get("display_uri"),
            details=cast(Mapping[str, PlainData], data.get("details", {})),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class ArtifactLocationSummary:
    """Public location summary for catalog/bundle/run-exchange projections."""

    kind: ArtifactLocationKind
    authority: str
    schema_version: int = 1
    uri: str | None = None
    display_uri: str | None = None
    store: ArtifactStoreRef | None = None
    checksum: Checksum | None = None
    fingerprint: Fingerprint | None = None
    size_bytes: int | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "kind", _require_location_kind(self.kind, "kind"))
        object.__setattr__(
            self,
            "authority",
            _require_authority(self.authority, "authority"),
        )
        _validate_authority_for_kind(self.kind, self.authority, "authority")
        object.__setattr__(
            self, "uri", _ensure_non_empty_optional_string(self.uri, "uri")
        )
        object.__setattr__(
            self,
            "display_uri",
            _ensure_non_empty_optional_string(self.display_uri, "display_uri"),
        )
        object.__setattr__(
            self,
            "store",
            _optional_store_ref(self.store, "store"),
        )
        object.__setattr__(self, "checksum", _ensure_digest(self.checksum, "checksum"))
        object.__setattr__(
            self,
            "fingerprint",
            _ensure_digest(self.fingerprint, "fingerprint"),
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "authority": self.authority,
            "uri": self.uri,
            "display_uri": self.display_uri,
            "store": None if self.store is None else self.store.to_summary(),
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "size_bytes": self.size_bytes,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactLocationSummary":
        if not isinstance(data, dict):
            raise ArtifactValidationError(
                "ArtifactLocationSummary.from_dict expects mapping"
            )
        required = {"schema_version", "kind", "authority"}
        optional = {
            "uri",
            "display_uri",
            "store",
            "checksum",
            "fingerprint",
            "size_bytes",
            "details",
        }
        _validate_fields(
            data, required=required, optional=optional, path="ArtifactLocationSummary"
        )
        store_data = data.get("store")
        store = None if store_data is None else ArtifactStoreRef.from_dict(store_data)
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            kind=cast(Any, data.get("kind")),
            authority=cast(str, data.get("authority")),
            uri=data.get("uri"),
            display_uri=data.get("display_uri"),
            store=store,
            checksum=_ensure_digest(data.get("checksum"), "checksum"),
            fingerprint=_ensure_digest(data.get("fingerprint"), "fingerprint"),
            size_bytes=_require_non_negative_int(data.get("size_bytes"), "size_bytes"),
            details=cast(Mapping[str, PlainData], data.get("details", {})),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class ExternalArtifactDeclaration:
    """Backend-neutral immutable declaration of an external artifact."""

    artifact_id: ArtifactID
    uri: str
    artifact_type: ArtifactType
    artifact_schema_version: int
    schema_version: int = 1
    codec_key: CodecKey | None = None
    store: ArtifactStoreRef | None = None
    location: ArtifactLocationSummary | None = None
    checksum: Checksum | None = None
    fingerprint: Fingerprint | None = None
    immutability: str = _Immutability.DECLARED.value
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "artifact_id",
            _require_non_empty_string(self.artifact_id, "artifact_id"),
        )
        object.__setattr__(self, "uri", _require_non_empty_string(self.uri, "uri"))
        object.__setattr__(
            self,
            "artifact_type",
            _require_non_empty_string(self.artifact_type, "artifact_type"),
        )
        object.__setattr__(
            self,
            "artifact_schema_version",
            _require_positive_int(
                self.artifact_schema_version, "artifact_schema_version"
            ),
        )
        object.__setattr__(
            self,
            "codec_key",
            _ensure_non_empty_optional_string(self.codec_key, "codec_key"),
        )
        object.__setattr__(self, "store", _optional_store_ref(self.store, "store"))
        object.__setattr__(
            self,
            "location",
            _optional_location_summary(self.location, "location"),
        )
        object.__setattr__(self, "checksum", _ensure_digest(self.checksum, "checksum"))
        object.__setattr__(
            self,
            "fingerprint",
            _ensure_digest(self.fingerprint, "fingerprint"),
        )
        object.__setattr__(
            self,
            "immutability",
            _require_immutability(self.immutability, "immutability"),
        )
        object.__setattr__(
            self, "metadata", _freeze_plain_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "artifact_schema_version": self.artifact_schema_version,
            "store": None if self.store is None else self.store.to_summary(),
            "location": None if self.location is None else self.location.to_summary(),
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "immutability": self.immutability,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ExternalArtifactDeclaration":
        if not isinstance(data, dict):
            raise ArtifactValidationError(
                "ExternalArtifactDeclaration.from_dict expects mapping"
            )
        required = {
            "schema_version",
            "artifact_id",
            "uri",
            "artifact_type",
            "artifact_schema_version",
            "immutability",
        }
        optional = {
            "codec_key",
            "store",
            "location",
            "checksum",
            "fingerprint",
            "metadata",
            "details",
        }
        _validate_fields(
            data,
            required=required,
            optional=optional,
            path="ExternalArtifactDeclaration",
        )
        store_data = data.get("store")
        location_data = data.get("location")
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            artifact_id=_require_non_empty_string(data["artifact_id"], "artifact_id"),
            uri=_require_non_empty_string(data["uri"], "uri"),
            artifact_type=_require_non_empty_string(
                data["artifact_type"], "artifact_type"
            ),
            codec_key=_ensure_non_empty_optional_string(
                data.get("codec_key"), "codec_key"
            ),
            artifact_schema_version=_require_positive_int(
                data["artifact_schema_version"], "artifact_schema_version"
            ),
            store=None
            if store_data is None
            else ArtifactStoreRef.from_dict(store_data),
            location=None
            if location_data is None
            else ArtifactLocationSummary.from_dict(location_data),
            checksum=_ensure_digest(data.get("checksum"), "checksum"),
            fingerprint=_ensure_digest(data.get("fingerprint"), "fingerprint"),
            immutability=_require_immutability(data["immutability"], "immutability"),
            metadata=cast(Mapping[str, PlainData], data.get("metadata", {})),
            details=cast(Mapping[str, PlainData], data.get("details", {})),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class PublishedArtifactRecord:
    """Published artifact metadata in backend-neutral form."""

    artifact_id: ArtifactID
    uri: str
    artifact_type: ArtifactType
    artifact_schema_version: int
    producer_run_uri: RunURI
    producer_stage: StageID
    producer_artifact_id: ArtifactID
    reuse_key: str
    schema_version: int = 1
    validation_policy: Mapping[str, PlainData] = field(default_factory=dict)
    owner: Mapping[str, PlainData] = field(default_factory=dict)
    retention: Mapping[str, PlainData] = field(default_factory=dict)
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    codec_key: CodecKey | None = None
    store: ArtifactStoreRef | None = None
    location: ArtifactLocationSummary | None = None
    checksum: Checksum | None = None
    fingerprint: Fingerprint | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "artifact_id",
            _require_non_empty_string(self.artifact_id, "artifact_id"),
        )
        object.__setattr__(self, "uri", _require_non_empty_string(self.uri, "uri"))
        object.__setattr__(
            self,
            "artifact_type",
            _require_non_empty_string(self.artifact_type, "artifact_type"),
        )
        object.__setattr__(
            self,
            "artifact_schema_version",
            _require_positive_int(
                self.artifact_schema_version, "artifact_schema_version"
            ),
        )
        object.__setattr__(
            self,
            "producer_run_uri",
            _require_non_empty_string(self.producer_run_uri, "producer_run_uri"),
        )
        object.__setattr__(
            self,
            "producer_stage",
            _require_non_empty_string(self.producer_stage, "producer_stage"),
        )
        object.__setattr__(
            self,
            "producer_artifact_id",
            _require_non_empty_string(
                self.producer_artifact_id, "producer_artifact_id"
            ),
        )
        object.__setattr__(
            self, "reuse_key", _require_non_empty_string(self.reuse_key, "reuse_key")
        )
        object.__setattr__(
            self,
            "validation_policy",
            _freeze_plain_mapping(self.validation_policy, "validation_policy"),
        )
        object.__setattr__(self, "owner", _freeze_plain_mapping(self.owner, "owner"))
        object.__setattr__(
            self, "retention", _freeze_plain_mapping(self.retention, "retention")
        )
        object.__setattr__(
            self, "evidence", _freeze_plain_mapping(self.evidence, "evidence")
        )
        object.__setattr__(
            self,
            "codec_key",
            _ensure_non_empty_optional_string(self.codec_key, "codec_key"),
        )
        object.__setattr__(self, "store", _optional_store_ref(self.store, "store"))
        object.__setattr__(
            self,
            "location",
            _optional_location_summary(self.location, "location"),
        )
        object.__setattr__(
            self,
            "checksum",
            _ensure_digest(self.checksum, "checksum"),
        )
        object.__setattr__(
            self,
            "fingerprint",
            _ensure_digest(self.fingerprint, "fingerprint"),
        )
        object.__setattr__(
            self, "metadata", _freeze_plain_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "artifact_schema_version": self.artifact_schema_version,
            "producer_run_uri": self.producer_run_uri,
            "producer_stage": self.producer_stage,
            "producer_artifact_id": self.producer_artifact_id,
            "reuse_key": self.reuse_key,
            "validation_policy": thaw_plain_data(
                self.validation_policy, path="validation_policy"
            ),
            "owner": thaw_plain_data(self.owner, path="owner"),
            "retention": thaw_plain_data(self.retention, path="retention"),
            "evidence": thaw_plain_data(self.evidence, path="evidence"),
            "store": None if self.store is None else self.store.to_summary(),
            "location": None if self.location is None else self.location.to_summary(),
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PublishedArtifactRecord":
        if not isinstance(data, dict):
            raise ArtifactValidationError(
                "PublishedArtifactRecord.from_dict expects mapping"
            )
        required = {
            "schema_version",
            "artifact_id",
            "uri",
            "artifact_type",
            "artifact_schema_version",
            "producer_run_uri",
            "producer_stage",
            "producer_artifact_id",
            "reuse_key",
            "validation_policy",
            "owner",
            "retention",
            "evidence",
            "metadata",
            "details",
        }
        optional = {
            "codec_key",
            "store",
            "location",
            "checksum",
            "fingerprint",
        }
        _validate_fields(
            data,
            required=required,
            optional=optional,
            path="PublishedArtifactRecord",
        )
        store_data = data.get("store")
        location_data = data.get("location")
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            artifact_id=_require_non_empty_string(data["artifact_id"], "artifact_id"),
            uri=_require_non_empty_string(data["uri"], "uri"),
            artifact_type=_require_non_empty_string(
                data["artifact_type"], "artifact_type"
            ),
            codec_key=_ensure_non_empty_optional_string(
                data.get("codec_key"), "codec_key"
            ),
            artifact_schema_version=_require_positive_int(
                data["artifact_schema_version"], "artifact_schema_version"
            ),
            producer_run_uri=_require_non_empty_string(
                data["producer_run_uri"], "producer_run_uri"
            ),
            producer_stage=_require_non_empty_string(
                data["producer_stage"], "producer_stage"
            ),
            producer_artifact_id=_require_non_empty_string(
                data["producer_artifact_id"], "producer_artifact_id"
            ),
            reuse_key=_require_non_empty_string(data["reuse_key"], "reuse_key"),
            validation_policy=cast(Mapping[str, PlainData], data["validation_policy"]),
            owner=cast(Mapping[str, PlainData], data["owner"]),
            retention=cast(Mapping[str, PlainData], data["retention"]),
            evidence=cast(Mapping[str, PlainData], data["evidence"]),
            store=None
            if store_data is None
            else ArtifactStoreRef.from_dict(store_data),
            location=None
            if location_data is None
            else ArtifactLocationSummary.from_dict(location_data),
            checksum=_ensure_digest(data.get("checksum"), "checksum"),
            fingerprint=_ensure_digest(data.get("fingerprint"), "fingerprint"),
            metadata=cast(Mapping[str, PlainData], data["metadata"]),
            details=cast(Mapping[str, PlainData], data["details"]),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class ImmutableArtifactLookupRequest:
    """Request details for lookup of an immutable artifact."""

    reuse_key: str
    artifact_type: ArtifactType
    artifact_schema_version: int
    schema_version: int = 1
    validation_policy: Mapping[str, PlainData] = field(default_factory=dict)
    store: ArtifactStoreRef | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "reuse_key", _require_non_empty_string(self.reuse_key, "reuse_key")
        )
        object.__setattr__(
            self,
            "artifact_type",
            _require_non_empty_string(self.artifact_type, "artifact_type"),
        )
        object.__setattr__(
            self,
            "artifact_schema_version",
            _require_positive_int(
                self.artifact_schema_version, "artifact_schema_version"
            ),
        )
        object.__setattr__(
            self,
            "validation_policy",
            _freeze_plain_mapping(self.validation_policy, "validation_policy"),
        )
        object.__setattr__(self, "store", _optional_store_ref(self.store, "store"))
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reuse_key": self.reuse_key,
            "artifact_type": self.artifact_type,
            "artifact_schema_version": self.artifact_schema_version,
            "validation_policy": thaw_plain_data(
                self.validation_policy, path="validation_policy"
            ),
            "store": None if self.store is None else self.store.to_summary(),
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ImmutableArtifactLookupRequest":
        if not isinstance(data, dict):
            raise ArtifactValidationError(
                "ImmutableArtifactLookupRequest.from_dict expects mapping"
            )
        required = {
            "schema_version",
            "reuse_key",
            "artifact_type",
            "artifact_schema_version",
            "validation_policy",
            "store",
            "details",
        }
        _validate_fields(
            data,
            required=required,
            optional=set(),
            path="ImmutableArtifactLookupRequest",
        )
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            reuse_key=_require_non_empty_string(data["reuse_key"], "reuse_key"),
            artifact_type=_require_non_empty_string(
                data["artifact_type"], "artifact_type"
            ),
            artifact_schema_version=_require_positive_int(
                data["artifact_schema_version"], "artifact_schema_version"
            ),
            validation_policy=cast(Mapping[str, PlainData], data["validation_policy"]),
            store=_optional_store_ref(data["store"], "store"),
            details=cast(Mapping[str, PlainData], data["details"]),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class ImmutableArtifactLookupResult:
    """Result of immutable artifact lookup by key."""

    status: str
    request: ImmutableArtifactLookupRequest
    schema_version: int = 1
    published: PublishedArtifactRecord | None = None
    location: ArtifactLocationSummary | None = None
    diagnostics: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_record_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "status", _require_lookup_status(self.status, "status")
        )
        object.__setattr__(
            self, "request", _required_lookup_request(self.request, "request")
        )
        object.__setattr__(
            self, "published", _optional_published_record(self.published, "published")
        )
        object.__setattr__(
            self, "location", _optional_location_summary(self.location, "location")
        )
        object.__setattr__(
            self,
            "diagnostics",
            _freeze_plain_mapping(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self, "details", _freeze_plain_mapping(self.details, "details")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "request": self.request.to_summary(),
            "published": None
            if self.published is None
            else self.published.to_summary(),
            "location": None if self.location is None else self.location.to_summary(),
            "diagnostics": thaw_plain_data(self.diagnostics, path="diagnostics"),
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ImmutableArtifactLookupResult":
        if not isinstance(data, dict):
            raise ArtifactValidationError(
                "ImmutableArtifactLookupResult.from_dict expects mapping"
            )
        required = {
            "schema_version",
            "status",
            "request",
            "published",
            "location",
            "diagnostics",
            "details",
        }
        _validate_fields(
            data,
            required=required,
            optional=set(),
            path="ImmutableArtifactLookupResult",
        )
        published_data = data.get("published")
        location_data = data.get("location")
        request_data = data.get("request")
        if request_data is None:
            raise ArtifactValidationError("request is required")
        return cls(
            schema_version=_require_record_schema_version(
                data["schema_version"], "schema_version"
            ),
            status=_require_lookup_status(data["status"], "status"),
            request=ImmutableArtifactLookupRequest.from_dict(request_data),
            published=None
            if published_data is None
            else PublishedArtifactRecord.from_dict(published_data),
            location=None
            if location_data is None
            else ArtifactLocationSummary.from_dict(location_data),
            diagnostics=cast(Mapping[str, PlainData], data["diagnostics"]),
            details=cast(Mapping[str, PlainData], data["details"]),
        )

    def to_summary(self) -> dict[str, Any]:
        return self.to_dict()


def _validate_fields(
    data: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    missing = required - set(data)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ArtifactValidationError(
            f"{path}: missing required field(s): {missing_text}"
        )
    unknown = set(data) - required - optional
    if unknown:
        unknown_text = ", ".join(sorted(unknown))
        raise ArtifactValidationError(f"{path}: unknown field(s): {unknown_text}")


def _require_str(value: Any, field: str) -> str:
    if value is None:
        raise ArtifactValidationError(f"{field} is required")
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(f"{field} must be a non-empty string")
    return value


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(f"{field} must be a non-empty string")
    return value


def _require_non_empty_optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field)


def _ensure_non_empty_optional_string(value: Any, field: str) -> str | None:
    return _require_non_empty_optional_string(value, field)


def _ensure_str_or_none(value: Any, field: str, *, parse: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArtifactValidationError(f"{field} must be a string")
    if parse and value:
        _validate_timestamp(value, field)
    return value


def _ensure_codec_key(value: Any) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, "codec_key")


def _ensure_stage_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(
            "producer_stage must be None or a non-empty string"
        )
    return value


def _require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactValidationError(f"{field} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactValidationError(f"{field} must be a non-negative integer")
    return value


def _require_artifact_ref_schema_version(
    value: Any, field: str = "schema_version"
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactValidationError(f"{field} must be a positive integer")
    return value


def _require_record_schema_version(value: Any, field: str = "schema_version") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != 1:
        raise ArtifactValidationError(f"{field} must be 1")
    return value


def _ensure_digest(value: Any, field: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_digest(value)
    except FingerprintError as exc:
        raise ArtifactValidationError(f"{field} must be a valid digest: {exc}") from exc


def _freeze_plain_mapping(value: Any, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{field} must be a mapping")
    try:
        frozen = freeze_plain_data(value, path=field)
    except Exception as exc:
        raise ArtifactValidationError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise ArtifactValidationError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _validate_timestamp(value: str, field: str) -> None:
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise ArtifactValidationError(
            f"{field} must be a valid UTC timestamp: {exc}"
        ) from exc


def _require_location_kind(value: Any, field: str) -> ArtifactLocationKind:
    if not isinstance(value, str):
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_artifact_location_kind_values())}"
        )
    if value not in _artifact_location_kind_values():
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_artifact_location_kind_values())}"
        )
    return ArtifactLocationKind(value)


def _artifact_location_kind_values() -> tuple[str, ...]:
    return tuple(kind.value for kind in ArtifactLocationKind)


def _require_authority(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_authority_values())}"
        )
    if value not in _authority_values():
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_authority_values())}"
        )
    return value


def _authority_values() -> tuple[str, ...]:
    return tuple(kind.value for kind in _AuthorityKind)


def _validate_authority_for_kind(
    kind: ArtifactLocationKind, authority: str, field: str
) -> None:
    if authority == _AuthorityKind.DERIVED.value and kind in _DERIVED_LOCATION_KINDS:
        return
    if kind in _DERIVED_LOCATION_KINDS and authority != _AuthorityKind.DERIVED.value:
        raise ArtifactValidationError(
            f"{field} must be {_AuthorityKind.DERIVED.value} when kind is {kind.value}"
        )
    if (
        authority == _AuthorityKind.AUTHORITATIVE.value
        and kind not in _DERIVED_LOCATION_KINDS
    ):
        return
    if authority not in _authority_values():
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_authority_values())}"
        )


def _require_immutability(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_immutability_values())}"
        )
    if value not in _immutability_values():
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_immutability_values())}"
        )
    return value


def _immutability_values() -> tuple[str, ...]:
    return tuple(kind.value for kind in _Immutability)


def _require_lookup_status(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_lookup_status_values())}"
        )
    if value not in _lookup_status_values():
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_lookup_status_values())}"
        )
    return value


def _lookup_status_values() -> tuple[str, ...]:
    return tuple(kind.value for kind in _LookupStatus)


def _require_retention_mode(value: Any, field: str) -> RetentionMode:
    if isinstance(value, RetentionMode):
        return value
    if not isinstance(value, str):
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_retention_mode_values())}"
        )
    try:
        return RetentionMode(value)
    except ValueError as exc:
        raise ArtifactValidationError(
            f"{field} must be one of: {', '.join(_retention_mode_values())}"
        ) from exc


def _retention_mode_values() -> tuple[str, ...]:
    return tuple(mode.value for mode in RetentionMode)


def _optional_store_ref(value: Any, field: str) -> ArtifactStoreRef | None:
    if value is None:
        return None
    return _required_store_ref(value, field)


def _required_store_ref(value: Any, field: str) -> ArtifactStoreRef:
    if isinstance(value, ArtifactStoreRef):
        return value
    if isinstance(value, dict):
        return ArtifactStoreRef.from_dict(value)
    raise ArtifactValidationError(f"{field} must be an ArtifactStoreRef or None")


def _optional_location_summary(
    value: Any, field: str
) -> ArtifactLocationSummary | None:
    if value is None:
        return None
    if not isinstance(value, ArtifactLocationSummary):
        raise ArtifactValidationError(
            f"{field} must be an ArtifactLocationSummary or None"
        )
    return value


def _optional_published_record(
    value: Any, field: str
) -> PublishedArtifactRecord | None:
    if value is None:
        return None
    if not isinstance(value, PublishedArtifactRecord):
        raise ArtifactValidationError(
            f"{field} must be a PublishedArtifactRecord or None"
        )
    return value


def _required_lookup_request(
    value: Any,
    field: str,
) -> ImmutableArtifactLookupRequest:
    if not isinstance(value, ImmutableArtifactLookupRequest):
        raise ArtifactValidationError(
            f"{field} must be an ImmutableArtifactLookupRequest"
        )
    return value


__all__ = [
    "ArtifactAddress",
    "ArtifactRef",
    "ArtifactValidationError",
    "ArtifactLocationKind",
    "RetentionMode",
    "RetentionPolicy",
    "normalize_retention_policy",
    "retention_policy_from_metadata",
    "ArtifactStoreRef",
    "ArtifactLocationSummary",
    "ExternalArtifactDeclaration",
    "PublishedArtifactRecord",
    "ImmutableArtifactLookupRequest",
    "ImmutableArtifactLookupResult",
]
