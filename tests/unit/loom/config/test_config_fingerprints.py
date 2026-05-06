"""Unit tests for artifact-safe fingerprint payloads and comparisons."""

from pathlib import Path
from typing import Any, cast

from loom.config.artifacts import ConfigFingerprintRecord, SourceArtifactRecord, SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION
from loom.config.fingerprints import (
    ARTIFACT_SAFE_FINGERPRINT_LABEL,
    ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION,
    ARTIFACT_SAFE_FINGERPRINT_POLICY,
    ARTIFACT_SAFE_RUNTIME_REPLAY,
    build_artifact_safe_config_fingerprint_payload,
    build_artifact_safe_config_fingerprint_record,
    compare_config_artifact_fingerprints,
)
from loom.config.includes import IncludeSiteRecord
from loom.config.interpolation import ResolverExpressionRecord
from loom.config.provenance import ParsedOverride


def _source_artifacts(base_path: str) -> tuple[SourceArtifactRecord, SourceArtifactRecord]:
    return (
        SourceArtifactRecord(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            kind="base",
            path=f"{base_path}/base.yaml",
            order=0,
            content_digest="sha256:base",
            size_bytes=20,
        ),
        SourceArtifactRecord(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            kind="include",
            path=f"{base_path}/include.yaml",
            order=1,
            content_digest="sha256:include",
            size_bytes=10,
            metadata={
                "include_site_path": ["pipeline", "model"],
                "authored_target": "./nested.yaml",
                "source_path": f"{base_path}/base.yaml",
                "source_kind": "base",
                "source_order": 0,
                "source_content_digest": "sha256:base-include",
                "source_size_bytes": 20,
                "source_include_site_path": ["pipeline"],
                "target_kind": "explicit_relative",
                "explicit_escape": False,
                "has_replace_marker": False,
            },
        ),
    )


def _include_sites(base_path: str) -> tuple[IncludeSiteRecord, ...]:
    return (
        IncludeSiteRecord(
            include_site_path=("pipeline", "model"),
            authored_target="./nested.yaml",
            source_path=f"{base_path}/base.yaml",
            source_kind="base",
            source_order=0,
            source_include_site_path=("pipeline",),
            source_content_digest="sha256:base",
            source_size_bytes=20,
            resolved_path=str(Path(f"{base_path}/nested.yaml")),
            included_content_digest="sha256:include-content",
            included_size_bytes=10,
            target_kind="explicit_relative",
            explicit_escape=False,
            has_replace_marker=False,
        ),
    )


def _resolver_records() -> tuple[ResolverExpressionRecord, ...]:
    return (
        ResolverExpressionRecord(
            config_path="$.pipeline.paths",
            token="${paths.root}",
            resolver="oc.env",
            expression="oc.env:PHASE14_ROOT",
        ),
    )


def test_artifact_safe_payload_is_portable_across_absolute_source_paths() -> None:
    payload_one = build_artifact_safe_config_fingerprint_payload(
        unresolved={"pipeline": {"value": "${paths.root}"}},
        redacted={"pipeline": {"value": "${paths.root}"}},
        source_artifacts=_source_artifacts("/tmp/root-a"),
        include_sites=_include_sites("/tmp/root-a"),
        include_overrides=(),
        ordinary_overrides=(),
        recipe_manifest=(),
        resolver_records=_resolver_records(),
        redaction_policy={"policy": "strict"},
    )
    payload_two = build_artifact_safe_config_fingerprint_payload(
        unresolved={"pipeline": {"value": "${paths.root}"}},
        redacted={"pipeline": {"value": "${paths.root}"}},
        source_artifacts=_source_artifacts("/other/tmp/root-b"),
        include_sites=_include_sites("/other/tmp/root-b"),
        include_overrides=(),
        ordinary_overrides=(),
        recipe_manifest=(),
        resolver_records=_resolver_records(),
        redaction_policy={"policy": "strict"},
    )

    assert payload_one == payload_two
    assert payload_one["fingerprint_policy"] == ARTIFACT_SAFE_FINGERPRINT_POLICY
    assert payload_one["payload_schema_version"] == ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION
    assert payload_one["runtime_value_replay"] == ARTIFACT_SAFE_RUNTIME_REPLAY
    assert payload_one["resolver_outputs_included"] is False
    assert payload_one["raw_source_bytes_included"] is False


