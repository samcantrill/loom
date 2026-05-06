"""Artifact-safe authored-composition fingerprint helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from loom.fingerprints import hash_mapping
from loom.serialization import PlainData, ensure_plain_data, to_plain_data

from .artifacts import (
    SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION,
    CompositionManifest,
    ConfigFingerprintRecord,
    SourceArtifactRecord,
)
from .provenance import ParsedOverride
from .redaction import (
    REDACTION_MARKER,
    contains_secret_like_value,
    is_secret_path,
    redact_secret_like_value,
)

if TYPE_CHECKING:
    from .includes import IncludeSiteRecord
    from .interpolation import ResolverExpressionRecord

FingerprintComparisonStatus = Literal[
    "match",
    "mismatch",
    "incompatible_policy",
    "insufficient_data",
]

ARTIFACT_SAFE_FINGERPRINT_LABEL = "artifact_safe_config"
ARTIFACT_SAFE_FINGERPRINT_POLICY = "artifact_safe_authored_composition_v1"
ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION = 1
ARTIFACT_SAFE_RUNTIME_REPLAY = "unavailable"


@dataclass(frozen=True, slots=True)
class ConfigFingerprintComparison:
    status: FingerprintComparisonStatus
    left_digest: str | None
    right_digest: str | None
    left_record_label: str | None
    right_record_label: str | None
    left_policy: str | None
    right_policy: str | None
    left_payload_schema_version: int | None
    right_payload_schema_version: int | None
    left_algorithm: str | None
    right_algorithm: str | None
    runtime_values_replayed: bool
    reason: str


def build_artifact_safe_config_fingerprint_payload(
    *,
    unresolved: Mapping[str, PlainData],
    redacted: Mapping[str, PlainData],
    source_artifacts: Sequence[SourceArtifactRecord],
    include_sites: Sequence[IncludeSiteRecord],
    include_overrides: Sequence[ParsedOverride],
    ordinary_overrides: Sequence[ParsedOverride],
    recipe_manifest: Sequence[Mapping[str, PlainData]],
    resolver_records: Sequence[ResolverExpressionRecord],
    redaction_policy: Mapping[str, PlainData],
) -> dict[str, PlainData]:
    source_artifact_facts = [_source_artifact_fingerprint_facts(record) for record in source_artifacts]
    include_facts = [_include_record_fingerprint_facts(record) for record in include_sites]
    resolver_facts = [_resolver_expression_record_facts(record) for record in resolver_records]
    recipe_manifest_payload = [
        cast(dict[str, PlainData], to_plain_data(record, path="recipe_manifest")) for record in recipe_manifest
    ]

    payload = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "payload_schema_version": ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION,
        "fingerprint_policy": ARTIFACT_SAFE_FINGERPRINT_POLICY,
        "semantic_scope": "authored_composition",
        "runtime_values_included": False,
        "resolver_outputs_included": False,
        "raw_source_bytes_included": False,
        "runtime_value_replay": ARTIFACT_SAFE_RUNTIME_REPLAY,
        "source_artifact_count": len(source_artifacts),
        "resolver_expression_count": len(resolver_records),
        "include_record_count": len(include_sites),
        "override_count": len(include_overrides) + len(ordinary_overrides),
        "recipe_manifest_count": len(recipe_manifest),
        "source_artifact_facts": source_artifact_facts,
        "include_facts": include_facts,
        "resolver_facts": resolver_facts,
        "include_overrides": [_override_fact(override) for override in include_overrides],
        "ordinary_overrides": [_override_fact(override) for override in ordinary_overrides],
        "recipe_manifest": recipe_manifest_payload,
        "unresolved": cast(dict[str, PlainData], to_plain_data(redacted, path="unresolved")),
        "redacted": cast(dict[str, PlainData], to_plain_data(redacted, path="redacted")),
        "redaction_policy": redaction_policy,
    }
    return cast(dict[str, PlainData], to_plain_data(payload, path="artifact_safe_fingerprint_payload"))


def build_artifact_safe_config_fingerprint_record(
    *,
    unresolved: Mapping[str, PlainData],
    redacted: Mapping[str, PlainData],
    source_artifacts: Sequence[SourceArtifactRecord],
    include_sites: Sequence[IncludeSiteRecord],
    include_overrides: Sequence[ParsedOverride],
    ordinary_overrides: Sequence[ParsedOverride],
    recipe_manifest: Sequence[Mapping[str, PlainData]],
    resolver_records: Sequence[ResolverExpressionRecord],
    redaction_policy: Mapping[str, PlainData],
) -> ConfigFingerprintRecord:
    payload = build_artifact_safe_config_fingerprint_payload(
        unresolved=unresolved,
        redacted=redacted,
        source_artifacts=source_artifacts,
        include_sites=include_sites,
        include_overrides=include_overrides,
        ordinary_overrides=ordinary_overrides,
        recipe_manifest=recipe_manifest,
        resolver_records=resolver_records,
        redaction_policy=redaction_policy,
    )
    return ConfigFingerprintRecord(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        digest=hash_mapping(payload),
        label=ARTIFACT_SAFE_FINGERPRINT_LABEL,
        algorithm="sha256",
        metadata=payload,
    )


def compare_config_artifact_fingerprints(
    left: ConfigFingerprintRecord | CompositionManifest | Mapping[str, PlainData],
    right: ConfigFingerprintRecord | CompositionManifest | Mapping[str, PlainData],
) -> ConfigFingerprintComparison:
    left_record = _extract_default_fingerprint_record(left)
    right_record = _extract_default_fingerprint_record(right)

    if left_record is None or right_record is None:
        return _build_comparison(
            status="insufficient_data",
            left_record=left_record,
            right_record=right_record,
            reason="Missing default artifact-safe fingerprint record",
        )

    if (
        left_record.label != ARTIFACT_SAFE_FINGERPRINT_LABEL
        or right_record.label != ARTIFACT_SAFE_FINGERPRINT_LABEL
    ):
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Unexpected fingerprint label",
        )

    left_policy = _extract_metadata_value(left_record.metadata, "fingerprint_policy", expected=str)
    right_policy = _extract_metadata_value(right_record.metadata, "fingerprint_policy", expected=str)
    if left_policy != ARTIFACT_SAFE_FINGERPRINT_POLICY or right_policy != ARTIFACT_SAFE_FINGERPRINT_POLICY:
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Fingerprint policy mismatch",
        )

    left_scope = _extract_metadata_value(left_record.metadata, "semantic_scope", expected=str)
    right_scope = _extract_metadata_value(right_record.metadata, "semantic_scope", expected=str)
    if left_scope != right_scope or left_scope is None:
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Fingerprint semantic scope mismatch",
        )

    left_payload_schema = _extract_metadata_value(
        left_record.metadata, "payload_schema_version", expected=int
    )
    right_payload_schema = _extract_metadata_value(
        right_record.metadata, "payload_schema_version", expected=int
    )
    if (
        left_payload_schema != ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION
        or right_payload_schema != ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION
    ):
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Fingerprint payload schema mismatch",
        )

    left_artifact_schema = _extract_metadata_value(left_record.metadata, "artifact_schema_version", expected=int)
    right_artifact_schema = _extract_metadata_value(right_record.metadata, "artifact_schema_version", expected=int)
    if left_artifact_schema != ARTIFACT_SCHEMA_VERSION or right_artifact_schema != ARTIFACT_SCHEMA_VERSION:
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Artifact schema mismatch",
        )

    if left_record.algorithm != right_record.algorithm:
        return _build_comparison(
            status="incompatible_policy",
            left_record=left_record,
            right_record=right_record,
            reason="Fingerprint algorithm mismatch",
        )

    if left_record.digest == right_record.digest:
        return _build_comparison(
            status="match",
            left_record=left_record,
            right_record=right_record,
            reason="Default artifact-safe fingerprint records match",
        )

    return _build_comparison(
        status="mismatch",
        left_record=left_record,
        right_record=right_record,
        reason="Default artifact-safe fingerprint digests differ",
    )


def _extract_default_fingerprint_record(
    value: ConfigFingerprintRecord | CompositionManifest | Mapping[str, PlainData],
) -> ConfigFingerprintRecord | None:
    if isinstance(value, ConfigFingerprintRecord):
        return value

    if isinstance(value, CompositionManifest):
        return _extract_default_record_from_records(value.fingerprint_records)

    if not isinstance(value, Mapping):
        return None
    try:
        plain = _ensure_plain_mapping(value)
    except Exception:
        return None

    if _looks_like_manifest_dict(plain):
        try:
            manifest = CompositionManifest.from_dict(plain)
        except Exception:
            return None
        return _extract_default_record_from_records(manifest.fingerprint_records)

    try:
        record = ConfigFingerprintRecord.from_dict(plain)
    except Exception:
        return None
    return record


def _extract_default_record_from_records(
    records: Sequence[ConfigFingerprintRecord],
) -> ConfigFingerprintRecord | None:
    for record in records:
        if record.label == ARTIFACT_SAFE_FINGERPRINT_LABEL:
            return record
    return None


def _extract_metadata_value(
    metadata: Mapping[str, PlainData],
    key: str,
    expected: type[Any],
) -> Any | None:
    value = metadata.get(key)
    return value if isinstance(value, expected) else None


def _build_comparison(
    *,
    status: FingerprintComparisonStatus,
    left_record: ConfigFingerprintRecord | None,
    right_record: ConfigFingerprintRecord | None,
    reason: str,
) -> ConfigFingerprintComparison:
    return ConfigFingerprintComparison(
        status=status,
        left_digest=left_record.digest if left_record is not None else None,
        right_digest=right_record.digest if right_record is not None else None,
        left_record_label=left_record.label if left_record is not None else None,
        right_record_label=right_record.label if right_record is not None else None,
        left_policy=_extract_metadata_value(
            left_record.metadata if left_record is not None else {},
            "fingerprint_policy",
            expected=str,
        ),
        right_policy=_extract_metadata_value(
            right_record.metadata if right_record is not None else {},
            "fingerprint_policy",
            expected=str,
        ),
        left_payload_schema_version=_extract_metadata_value(
            left_record.metadata if left_record is not None else {},
            "payload_schema_version",
            expected=int,
        ),
        right_payload_schema_version=_extract_metadata_value(
            right_record.metadata if right_record is not None else {},
            "payload_schema_version",
            expected=int,
        ),
        left_algorithm=left_record.algorithm if left_record is not None else None,
        right_algorithm=right_record.algorithm if right_record is not None else None,
        runtime_values_replayed=False,
        reason=reason,
    )


def _ensure_plain_mapping(value: Mapping[str, object] | Mapping[str, PlainData]) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], ensure_plain_data(value, path="fingerprint_data"))


def _looks_like_manifest_dict(payload: Mapping[str, PlainData]) -> bool:
    return (
        (isinstance(payload.get("schema_version"), int))
        and "fingerprint_records" in payload
        and isinstance(payload.get("fingerprint_records"), (list, tuple))
    )


def _source_artifact_fingerprint_facts(record: SourceArtifactRecord) -> dict[str, PlainData]:
    facts: dict[str, PlainData] = {
        "kind": record.kind,
        "order": record.order,
        "role": "source",
        "content_digest": record.content_digest,
        "size_bytes": record.size_bytes,
    }

    if record.kind == "include":
        metadata = cast(dict[str, Any], record.metadata)
        facts["role"] = "include"
        facts["include"] = cast(
            dict[str, PlainData],
            to_plain_data(
                {
                    "include_site_path": metadata.get("include_site_path", ()),
                    "authored_target": metadata.get("authored_target", ""),
                    "target_kind": metadata.get("target_kind", ""),
                    "explicit_escape": bool(metadata.get("explicit_escape", False)),
                    "source_kind": metadata.get("source_kind"),
                    "source_order": metadata.get("source_order"),
                    "source_content_digest": metadata.get("source_content_digest"),
                    "source_size_bytes": metadata.get("source_size_bytes"),
                    "source_include_site_path": metadata.get("source_include_site_path", ()),
                    "has_replace_marker": bool(metadata.get("has_replace_marker", False)),
                },
                path="source_artifact_include_facts",
            ),
        )
    elif record.kind == "recipe":
        metadata = cast(dict[str, Any], record.metadata)
        facts["role"] = "recipe"
        facts["recipe"] = cast(
            dict[str, PlainData],
            to_plain_data(
                {
                    "name": metadata.get("name", ""),
                    "path": metadata.get("path", ""),
                    "target": metadata.get("target", ""),
                    "expanded_hash": metadata.get("expanded_hash", ""),
                    "loom_version": metadata.get("loom_version"),
                },
                path="source_artifact_recipe_facts",
            ),
        )
    return cast(dict[str, PlainData], to_plain_data(facts, path="source_artifact_facts"))


def _include_record_fingerprint_facts(record: IncludeSiteRecord) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        to_plain_data(
            {
                "include_site_path": _to_plain_path(record.include_site_path),
                "source_include_site_path": _to_plain_path(record.source_include_site_path),
                "authored_target": record.authored_target,
                "target_kind": record.target_kind,
                "explicit_escape": record.explicit_escape,
                "has_replace_marker": record.has_replace_marker,
            },
            path="include_record_facts",
        ),
    )


def _resolver_expression_record_facts(record: ResolverExpressionRecord) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "config_path": record.config_path,
            "token": record.token,
            "resolver": record.resolver,
            "expression": record.expression,
        },
    )


def _override_fact(override: ParsedOverride) -> dict[str, PlainData]:
    final_key = override.path.rsplit(".", 1)[-1]
    path_redacted = is_secret_path(override.path)
    redacted = path_redacted or contains_secret_like_value(final_key, override.value)
    value: PlainData = (
        REDACTION_MARKER if path_redacted else redact_secret_like_value(final_key, override.value)
    )
    if isinstance(value, (dict, list)) and redacted is False:
        value = cast(PlainData, to_plain_data(value, path=f"override:{override.path}"))
    return {
        "raw": REDACTION_MARKER if redacted else override.raw,
        "path": override.path,
        "operation": override.operation,
        "value": value,
        "order": override.order,
        "redacted": redacted,
    }


def _to_plain_path(path: tuple[object, ...]) -> list[str | int]:
    plain_segments: list[str | int] = []
    for segment in path:
        if isinstance(segment, (str, int)):
            plain_segments.append(segment)
        else:
            plain_segments.append(str(segment))
    return plain_segments


__all__ = [
    "ARTIFACT_SAFE_FINGERPRINT_LABEL",
    "ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION",
    "ARTIFACT_SAFE_FINGERPRINT_POLICY",
    "ARTIFACT_SAFE_RUNTIME_REPLAY",
    "ConfigFingerprintComparison",
    "FingerprintComparisonStatus",
    "build_artifact_safe_config_fingerprint_payload",
    "build_artifact_safe_config_fingerprint_record",
    "compare_config_artifact_fingerprints",
]
