"""Config provenance and fingerprint helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from loom.fingerprints import Digest, Fingerprint, FingerprintError, hash_mapping
from loom.serialization import PlainData, ensure_plain_data, to_plain_data

from .errors import ConfigProvenanceError

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ConfigSource:
    kind: Literal["base", "overlay"]
    path: str
    order: int
    content_digest: Digest
    size_bytes: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "path": self.path,
            "order": self.order,
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigSource":
        try:
            plain = ensure_plain_data(value)
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("Invalid ConfigSource data") from exc

        if not isinstance(plain, dict):
            raise ConfigProvenanceError("Invalid ConfigSource payload: expected mapping")

        kind = plain.get("kind")
        path = plain.get("path")
        order = plain.get("order")
        content_digest = plain.get("content_digest")
        size_bytes = plain.get("size_bytes")

        if kind not in {"base", "overlay"}:
            raise ConfigProvenanceError(f"Invalid ConfigSource kind: {kind!r}")
        if not isinstance(path, str) or not path:
            raise ConfigProvenanceError(f"Invalid ConfigSource path: {path!r}")
        if not isinstance(order, int) or order < 0:
            raise ConfigProvenanceError(f"Invalid ConfigSource order: {order!r}")
        if not isinstance(content_digest, str):
            raise ConfigProvenanceError(f"Invalid ConfigSource digest: {content_digest!r}")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise ConfigProvenanceError(f"Invalid ConfigSource size: {size_bytes!r}")

        return cls(
            kind=cast(Literal["base", "overlay"], kind),
            path=path,
            order=order,
            content_digest=content_digest,
            size_bytes=size_bytes,
        )


@dataclass(frozen=True, slots=True)
class ParsedOverride:
    raw: str
    path: str
    operation: Literal["update", "add"]
    value: PlainData
    order: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "raw": self.raw,
            "path": self.path,
            "operation": self.operation,
            "value": self.value,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParsedOverride":
        try:
            plain = ensure_plain_data(value)
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("Invalid ParsedOverride data") from exc

        if not isinstance(plain, dict):
            raise ConfigProvenanceError("Invalid ParsedOverride payload: expected mapping")

        raw = plain.get("raw")
        path = plain.get("path")
        operation = plain.get("operation")
        parsed_value = plain.get("value")
        order = plain.get("order")

        if not isinstance(raw, str):
            raise ConfigProvenanceError(f"Invalid override raw value: {raw!r}")
        if not isinstance(path, str) or not path:
            raise ConfigProvenanceError(f"Invalid override path: {path!r}")
        if operation not in {"update", "add"}:
            raise ConfigProvenanceError(f"Invalid override operation: {operation!r}")
        if not isinstance(order, int) or order < 0:
            raise ConfigProvenanceError(f"Invalid override order: {order!r}")

        return cls(
            raw=raw,
            path=path,
            operation=cast(Literal["update", "add"], operation),
            value=to_plain_data(parsed_value),
            order=order,
        )


@dataclass(frozen=True, slots=True)
class ConfigProvenance:
    schema_version: int
    config_path: str
    sources: tuple[ConfigSource, ...]
    overrides: tuple[ParsedOverride, ...]
    resolved_fingerprint: Fingerprint
    recipe_manifest_count: int
    metadata: dict[str, PlainData]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "config_path": self.config_path,
            "sources": [source.to_dict() for source in self.sources],
            "overrides": [override.to_dict() for override in self.overrides],
            "resolved_fingerprint": self.resolved_fingerprint,
            "recipe_manifest_count": self.recipe_manifest_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigProvenance":
        try:
            plain = ensure_plain_data(value)
        except Exception as exc:  # noqa: BLE001
            raise ConfigProvenanceError("Invalid ConfigProvenance data") from exc

        if not isinstance(plain, dict):
            raise ConfigProvenanceError("Invalid ConfigProvenance payload: expected mapping")

        schema_version = plain.get("schema_version")
        config_path = plain.get("config_path")
        sources_payload = plain.get("sources")
        overrides_payload = plain.get("overrides")
        resolved_fingerprint = plain.get("resolved_fingerprint")
        recipe_manifest_count = plain.get("recipe_manifest_count")
        metadata = plain.get("metadata")

        if not isinstance(schema_version, int) or schema_version < 1:
            raise ConfigProvenanceError(f"Invalid schema_version: {schema_version!r}")
        if not isinstance(config_path, str) or not config_path:
            raise ConfigProvenanceError(f"Invalid config_path: {config_path!r}")
        if not isinstance(resolved_fingerprint, str) or not resolved_fingerprint:
            raise ConfigProvenanceError("Invalid resolved_fingerprint")
        if not isinstance(recipe_manifest_count, int) or recipe_manifest_count < 0:
            raise ConfigProvenanceError("Invalid recipe_manifest_count")
        if not isinstance(metadata, dict):
            raise ConfigProvenanceError("Invalid metadata")

        if not isinstance(sources_payload, Sequence) or not isinstance(overrides_payload, Sequence):
            raise ConfigProvenanceError("Invalid provenance source/override payload")

        sources = tuple(ConfigSource.from_dict(cast(Mapping[str, Any], item)) for item in sources_payload)
        overrides = tuple(ParsedOverride.from_dict(cast(Mapping[str, Any], item)) for item in overrides_payload)

        plain_metadata = to_plain_data(metadata)
        if not isinstance(plain_metadata, dict):
            raise ConfigProvenanceError("Invalid metadata")

        return cls(
            schema_version=schema_version,
            config_path=config_path,
            sources=sources,
            overrides=overrides,
            resolved_fingerprint=resolved_fingerprint,
            recipe_manifest_count=recipe_manifest_count,
            metadata=plain_metadata,
        )


def build_config_fingerprint(
    *,
    resolved: dict[str, PlainData],
    sources: tuple[ConfigSource, ...],
    overrides: tuple[ParsedOverride, ...],
    recipe_manifest: tuple[Mapping[str, PlainData], ...] | None = None,
    schema_version: int,
) -> Fingerprint:
    payload = {
        "schema_version": schema_version,
        "resolved": resolved,
        "sources": [source.to_dict() for source in sources],
        "overrides": [override.to_dict() for override in overrides],
        "recipe_manifest": list(recipe_manifest or ()),
    }
    try:
        return hash_mapping(payload)
    except FingerprintError as exc:
        raise ConfigProvenanceError("Failed to hash config fingerprint payload") from exc