def test_artifact_safe_record_includes_redacted_overrides_and_resolver_facts() -> None:
    record = build_artifact_safe_config_fingerprint_record(
        unresolved={"pipeline": {"secret_token": "keep-secret"}},
        redacted={"pipeline": {"secret_token": "***REDACTED***"}},
        source_artifacts=_source_artifacts("/tmp/root-a"),
        include_sites=_include_sites("/tmp/root-a"),
        include_overrides=(
            ParsedOverride(
                raw="pipeline.secret_token=sauce",
                path="pipeline.secret_token",
                operation="add",
                value="sauce",
                order=0,
            ),
        ),
        ordinary_overrides=(
            ParsedOverride(
                raw="pipeline.token_parent.value=sauce",
                path="pipeline.token_parent.value",
                operation="update",
                value="sauce",
                order=0,
            ),
        ),
        recipe_manifest=(),
        resolver_records=_resolver_records(),
        redaction_policy={"policy": "strict"},
    )

    assert record.label == ARTIFACT_SAFE_FINGERPRINT_LABEL
    assert record.metadata["fingerprint_policy"] == ARTIFACT_SAFE_FINGERPRINT_POLICY
    assert record.metadata["runtime_values_included"] is False
    include_overrides = cast(list[dict[str, Any]], record.metadata["include_overrides"])
    ordinary_overrides = cast(list[dict[str, Any]], record.metadata["ordinary_overrides"])
    assert include_overrides[0]["redacted"] is True
    assert include_overrides[0]["raw"] == "***REDACTED***"
    assert ordinary_overrides[0]["redacted"] is True
    assert ordinary_overrides[0]["raw"] == "***REDACTED***"
    assert ordinary_overrides[0]["value"] == "***REDACTED***"
    resolver_facts = cast(list[dict[str, Any]], record.metadata["resolver_facts"])
    assert len(resolver_facts) == 1


def _build_record(
    *,
    unresolved_value: str,
    path: str = "/tmp/root",
) -> ConfigFingerprintRecord:
    return build_artifact_safe_config_fingerprint_record(
        unresolved={"pipeline": {"value": unresolved_value}},
        redacted={"pipeline": {"value": unresolved_value}},
        source_artifacts=_source_artifacts(path),
        include_sites=_include_sites(path),
        include_overrides=(),
        ordinary_overrides=(),
        recipe_manifest=(),
        resolver_records=_resolver_records(),
        redaction_policy={},
    )


def test_compare_config_artifact_fingerprints_status_matrix() -> None:
    left = _build_record(unresolved_value="${paths.root}", path="/tmp/root")
    right = _build_record(unresolved_value="${paths.root}", path="/tmp/root")
    assert compare_config_artifact_fingerprints(left=left, right=right).status == "match"

    changed = _build_record(unresolved_value="${paths.root}/changed", path="/tmp/root")
    mismatch = compare_config_artifact_fingerprints(left=left, right=changed)
    assert mismatch.status == "mismatch"
    assert mismatch.runtime_values_replayed is False
    assert mismatch.left_payload_schema_version == ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION

    incompatible = ConfigFingerprintRecord(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        digest=left.digest,
        metadata={},
    )
    incompatible_result = compare_config_artifact_fingerprints(left=left, right=incompatible)
    assert incompatible_result.status == "incompatible_policy"

    missing = compare_config_artifact_fingerprints(
        left=left,
        right={"schema_version": "bad"},
    )
    assert missing.status == "insufficient_data"

    manifest_map = {
        "schema_version": 1,
        "fingerprint_records": [left.to_dict()],
        "source_artifacts": (),
    }
    plain_result = compare_config_artifact_fingerprints(left=left, right=manifest_map)
    assert plain_result.status == "match"


def test_compare_config_artifact_fingerprints_reports_wrong_label_mapping_as_incompatible() -> None:
    left = _build_record(unresolved_value="${paths.root}", path="/tmp/root")
    wrong_label_mapping = left.to_dict()
    wrong_label_mapping["label"] = "resolved"

    comparison = compare_config_artifact_fingerprints(left=left, right=wrong_label_mapping)

    assert comparison.status == "incompatible_policy"
    assert comparison.right_record_label == "resolved"
    assert comparison.reason == "Unexpected fingerprint label"


def test_compare_config_artifact_fingerprints_handles_malformed_mapping_as_insufficient_data() -> None:
    left = _build_record(unresolved_value="${paths.root}", path="/tmp/root")
    malformed = cast(
        dict[str, Any],
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "digest": "sha256:abc",
            "label": ARTIFACT_SAFE_FINGERPRINT_LABEL,
            "metadata": object(),
        },
    )

    comparison = compare_config_artifact_fingerprints(left=left, right=malformed)

    assert comparison.status == "insufficient_data"
    assert comparison.right_digest is None
