"""Config provenance and fingerprint helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from loom.fingerprints import Digest, Fingerprint, FingerprintError, hash_mapping
from loom.serialization import PlainData, ensure_plain_data, to_plain_data

from .errors import ConfigErrorContext, ConfigProvenanceError
from .redaction import (
    REDACTION_MARKER,
    contains_secret_like_value,
    is_secret_path,
    redact_secret_like_value,
)

SCHEMA_VERSION = 2
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})


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
            raise _provenance_error(
                "Invalid ConfigSource data",
                code="config_source_invalid_plain_data",
                path="ConfigSource",
                stage="provenance_from_dict",
                expected="plain-data mapping",
                actual=value,
            ) from exc

        if not isinstance(plain, dict):
            raise _provenance_error(
                "Invalid ConfigSource payload: expected mapping",
                code="config_source_payload_not_mapping",
                path="ConfigSource",
                stage="provenance_from_dict",
                expected="mapping",
                actual=plain,
            )

        kind = plain.get("kind")
        path = plain.get("path")
        order = plain.get("order")
        content_digest = plain.get("content_digest")
        size_bytes = plain.get("size_bytes")

        if kind not in {"base", "overlay"}:
            raise _provenance_error(
                f"Invalid ConfigSource kind: {kind!r}",
                code="invalid_config_source_kind",
                path="ConfigSource.kind",
                stage="provenance_from_dict",
                expected="base or overlay",
                actual=kind,
            )
        if not isinstance(path, str) or not path:
            raise _provenance_error(
                f"Invalid ConfigSource path: {path!r}",
                code="invalid_config_source_path",
                path="ConfigSource.path",
                stage="provenance_from_dict",
                expected="non-empty string",
                actual=path,
            )
        if not isinstance(order, int) or order < 0:
            raise _provenance_error(
                f"Invalid ConfigSource order: {order!r}",
                code="invalid_config_source_order",
                path="ConfigSource.order",
                stage="provenance_from_dict",
                expected="non-negative integer",
                actual=order,
            )
        if not isinstance(content_digest, str):
            raise _provenance_error(
                f"Invalid ConfigSource digest: {content_digest!r}",
                code="invalid_config_source_digest",
                path="ConfigSource.content_digest",
                stage="provenance_from_dict",
                expected="string",
                actual=content_digest,
            )
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise _provenance_error(
                f"Invalid ConfigSource size: {size_bytes!r}",
                code="invalid_config_source_size",
                path="ConfigSource.size_bytes",
                stage="provenance_from_dict",
                expected="non-negative integer",
                actual=size_bytes,
            )

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
            raise _provenance_error(
                "Invalid ParsedOverride data",
                code="parsed_override_invalid_plain_data",
                path="ParsedOverride",
                stage="provenance_from_dict",
                expected="plain-data mapping",
                actual=value,
            ) from exc

        if not isinstance(plain, dict):
            raise _provenance_error(
                "Invalid ParsedOverride payload: expected mapping",
                code="parsed_override_payload_not_mapping",
                path="ParsedOverride",
                stage="provenance_from_dict",
                expected="mapping",
                actual=plain,
            )

        raw = plain.get("raw")
        path = plain.get("path")
        operation = plain.get("operation")
        parsed_value = plain.get("value")
        order = plain.get("order")

        if not isinstance(raw, str):
            raise _provenance_error(
                f"Invalid override raw value: {raw!r}",
                code="invalid_override_raw",
                path="ParsedOverride.raw",
                stage="provenance_from_dict",
                expected="string",
                actual=raw,
            )
        if not isinstance(path, str) or not path:
            raise _provenance_error(
                f"Invalid override path: {path!r}",
                code="invalid_override_path",
                path="ParsedOverride.path",
                stage="provenance_from_dict",
                expected="non-empty string",
                actual=path,
            )
        if operation not in {"update", "add"}:
            raise _provenance_error(
                f"Invalid override operation: {operation!r}",
                code="invalid_override_operation",
                path="ParsedOverride.operation",
                stage="provenance_from_dict",
                expected="update or add",
                actual=operation,
            )
        if not isinstance(order, int) or order < 0:
            raise _provenance_error(
                f"Invalid override order: {order!r}",
                code="invalid_override_order",
                path="ParsedOverride.order",
                stage="provenance_from_dict",
                expected="non-negative integer",
                actual=order,
            )

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
    recipe_manifest_count: int
    metadata: dict[str, PlainData]
    artifact_fingerprint: Fingerprint | None = None

    def to_dict(self) -> dict[str, PlainData]:
        if self.schema_version == SCHEMA_VERSION and not self.artifact_fingerprint:
            raise _provenance_error(
                "schema-version-2 ConfigProvenance writes require artifact_fingerprint",
                code="invalid_config_provenance_artifact_fingerprint",
                path="ConfigProvenance.artifact_fingerprint",
                stage="provenance_serialization",
                expected="non-empty string",
                actual=self.artifact_fingerprint,
            )
        payload: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "config_path": self.config_path,
            "sources": [source.to_dict() for source in self.sources],
            "overrides": [_override_to_artifact_dict(override) for override in self.overrides],
            "recipe_manifest_count": self.recipe_manifest_count,
            "metadata": self.metadata,
        }
        if self.artifact_fingerprint is not None:
            payload["artifact_fingerprint"] = self.artifact_fingerprint
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigProvenance":
        try:
            plain = ensure_plain_data(value)
        except Exception as exc:  # noqa: BLE001
            raise _provenance_error(
                "Invalid ConfigProvenance data",
                code="config_provenance_invalid_plain_data",
                path="ConfigProvenance",
                stage="provenance_from_dict",
                expected="plain-data mapping",
                actual=value,
            ) from exc

        if not isinstance(plain, dict):
            raise _provenance_error(
                "Invalid ConfigProvenance payload: expected mapping",
                code="config_provenance_payload_not_mapping",
                path="ConfigProvenance",
                stage="provenance_from_dict",
                expected="mapping",
                actual=plain,
            )

        schema_version = plain.get("schema_version")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise _provenance_error(
                f"Invalid schema_version: {schema_version!r}",
                code="invalid_config_provenance_schema_version",
                path="ConfigProvenance.schema_version",
                stage="provenance_from_dict",
                expected="positive integer",
                actual=schema_version,
            )
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise _provenance_error(
                f"Unsupported schema_version: {schema_version!r}",
                code="unsupported_config_provenance_schema_version",
                path="ConfigProvenance.schema_version",
                stage="provenance_from_dict",
                expected=sorted(_SUPPORTED_SCHEMA_VERSIONS),
                actual=schema_version,
            )

        allowed_keys = {
            "schema_version",
            "config_path",
            "sources",
            "overrides",
            "recipe_manifest_count",
            "metadata",
        }
        if schema_version == 1:
            allowed_keys.add("resolved_fingerprint")
        else:
            allowed_keys.add("artifact_fingerprint")
        unknown = set(plain) - allowed_keys
        if unknown:
            raise _provenance_error(
                "ConfigProvenance.from_dict received unknown fields",
                code="config_provenance_unknown_fields",
                path="ConfigProvenance",
                stage="provenance_from_dict",
                expected=sorted(allowed_keys),
                actual=sorted(unknown),
            )

        config_path = plain.get("config_path")
        sources_payload = plain.get("sources")
        overrides_payload = plain.get("overrides")
        artifact_fingerprint = plain.get("artifact_fingerprint")
        resolved_fingerprint = plain.get("resolved_fingerprint")
        recipe_manifest_count = plain.get("recipe_manifest_count")
        metadata = plain.get("metadata")

        if not isinstance(config_path, str) or not config_path:
            raise _provenance_error(
                f"Invalid config_path: {config_path!r}",
                code="invalid_config_provenance_config_path",
                path="ConfigProvenance.config_path",
                stage="provenance_from_dict",
                expected="non-empty string",
                actual=config_path,
            )
        if schema_version == 2 and (
            not isinstance(artifact_fingerprint, str) or not artifact_fingerprint
        ):
            raise _provenance_error(
                "Invalid artifact_fingerprint",
                code="invalid_config_provenance_artifact_fingerprint",
                path="ConfigProvenance.artifact_fingerprint",
                stage="provenance_from_dict",
                expected="non-empty string",
                actual=artifact_fingerprint,
            )
        if schema_version == 1 and (
            not isinstance(resolved_fingerprint, str) or not resolved_fingerprint
        ):
            raise _provenance_error(
                "Invalid resolved_fingerprint",
                code="invalid_config_provenance_resolved_fingerprint",
                path="ConfigProvenance.resolved_fingerprint",
                stage="provenance_from_dict",
                expected="non-empty string",
                actual=resolved_fingerprint,
            )
        if not isinstance(recipe_manifest_count, int) or recipe_manifest_count < 0:
            raise _provenance_error(
                "Invalid recipe_manifest_count",
                code="invalid_config_provenance_recipe_manifest_count",
                path="ConfigProvenance.recipe_manifest_count",
                stage="provenance_from_dict",
                expected="non-negative integer",
                actual=recipe_manifest_count,
            )
        if not isinstance(metadata, dict):
            raise _provenance_error(
                "Invalid metadata",
                code="invalid_config_provenance_metadata",
                path="ConfigProvenance.metadata",
                stage="provenance_from_dict",
                expected="mapping",
                actual=metadata,
            )

        if not isinstance(sources_payload, Sequence) or not isinstance(overrides_payload, Sequence):
            raise _provenance_error(
                "Invalid provenance source/override payload",
                code="invalid_config_provenance_source_override_payload",
                path="ConfigProvenance",
                stage="provenance_from_dict",
                expected="source and override sequences",
                actual={
                    "sources_type": type(sources_payload).__name__,
                    "overrides_type": type(overrides_payload).__name__,
                },
            )

        sources = tuple(ConfigSource.from_dict(cast(Mapping[str, Any], item)) for item in sources_payload)
        overrides = tuple(ParsedOverride.from_dict(cast(Mapping[str, Any], item)) for item in overrides_payload)

        plain_metadata = to_plain_data(metadata)
        if not isinstance(plain_metadata, dict):
            raise _provenance_error(
                "Invalid metadata",
                code="invalid_config_provenance_metadata_plain_data",
                path="ConfigProvenance.metadata",
                stage="provenance_from_dict",
                expected="plain-data mapping",
                actual=plain_metadata,
            )
        if schema_version == 1:
            plain_metadata = {
                **plain_metadata,
                "legacy_resolved_fingerprint": resolved_fingerprint,
            }

        return cls(
            schema_version=schema_version,
            config_path=config_path,
            sources=sources,
            overrides=overrides,
            recipe_manifest_count=recipe_manifest_count,
            metadata=plain_metadata,
            artifact_fingerprint=cast(Fingerprint | None, artifact_fingerprint),
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
        raise _provenance_error(
            "Failed to hash config fingerprint payload",
            code="config_fingerprint_hash_failed",
            path="ConfigFingerprint.payload",
            stage="provenance_serialization",
            expected="hashable plain-data payload",
            actual=payload,
            details={"exception_type": type(exc).__name__},
        ) from exc


def _override_to_artifact_dict(override: ParsedOverride) -> dict[str, PlainData]:
    final_key = override.path.rsplit(".", 1)[-1]
    path_redacted = is_secret_path(override.path)
    redacted = path_redacted or contains_secret_like_value(final_key, override.value)
    return {
        "raw": REDACTION_MARKER if redacted else override.raw,
        "path": override.path,
        "operation": override.operation,
        "value": (
            REDACTION_MARKER if path_redacted else redact_secret_like_value(final_key, override.value)
        ),
        "order": override.order,
        "redacted": redacted,
    }


def _provenance_error(
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
        context=_provenance_context(
            code=code,
            path=path,
            stage=stage,
            expected=expected,
            actual=actual,
            details=details,
        ),
    )


def _provenance_context(
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
        source_kind="provenance",
        source_order=0,
        source_path="<config-provenance>",
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
