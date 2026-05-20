"""Configuration artifact contracts for composition metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, cast

from .plain import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data, to_plain_data

from .errors import ConfigErrorContext, ConfigProvenanceError

SCHEMA_VERSION = 1
_SourceArtifactKind: TypeAlias = Literal["base", "overlay", "include", "recipe"]
_SOURCE_ARTIFACT_KINDS = frozenset({"base", "overlay", "include", "recipe"})
_RawSourceSnapshotAvailability: TypeAlias = Literal["disabled", "available", "unavailable"]
_RAW_SOURCE_SNAPSHOT_ENCODINGS = frozenset({"utf-8"})


@dataclass(frozen=True, slots=True)
class RawSourceSnapshotPayload:
    """A caller-owned raw snapshot payload for reconstructed authored sources."""

    payload_id: str
    content: str
    content_digest: str
    size_bytes: int
    encoding: str = "utf-8"
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.payload_id, str) or not self.payload_id:
            raise ConfigProvenanceError("payload_id must be a non-empty string")
        if not isinstance(self.content, str):
            raise ConfigProvenanceError("content must be a string")
        if not isinstance(self.content_digest, str) or not self.content_digest:
            raise ConfigProvenanceError("content_digest must be a non-empty string")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid size_bytes: {self.size_bytes!r}")
        if self.encoding not in _RAW_SOURCE_SNAPSHOT_ENCODINGS:
            raise ConfigProvenanceError("encoding must be utf-8")
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="RawSourceSnapshotPayload.metadata")
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("RawSourceSnapshotPayload metadata must be plain data") from exc
        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "payload_id": self.payload_id,
            "content": self.content,
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
            "encoding": self.encoding,
            "metadata": thaw_plain_data(self.metadata, path="RawSourceSnapshotPayload.metadata"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RawSourceSnapshotPayload":
        payload = ensure_plain_data(value, path="RawSourceSnapshotPayload")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid snapshot payload; expected a mapping")

        payload_keys = set(payload)
        allowed_keys = {
            "payload_id",
            "content",
            "content_digest",
            "size_bytes",
            "encoding",
            "metadata",
        }
        unknown = payload_keys - allowed_keys
        if unknown:
            raise ConfigProvenanceError(
                "RawSourceSnapshotPayload.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        payload_id = payload.get("payload_id")
        content = payload.get("content")
        content_digest = payload.get("content_digest")
        size_bytes = payload.get("size_bytes")
        encoding = payload.get("encoding", "utf-8")
        metadata = payload.get("metadata", {})

        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid size_bytes: {size_bytes!r}")
        if not isinstance(metadata, Mapping):
            raise ConfigProvenanceError("RawSourceSnapshotPayload metadata must be a mapping")

        return cls(
            payload_id=cast(str, payload_id),
            content=cast(str, content),
            content_digest=cast(str, content_digest),
            size_bytes=size_bytes,
            encoding=cast(str, encoding),
            metadata=cast(dict[str, PlainData], metadata),
        )


@dataclass(frozen=True, slots=True)
class RawSourceSnapshotReference:
    """Availability record for one source candidate in a snapshot bundle."""

    kind: _SourceArtifactKind
    order: int
    path: str
    content_digest: str
    size_bytes: int
    availability: _RawSourceSnapshotAvailability
    payload_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in _SOURCE_ARTIFACT_KINDS:
            raise ConfigProvenanceError(f"Invalid source kind: {self.kind!r}")
        if not isinstance(self.order, int) or isinstance(self.order, bool) or self.order < 0:
            raise ConfigProvenanceError(f"Invalid reference order: {self.order!r}")
        if not isinstance(self.path, str) or not self.path:
            raise ConfigProvenanceError(f"Invalid reference path: {self.path!r}")
        if not isinstance(self.content_digest, str) or not self.content_digest:
            raise ConfigProvenanceError(f"Invalid reference content_digest: {self.content_digest!r}")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid reference size_bytes: {self.size_bytes!r}")
        if self.availability not in {"disabled", "available", "unavailable"}:
            raise ConfigProvenanceError(f"Invalid availability: {self.availability!r}")
        if self.payload_id is not None and (not isinstance(self.payload_id, str) or not self.payload_id):
            raise ConfigProvenanceError("payload_id must be a non-empty string when present")
        if not isinstance(self.reason, str) or not self.reason:
            raise ConfigProvenanceError("reason must be a non-empty string")
        if self.availability == "disabled":
            if self.payload_id is not None:
                raise ConfigProvenanceError("disabled snapshot references must not include payload_id")
            if self.reason != "not_requested":
                raise ConfigProvenanceError("disabled snapshot references must use reason not_requested")
        elif self.availability == "available":
            if self.payload_id is None:
                raise ConfigProvenanceError("available snapshot references must include payload_id")
        elif self.payload_id is not None:
            raise ConfigProvenanceError("unavailable snapshot references must not include payload_id")

    def to_dict(self) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "kind": self.kind,
            "order": self.order,
            "path": self.path,
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
            "availability": self.availability,
            "payload_id": self.payload_id,
            "reason": self.reason,
        }
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RawSourceSnapshotReference":
        payload = ensure_plain_data(value, path="RawSourceSnapshotReference")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid snapshot reference; expected a mapping")

        payload_keys = set(payload)
        allowed_keys = {
            "kind",
            "order",
            "path",
            "content_digest",
            "size_bytes",
            "availability",
            "payload_id",
            "reason",
        }
        unknown = payload_keys - allowed_keys
        if unknown:
            raise ConfigProvenanceError(
                "RawSourceSnapshotReference.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        kind = payload.get("kind")
        order = payload.get("order")
        path = payload.get("path")
        content_digest = payload.get("content_digest")
        size_bytes = payload.get("size_bytes")
        availability = payload.get("availability")
        payload_id = payload.get("payload_id")
        reason = payload.get("reason")

        if not isinstance(reason, str) or not reason:
            raise ConfigProvenanceError("reason must be a non-empty string")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid size_bytes: {size_bytes!r}")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            raise ConfigProvenanceError(f"Invalid order: {order!r}")
        if not isinstance(path, str) or not path:
            raise ConfigProvenanceError(f"Invalid path: {path!r}")
        if not isinstance(content_digest, str) or not content_digest:
            raise ConfigProvenanceError(f"Invalid content_digest: {content_digest!r}")
        if payload_id is not None and (not isinstance(payload_id, str) or not payload_id):
            raise ConfigProvenanceError("payload_id must be a non-empty string when present")

        return cls(
            kind=cast(_SourceArtifactKind, kind),
            order=order,
            path=path,
            content_digest=content_digest,
            size_bytes=size_bytes,
            availability=cast(_RawSourceSnapshotAvailability, availability),
            payload_id=cast(str | None, payload_id),
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class RawSourceSnapshotBundle:
    """Raw snapshot contract returned for compose opt-in workflows."""

    schema_version: int
    enabled: bool
    payloads: tuple[RawSourceSnapshotPayload, ...]
    references: tuple[RawSourceSnapshotReference, ...]
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise ConfigProvenanceError("schema_version must be a positive integer")
        if not isinstance(self.enabled, bool):
            raise ConfigProvenanceError("enabled must be a boolean")
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="RawSourceSnapshotBundle.metadata")
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("RawSourceSnapshotBundle metadata must be plain data") from exc

        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))

        frozen_payloads = tuple(self.payloads)
        frozen_references = tuple(self.references)
        for index, payload in enumerate(frozen_payloads):
            if not isinstance(payload, RawSourceSnapshotPayload):
                raise ConfigProvenanceError(f"payloads[{index}] must be RawSourceSnapshotPayload")
        for index, reference in enumerate(frozen_references):
            if not isinstance(reference, RawSourceSnapshotReference):
                raise ConfigProvenanceError(f"references[{index}] must be RawSourceSnapshotReference")
        object.__setattr__(self, "payloads", frozen_payloads)
        object.__setattr__(self, "references", frozen_references)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "enabled": self.enabled,
            "payloads": [payload.to_dict() for payload in self.payloads],
            "references": [reference.to_dict() for reference in self.references],
            "metadata": thaw_plain_data(self.metadata, path="RawSourceSnapshotBundle.metadata"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RawSourceSnapshotBundle":
        payload = ensure_plain_data(value, path="RawSourceSnapshotBundle")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid snapshot bundle; expected a mapping")

        payload_keys = set(payload)
        allowed_keys = {"schema_version", "enabled", "payloads", "references", "metadata"}
        unknown = payload_keys - allowed_keys
        if unknown:
            raise ConfigProvenanceError(
                "RawSourceSnapshotBundle.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        schema_version = payload.get("schema_version")
        enabled = payload.get("enabled")
        payloads = payload.get("payloads", ())
        references = payload.get("references", ())
        metadata = payload.get("metadata", {})

        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise ConfigProvenanceError(f"Invalid schema_version: {schema_version!r}")
        if not isinstance(enabled, bool):
            raise ConfigProvenanceError("enabled must be a boolean")
        if not isinstance(payloads, Sequence) or isinstance(payloads, (bytes, str, Mapping)):
            raise ConfigProvenanceError("payloads must be a sequence")
        if not isinstance(references, Sequence) or isinstance(references, (bytes, str, Mapping)):
            raise ConfigProvenanceError("references must be a sequence")
        if not isinstance(metadata, Mapping):
            raise ConfigProvenanceError("metadata must be a mapping")

        return cls(
            schema_version=schema_version,
            enabled=enabled,
            payloads=tuple(RawSourceSnapshotPayload.from_dict(cast(Mapping[str, Any], item)) for item in payloads),
            references=tuple(RawSourceSnapshotReference.from_dict(cast(Mapping[str, Any], item)) for item in references),
            metadata=cast(dict[str, PlainData], metadata),
        )


@dataclass(frozen=True, slots=True)
class SourceArtifactRecord:
    """Metadata describing one composed source artifact input.

    This is a phase-1 skeleton contract only. It stores metadata and fingerprint
    identity for provenance-style tracking, not raw file contents or resolver
    runtime outputs.
    """

    schema_version: int
    kind: _SourceArtifactKind
    path: str
    order: int
    content_digest: str
    size_bytes: int
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise _artifact_error(
                "schema_version must be a positive integer",
                code="invalid_source_artifact_schema_version",
                path="SourceArtifactRecord.schema_version",
                stage="artifact_construction",
                expected="positive integer",
                actual=self.schema_version,
            )
        if self.kind not in _SOURCE_ARTIFACT_KINDS:
            raise _artifact_error(
                f"Invalid source artifact kind: {self.kind!r}",
                code="invalid_source_artifact_kind",
                path="SourceArtifactRecord.kind",
                stage="artifact_construction",
                expected="base, overlay, include, or recipe",
                actual=self.kind,
            )
        if not isinstance(self.path, str) or not self.path:
            raise _artifact_error(
                f"Invalid source artifact path: {self.path!r}",
                code="invalid_source_artifact_path",
                path="SourceArtifactRecord.path",
                stage="artifact_construction",
                expected="non-empty string",
                actual=self.path,
            )
        if not isinstance(self.order, int) or self.order < 0:
            raise _artifact_error(
                f"Invalid source artifact order: {self.order!r}",
                code="invalid_source_artifact_order",
                path="SourceArtifactRecord.order",
                stage="artifact_construction",
                expected="non-negative integer",
                actual=self.order,
            )
        if not isinstance(self.content_digest, str) or not self.content_digest:
            raise _artifact_error(
                f"Invalid source artifact digest: {self.content_digest!r}",
                code="invalid_source_artifact_digest",
                path="SourceArtifactRecord.content_digest",
                stage="artifact_construction",
                expected="non-empty string",
                actual=self.content_digest,
            )
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise _artifact_error(
                f"Invalid source artifact size: {self.size_bytes!r}",
                code="invalid_source_artifact_size",
                path="SourceArtifactRecord.size_bytes",
                stage="artifact_construction",
                expected="non-negative integer",
                actual=self.size_bytes,
            )
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="SourceArtifactRecord.metadata")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "source artifact metadata must be plain data",
                code="source_artifact_metadata_not_plain_data",
                path="SourceArtifactRecord.metadata",
                stage="artifact_construction",
                expected="plain-data mapping",
                actual=self.metadata,
                details={"exception_type": type(exc).__name__},
            ) from exc
        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "path": self.path,
            "order": self.order,
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
            "metadata": thaw_plain_data(self.metadata, path="SourceArtifactRecord.metadata"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceArtifactRecord":
        try:
            payload = ensure_plain_data(value, path="SourceArtifactRecord")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "Invalid source artifact data",
                code="source_artifact_invalid_plain_data",
                path="SourceArtifactRecord",
                stage="artifact_from_dict",
                expected="plain-data mapping",
                actual=value,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(payload, Mapping):
            raise _artifact_error(
                "Invalid source artifact payload; expected a mapping",
                code="source_artifact_payload_not_mapping",
                path="SourceArtifactRecord",
                stage="artifact_from_dict",
                expected="mapping",
                actual=payload,
            )

        payload_keys = set(payload)
        allowed_keys = {
            "schema_version",
            "kind",
            "path",
            "order",
            "content_digest",
            "size_bytes",
            "metadata",
        }
        unknown = payload_keys - allowed_keys
        if unknown:
            raise _artifact_error(
                "SourceArtifactRecord.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}",
                code="source_artifact_unknown_fields",
                path="SourceArtifactRecord",
                stage="artifact_from_dict",
                expected="known SourceArtifactRecord fields",
                actual="unknown fields",
                details={"unknown_fields": sorted(unknown)},
            )

        schema_version = payload.get("schema_version")
        kind = payload.get("kind")
        path = payload.get("path")
        order = payload.get("order")
        content_digest = payload.get("content_digest")
        size_bytes = payload.get("size_bytes")
        metadata = payload.get("metadata", {})
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise _artifact_error(
                f"Invalid schema_version: {schema_version!r}",
                code="invalid_source_artifact_schema_version",
                path="SourceArtifactRecord.schema_version",
                stage="artifact_from_dict",
                expected="positive integer",
                actual=schema_version,
            )
        if not isinstance(order, int) or order < 0:
            raise _artifact_error(
                f"Invalid order: {order!r}",
                code="invalid_source_artifact_order",
                path="SourceArtifactRecord.order",
                stage="artifact_from_dict",
                expected="non-negative integer",
                actual=order,
            )
        if not isinstance(path, str) or not path:
            raise _artifact_error(
                f"Invalid path: {path!r}",
                code="invalid_source_artifact_path",
                path="SourceArtifactRecord.path",
                stage="artifact_from_dict",
                expected="non-empty string",
                actual=path,
            )
        if kind not in _SOURCE_ARTIFACT_KINDS:
            raise _artifact_error(
                f"Invalid source artifact kind: {kind!r}",
                code="invalid_source_artifact_kind",
                path="SourceArtifactRecord.kind",
                stage="artifact_from_dict",
                expected="base, overlay, include, or recipe",
                actual=kind,
            )
        if not isinstance(content_digest, str) or not content_digest:
            raise _artifact_error(
                f"Invalid content_digest: {content_digest!r}",
                code="invalid_source_artifact_digest",
                path="SourceArtifactRecord.content_digest",
                stage="artifact_from_dict",
                expected="non-empty string",
                actual=content_digest,
            )
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise _artifact_error(
                f"Invalid size_bytes: {size_bytes!r}",
                code="invalid_source_artifact_size",
                path="SourceArtifactRecord.size_bytes",
                stage="artifact_from_dict",
                expected="non-negative integer",
                actual=size_bytes,
            )

        if not isinstance(metadata, Mapping):
            raise _artifact_error(
                "SourceArtifactRecord metadata must be a mapping",
                code="source_artifact_metadata_not_mapping",
                path="SourceArtifactRecord.metadata",
                stage="artifact_from_dict",
                expected="mapping",
                actual=metadata,
            )
        return cls(
            schema_version=schema_version,
            kind=cast(_SourceArtifactKind, kind),
            path=path,
            order=order,
            content_digest=content_digest,
            size_bytes=size_bytes,
            metadata=cast(dict[str, PlainData], metadata),
        )


@dataclass(frozen=True, slots=True)
class ConfigFingerprintRecord:
    """Record describing an artifact-safe configuration fingerprint fragment."""

    schema_version: int
    digest: str
    label: str = "resolved"
    algorithm: str = "sha256"
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise _artifact_error(
                "schema_version must be a positive integer",
                code="invalid_config_fingerprint_schema_version",
                path="ConfigFingerprintRecord.schema_version",
                stage="artifact_construction",
                expected="positive integer",
                actual=self.schema_version,
            )
        if not isinstance(self.digest, str) or not self.digest:
            raise _artifact_error(
                "digest must be a non-empty string",
                code="invalid_config_fingerprint_digest",
                path="ConfigFingerprintRecord.digest",
                stage="artifact_construction",
                expected="non-empty string",
                actual=self.digest,
            )
        if not isinstance(self.label, str) or not self.label:
            raise _artifact_error(
                "label must be a non-empty string",
                code="invalid_config_fingerprint_label",
                path="ConfigFingerprintRecord.label",
                stage="artifact_construction",
                expected="non-empty string",
                actual=self.label,
            )
        if not isinstance(self.algorithm, str) or not self.algorithm:
            raise _artifact_error(
                "algorithm must be a non-empty string",
                code="invalid_config_fingerprint_algorithm",
                path="ConfigFingerprintRecord.algorithm",
                stage="artifact_construction",
                expected="non-empty string",
                actual=self.algorithm,
            )
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="ConfigFingerprintRecord.metadata")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "ConfigFingerprintRecord metadata must be plain data",
                code="config_fingerprint_metadata_not_plain_data",
                path="ConfigFingerprintRecord.metadata",
                stage="artifact_construction",
                expected="plain-data mapping",
                actual=self.metadata,
                details={"exception_type": type(exc).__name__},
            ) from exc
        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "label": self.label,
            "algorithm": self.algorithm,
            "metadata": thaw_plain_data(self.metadata, path="ConfigFingerprintRecord.metadata"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigFingerprintRecord":
        try:
            payload = ensure_plain_data(value, path="ConfigFingerprintRecord")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "Invalid fingerprint data",
                code="config_fingerprint_invalid_plain_data",
                path="ConfigFingerprintRecord",
                stage="artifact_from_dict",
                expected="plain-data mapping",
                actual=value,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(payload, Mapping):
            raise _artifact_error(
                "Invalid fingerprint payload; expected a mapping",
                code="config_fingerprint_payload_not_mapping",
                path="ConfigFingerprintRecord",
                stage="artifact_from_dict",
                expected="mapping",
                actual=payload,
            )

        payload_keys = set(payload)
        allowed_keys = {"schema_version", "digest", "label", "algorithm", "metadata"}
        unknown = payload_keys - allowed_keys
        if unknown:
            raise _artifact_error(
                "ConfigFingerprintRecord.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}",
                code="config_fingerprint_unknown_fields",
                path="ConfigFingerprintRecord",
                stage="artifact_from_dict",
                expected="known ConfigFingerprintRecord fields",
                actual="unknown fields",
                details={"unknown_fields": sorted(unknown)},
            )

        schema_version = payload.get("schema_version")
        digest = payload.get("digest")
        label = payload.get("label", "resolved")
        algorithm = payload.get("algorithm", "sha256")
        metadata = payload.get("metadata", {})
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise _artifact_error(
                f"Invalid schema_version: {schema_version!r}",
                code="invalid_config_fingerprint_schema_version",
                path="ConfigFingerprintRecord.schema_version",
                stage="artifact_from_dict",
                expected="positive integer",
                actual=schema_version,
            )
        if not isinstance(digest, str) or not digest:
            raise _artifact_error(
                f"Invalid digest: {digest!r}",
                code="invalid_config_fingerprint_digest",
                path="ConfigFingerprintRecord.digest",
                stage="artifact_from_dict",
                expected="non-empty string",
                actual=digest,
            )
        if not isinstance(label, str) or not label:
            raise _artifact_error(
                f"Invalid label: {label!r}",
                code="invalid_config_fingerprint_label",
                path="ConfigFingerprintRecord.label",
                stage="artifact_from_dict",
                expected="non-empty string",
                actual=label,
            )
        if not isinstance(algorithm, str) or not algorithm:
            raise _artifact_error(
                f"Invalid algorithm: {algorithm!r}",
                code="invalid_config_fingerprint_algorithm",
                path="ConfigFingerprintRecord.algorithm",
                stage="artifact_from_dict",
                expected="non-empty string",
                actual=algorithm,
            )
        if not isinstance(metadata, Mapping):
            raise _artifact_error(
                "ConfigFingerprintRecord metadata must be a mapping",
                code="config_fingerprint_metadata_not_mapping",
                path="ConfigFingerprintRecord.metadata",
                stage="artifact_from_dict",
                expected="mapping",
                actual=metadata,
            )

        return cls(
            schema_version=schema_version,
            digest=digest,
            label=label,
            algorithm=algorithm,
            metadata=cast(dict[str, PlainData], metadata),
        )


@dataclass(frozen=True, slots=True)
class CompositionManifest:
    """Top-level composition artifact contract for persisted config provenance.

    This is an artifact contract only and must not be treated as a pipeline
    runtime API.
    """

    schema_version: int
    source_artifacts: tuple[SourceArtifactRecord, ...] = ()
    fingerprint_records: tuple[ConfigFingerprintRecord, ...] = ()
    recipe_manifest: tuple[Mapping[str, PlainData], ...] = ()
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise _artifact_error(
                "schema_version must be a positive integer",
                code="invalid_composition_manifest_schema_version",
                path="CompositionManifest.schema_version",
                stage="manifest_construction",
                expected="positive integer",
                actual=self.schema_version,
            )
        try:
            frozen_sources = tuple(self.source_artifacts)
            frozen_fingerprints = tuple(self.fingerprint_records)
            frozen_metadata = freeze_plain_data(self.metadata, path="CompositionManifest.metadata")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "CompositionManifest fields must be plain-data-compatible",
                code="composition_manifest_fields_not_plain_data",
                path="CompositionManifest",
                stage="manifest_construction",
                expected="plain-data-compatible fields",
                actual=self.metadata,
                details={"exception_type": type(exc).__name__},
            ) from exc

        try:
            normalized_recipe_manifest = _to_recipe_manifest_payload(tuple(self.recipe_manifest))
            frozen_recipe_manifest = tuple(
                cast(
                    Mapping[str, PlainData],
                    freeze_plain_data(record, path=f"CompositionManifest.recipe_manifest[{index}]"),
                )
                for index, record in enumerate(normalized_recipe_manifest)
            )
        except ConfigProvenanceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "CompositionManifest recipe_manifest must be plain data",
                code="composition_manifest_recipe_manifest_not_plain_data",
                path="CompositionManifest.recipe_manifest",
                stage="manifest_construction",
                expected="plain-data sequence",
                actual=self.recipe_manifest,
                details={"exception_type": type(exc).__name__},
            ) from exc

        object.__setattr__(self, "source_artifacts", frozen_sources)
        object.__setattr__(self, "fingerprint_records", frozen_fingerprints)
        object.__setattr__(self, "recipe_manifest", frozen_recipe_manifest)
        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))
        for index, source_artifact in enumerate(self.source_artifacts):
            if not isinstance(source_artifact, SourceArtifactRecord):
                raise _artifact_error(
                    f"source_artifacts[{index}] must be SourceArtifactRecord",
                    code="composition_manifest_invalid_source_artifact",
                    path=f"CompositionManifest.source_artifacts[{index}]",
                    stage="manifest_construction",
                    expected="SourceArtifactRecord",
                    actual=source_artifact,
                )
        for index, fingerprint_record in enumerate(self.fingerprint_records):
            if not isinstance(fingerprint_record, ConfigFingerprintRecord):
                raise _artifact_error(
                    f"fingerprint_records[{index}] must be ConfigFingerprintRecord",
                    code="composition_manifest_invalid_fingerprint_record",
                    path=f"CompositionManifest.fingerprint_records[{index}]",
                    stage="manifest_construction",
                    expected="ConfigFingerprintRecord",
                    actual=fingerprint_record,
                )
        for index, record in enumerate(self.recipe_manifest):
            if not isinstance(record, Mapping):
                raise _artifact_error(
                    f"recipe_manifest[{index}] must be mapping",
                    code="composition_manifest_invalid_recipe_manifest_record",
                    path=f"CompositionManifest.recipe_manifest[{index}]",
                    stage="manifest_construction",
                    expected="mapping",
                    actual=record,
                )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "source_artifacts": [source_artifact.to_dict() for source_artifact in self.source_artifacts],
            "fingerprint_records": [record.to_dict() for record in self.fingerprint_records],
            "recipe_manifest": [to_plain_mapping(record) for record in self.recipe_manifest],
            "metadata": thaw_plain_data(self.metadata, path="CompositionManifest.metadata"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompositionManifest":
        try:
            payload = ensure_plain_data(value, path="CompositionManifest")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                "Invalid composition manifest data",
                code="composition_manifest_invalid_plain_data",
                path="CompositionManifest",
                stage="manifest_from_dict",
                expected="plain-data mapping",
                actual=value,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(payload, Mapping):
            raise _artifact_error(
                "Invalid composition manifest payload; expected a mapping",
                code="composition_manifest_payload_not_mapping",
                path="CompositionManifest",
                stage="manifest_from_dict",
                expected="mapping",
                actual=payload,
            )

        payload_keys = set(payload)
        allowed_keys = {
            "schema_version",
            "source_artifacts",
            "fingerprint_records",
            "recipe_manifest",
            "metadata",
        }
        unknown = payload_keys - allowed_keys
        if unknown:
            raise _artifact_error(
                "CompositionManifest.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}",
                code="composition_manifest_unknown_fields",
                path="CompositionManifest",
                stage="manifest_from_dict",
                expected="known CompositionManifest fields",
                actual="unknown fields",
                details={"unknown_fields": sorted(unknown)},
            )

        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise _artifact_error(
                f"Invalid schema_version: {schema_version!r}",
                code="invalid_composition_manifest_schema_version",
                path="CompositionManifest.schema_version",
                stage="manifest_from_dict",
                expected="positive integer",
                actual=schema_version,
            )

        source_artifacts = payload.get("source_artifacts", ())
        if not isinstance(source_artifacts, Sequence):
            raise _artifact_error(
                "CompositionManifest source_artifacts must be a sequence",
                code="composition_manifest_source_artifacts_not_sequence",
                path="CompositionManifest.source_artifacts",
                stage="manifest_from_dict",
                expected="sequence",
                actual=source_artifacts,
            )
        if isinstance(source_artifacts, (bytes, str, Mapping)):
            raise _artifact_error(
                "CompositionManifest source_artifacts must be a sequence",
                code="composition_manifest_source_artifacts_not_sequence",
                path="CompositionManifest.source_artifacts",
                stage="manifest_from_dict",
                expected="sequence",
                actual=source_artifacts,
            )
        fingerprint_records = payload.get("fingerprint_records", ())
        if not isinstance(fingerprint_records, Sequence) or isinstance(fingerprint_records, (bytes, str, Mapping)):
            raise _artifact_error(
                "CompositionManifest fingerprint_records must be a sequence",
                code="composition_manifest_fingerprint_records_not_sequence",
                path="CompositionManifest.fingerprint_records",
                stage="manifest_from_dict",
                expected="sequence",
                actual=fingerprint_records,
            )
        recipe_manifest = payload.get("recipe_manifest", ())
        if not isinstance(recipe_manifest, Sequence) or isinstance(recipe_manifest, (bytes, str, Mapping)):
            raise _artifact_error(
                "CompositionManifest recipe_manifest must be a sequence",
                code="composition_manifest_recipe_manifest_not_sequence",
                path="CompositionManifest.recipe_manifest",
                stage="manifest_from_dict",
                expected="sequence",
                actual=recipe_manifest,
            )

        if not isinstance(payload.get("metadata", {}), Mapping):
            raise _artifact_error(
                "CompositionManifest metadata must be a mapping",
                code="composition_manifest_metadata_not_mapping",
                path="CompositionManifest.metadata",
                stage="manifest_from_dict",
                expected="mapping",
                actual=payload.get("metadata", {}),
            )

        return cls(
            schema_version=schema_version,
            source_artifacts=tuple(
                SourceArtifactRecord.from_dict(cast(Mapping[str, Any], item)) for item in source_artifacts
            ),
            fingerprint_records=tuple(
                ConfigFingerprintRecord.from_dict(cast(Mapping[str, Any], item))
                for item in fingerprint_records
            ),
            recipe_manifest=tuple(_to_recipe_manifest_payload(recipe_manifest)),
            metadata=cast(dict[str, PlainData], payload.get("metadata", {})),
        )


def _to_recipe_manifest_payload(value: Sequence[object]) -> tuple[dict[str, PlainData], ...]:
    manifest_records: list[dict[str, PlainData]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise _artifact_error(
                f"recipe_manifest[{index}] must be mapping",
                code="recipe_manifest_record_not_mapping",
                path=f"CompositionManifest.recipe_manifest[{index}]",
                stage="manifest_serialization",
                expected="mapping",
                actual=item,
            )
        try:
            payload = ensure_plain_data(item, path=f"CompositionManifest.recipe_manifest[{index}]")
        except Exception as exc:  # noqa: BLE001
            raise _artifact_error(
                f"recipe_manifest[{index}] must be plain data",
                code="recipe_manifest_record_not_plain_data",
                path=f"CompositionManifest.recipe_manifest[{index}]",
                stage="manifest_serialization",
                expected="plain-data mapping",
                actual=item,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(payload, dict):
            raise _artifact_error(
                f"recipe_manifest[{index}] must be a mapping",
                code="recipe_manifest_record_not_plain_mapping",
                path=f"CompositionManifest.recipe_manifest[{index}]",
                stage="manifest_serialization",
                expected="plain-data mapping",
                actual=payload,
            )
        manifest_records.append(payload)
    return tuple(manifest_records)


def to_plain_mapping(value: Mapping[str, Any]) -> dict[str, PlainData]:
    try:
        return cast(dict[str, PlainData], thaw_plain_data(value, path="mapping"))
    except Exception as exc:  # noqa: BLE001
        raise _artifact_error(
            "mapping must be plain data",
            code="artifact_mapping_serialization_failed",
            path="mapping",
            stage="artifact_serialization",
            expected="plain-data mapping",
            actual=value,
            details={"exception_type": type(exc).__name__},
        ) from exc


def _artifact_error(
    message: str,
    *,
    code: str,
    path: str,
    stage: str,
    expected: object | None = None,
    actual: object | None = None,
    details: dict[str, object] | None = None,
) -> ConfigProvenanceError:
    return ConfigProvenanceError(
        message,
        context=_artifact_context(
            code=code,
            path=path,
            stage=stage,
            expected=expected,
            actual=actual,
            details=details,
        ),
    )


def _artifact_context(
    *,
    code: str,
    path: str,
    stage: str,
    expected: object | None = None,
    actual: object | None = None,
    details: dict[str, object] | None = None,
) -> ConfigErrorContext:
    context_details: dict[str, object] = {
        "stage": stage,
        "actual_type": type(actual).__name__ if actual is not None else None,
    }
    if details is not None:
        context_details.update(details)
    return ConfigErrorContext(
        code=code,
        source_kind="artifact",
        source_order=0,
        source_path="<composition-artifact>",
        config_path=path,
        expected=to_plain_data(expected) if expected is not None else None,
        actual=_safe_context_actual(actual),
        details=cast(dict[str, PlainData], to_plain_data(context_details)),
    )


def _safe_context_actual(value: object | None) -> PlainData | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return "sequence"
    return type(value).__name__


__all__ = [
    "CompositionManifest",
    "SourceArtifactRecord",
    "ConfigFingerprintRecord",
    "RawSourceSnapshotPayload",
    "RawSourceSnapshotReference",
    "RawSourceSnapshotBundle",
    "SCHEMA_VERSION",
]
