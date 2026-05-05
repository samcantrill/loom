"""Configuration artifact contracts for composition metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, cast

from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data

from .errors import ConfigProvenanceError

SCHEMA_VERSION = 1
_SourceArtifactKind: TypeAlias = Literal["base", "overlay", "include", "recipe"]
_SOURCE_ARTIFACT_KINDS = frozenset({"base", "overlay", "include", "recipe"})


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
            raise ConfigProvenanceError("schema_version must be a positive integer")
        if self.kind not in _SOURCE_ARTIFACT_KINDS:
            raise ConfigProvenanceError(f"Invalid source artifact kind: {self.kind!r}")
        if not isinstance(self.path, str) or not self.path:
            raise ConfigProvenanceError(f"Invalid source artifact path: {self.path!r}")
        if not isinstance(self.order, int) or self.order < 0:
            raise ConfigProvenanceError(f"Invalid source artifact order: {self.order!r}")
        if not isinstance(self.content_digest, str) or not self.content_digest:
            raise ConfigProvenanceError(f"Invalid source artifact digest: {self.content_digest!r}")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid source artifact size: {self.size_bytes!r}")
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="SourceArtifactRecord.metadata")
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("source artifact metadata must be plain data") from exc
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
        payload = ensure_plain_data(value, path="SourceArtifactRecord")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid source artifact payload; expected a mapping")

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
            raise ConfigProvenanceError(
                "SourceArtifactRecord.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        schema_version = payload.get("schema_version")
        kind = payload.get("kind")
        path = payload.get("path")
        order = payload.get("order")
        content_digest = payload.get("content_digest")
        size_bytes = payload.get("size_bytes")
        metadata = payload.get("metadata", {})
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise ConfigProvenanceError(f"Invalid schema_version: {schema_version!r}")
        if not isinstance(order, int) or order < 0:
            raise ConfigProvenanceError(f"Invalid order: {order!r}")
        if not isinstance(path, str) or not path:
            raise ConfigProvenanceError(f"Invalid path: {path!r}")
        if kind not in _SOURCE_ARTIFACT_KINDS:
            raise ConfigProvenanceError(f"Invalid source artifact kind: {kind!r}")
        if not isinstance(content_digest, str) or not content_digest:
            raise ConfigProvenanceError(f"Invalid content_digest: {content_digest!r}")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid size_bytes: {size_bytes!r}")

        if not isinstance(metadata, Mapping):
            raise ConfigProvenanceError("SourceArtifactRecord metadata must be a mapping")
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
            raise ConfigProvenanceError("schema_version must be a positive integer")
        if not isinstance(self.digest, str) or not self.digest:
            raise ConfigProvenanceError("digest must be a non-empty string")
        if not isinstance(self.label, str) or not self.label:
            raise ConfigProvenanceError("label must be a non-empty string")
        if not isinstance(self.algorithm, str) or not self.algorithm:
            raise ConfigProvenanceError("algorithm must be a non-empty string")
        try:
            frozen_metadata = freeze_plain_data(self.metadata, path="ConfigFingerprintRecord.metadata")
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("ConfigFingerprintRecord metadata must be plain data") from exc
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
        payload = ensure_plain_data(value, path="ConfigFingerprintRecord")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid fingerprint payload; expected a mapping")

        payload_keys = set(payload)
        allowed_keys = {"schema_version", "digest", "label", "algorithm", "metadata"}
        unknown = payload_keys - allowed_keys
        if unknown:
            raise ConfigProvenanceError(
                "ConfigFingerprintRecord.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        schema_version = payload.get("schema_version")
        digest = payload.get("digest")
        label = payload.get("label", "resolved")
        algorithm = payload.get("algorithm", "sha256")
        metadata = payload.get("metadata", {})
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise ConfigProvenanceError(f"Invalid schema_version: {schema_version!r}")
        if not isinstance(digest, str) or not digest:
            raise ConfigProvenanceError(f"Invalid digest: {digest!r}")
        if not isinstance(label, str) or not label:
            raise ConfigProvenanceError(f"Invalid label: {label!r}")
        if not isinstance(algorithm, str) or not algorithm:
            raise ConfigProvenanceError(f"Invalid algorithm: {algorithm!r}")
        if not isinstance(metadata, Mapping):
            raise ConfigProvenanceError("ConfigFingerprintRecord metadata must be a mapping")

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
            raise ConfigProvenanceError("schema_version must be a positive integer")
        try:
            frozen_sources = tuple(self.source_artifacts)
            frozen_fingerprints = tuple(self.fingerprint_records)
            frozen_metadata = freeze_plain_data(self.metadata, path="CompositionManifest.metadata")
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("CompositionManifest fields must be plain-data-compatible") from exc

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
            raise ConfigProvenanceError("CompositionManifest recipe_manifest must be plain data") from exc

        object.__setattr__(self, "source_artifacts", frozen_sources)
        object.__setattr__(self, "fingerprint_records", frozen_fingerprints)
        object.__setattr__(self, "recipe_manifest", frozen_recipe_manifest)
        object.__setattr__(self, "metadata", cast(dict[str, PlainData], frozen_metadata))
        for index, source_artifact in enumerate(self.source_artifacts):
            if not isinstance(source_artifact, SourceArtifactRecord):
                raise ConfigProvenanceError(f"source_artifacts[{index}] must be SourceArtifactRecord")
        for index, fingerprint_record in enumerate(self.fingerprint_records):
            if not isinstance(fingerprint_record, ConfigFingerprintRecord):
                raise ConfigProvenanceError(
                    f"fingerprint_records[{index}] must be ConfigFingerprintRecord"
                )
        for index, record in enumerate(self.recipe_manifest):
            if not isinstance(record, Mapping):
                raise ConfigProvenanceError(f"recipe_manifest[{index}] must be mapping")

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
        payload = ensure_plain_data(value, path="CompositionManifest")
        if not isinstance(payload, Mapping):
            raise ConfigProvenanceError("Invalid composition manifest payload; expected a mapping")

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
            raise ConfigProvenanceError(
                "CompositionManifest.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )

        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
            raise ConfigProvenanceError(f"Invalid schema_version: {schema_version!r}")

        source_artifacts = payload.get("source_artifacts", ())
        if not isinstance(source_artifacts, Sequence):
            raise ConfigProvenanceError("CompositionManifest source_artifacts must be a sequence")
        if isinstance(source_artifacts, (bytes, str, Mapping)):
            raise ConfigProvenanceError("CompositionManifest source_artifacts must be a sequence")
        fingerprint_records = payload.get("fingerprint_records", ())
        if not isinstance(fingerprint_records, Sequence) or isinstance(fingerprint_records, (bytes, str, Mapping)):
            raise ConfigProvenanceError("CompositionManifest fingerprint_records must be a sequence")
        recipe_manifest = payload.get("recipe_manifest", ())
        if not isinstance(recipe_manifest, Sequence) or isinstance(recipe_manifest, (bytes, str, Mapping)):
            raise ConfigProvenanceError("CompositionManifest recipe_manifest must be a sequence")

        if not isinstance(payload.get("metadata", {}), Mapping):
            raise ConfigProvenanceError("CompositionManifest metadata must be a mapping")

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
            raise ConfigProvenanceError(f"recipe_manifest[{index}] must be mapping")
        payload = ensure_plain_data(item, path=f"CompositionManifest.recipe_manifest[{index}]")
        if not isinstance(payload, dict):
            raise ConfigProvenanceError(f"recipe_manifest[{index}] must be a mapping")
        manifest_records.append(payload)
    return tuple(manifest_records)


def to_plain_mapping(value: Mapping[str, Any]) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], ensure_plain_data(dict(value), path="mapping"))


__all__ = [
    "CompositionManifest",
    "SourceArtifactRecord",
    "ConfigFingerprintRecord",
    "SCHEMA_VERSION",
]
