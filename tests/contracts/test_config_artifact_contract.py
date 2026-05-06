"""Contract tests for phase-1 configuration artifact records."""

from typing import cast

import pytest

from loom.config.artifacts import (
    CompositionManifest,
    ConfigFingerprintRecord,
    RawSourceSnapshotBundle,
    RawSourceSnapshotPayload,
    RawSourceSnapshotReference,
    SourceArtifactRecord,
)
from loom.config.errors import ConfigProvenanceError
from loom.config.provenance import ConfigProvenance, ConfigSource, ParsedOverride, SCHEMA_VERSION
from loom.config.fingerprints import (
    ARTIFACT_SAFE_FINGERPRINT_LABEL,
    ARTIFACT_SAFE_FINGERPRINT_POLICY,
    ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION,
)


def _example_source() -> SourceArtifactRecord:
    return SourceArtifactRecord(
        schema_version=1,
        kind="base",
        path="/tmp/base.yaml",
        order=0,
        content_digest="sha256:1234",
        size_bytes=10,
    )


def _example_fingerprint() -> ConfigFingerprintRecord:
    return ConfigFingerprintRecord(schema_version=1, digest="sha256:abcd")


def test_composition_manifest_contract_round_trip() -> None:
    manifest = CompositionManifest(
        schema_version=1,
        source_artifacts=(_example_source(),),
        fingerprint_records=(_example_fingerprint(),),
        recipe_manifest=({"path": "workflow"},),
    )
    assert CompositionManifest.from_dict(manifest.to_dict()) == manifest


def test_composition_manifest_to_dict_thaws_nested_recipe_manifest_plain_data() -> None:
    manifest = CompositionManifest(
        schema_version=1,
        recipe_manifest=(
            {
                "path": "workflow.processor",
                "arguments": {"name": "normalize", "input": "dataset"},
            },
        ),
    )

    payload = manifest.to_dict()

    recipe_manifest = cast(list[dict[str, object]], payload["recipe_manifest"])
    assert recipe_manifest == [
        {
            "path": "workflow.processor",
            "arguments": {"name": "normalize", "input": "dataset"},
        }
    ]
    assert CompositionManifest.from_dict(payload) == manifest


def test_source_artifact_contract_plain_data_shape() -> None:
    record = _example_source()
    payload = record.to_dict()
    assert payload["schema_version"] == 1
    assert set(payload.keys()) == {
        "schema_version",
        "kind",
        "path",
        "order",
        "content_digest",
        "size_bytes",
        "metadata",
    }
    assert record == SourceArtifactRecord.from_dict(payload)


def test_source_artifact_contract_includes_future_source_roles() -> None:
    include_record = SourceArtifactRecord(
        schema_version=1,
        kind="include",
        path="/tmp/model/resnet.yaml",
        order=1,
        content_digest="sha256:5678",
        size_bytes=20,
    )
    recipe_record = SourceArtifactRecord(
        schema_version=1,
        kind="recipe",
        path="/tmp/recipes.py",
        order=2,
        content_digest="sha256:9012",
        size_bytes=30,
    )

    assert SourceArtifactRecord.from_dict(include_record.to_dict()) == include_record
    assert SourceArtifactRecord.from_dict(recipe_record.to_dict()) == recipe_record


def test_raw_source_snapshot_contract_round_trip() -> None:
    bundle = RawSourceSnapshotBundle(
        schema_version=1,
        enabled=False,
        payloads=(
            RawSourceSnapshotPayload(
                payload_id="sha256:base:10",
                content="value: base\n",
                content_digest="sha256:base",
                size_bytes=10,
            ),
        ),
        references=(
            RawSourceSnapshotReference(
                kind="base",
                order=0,
                path="/tmp/base.yaml",
                content_digest="sha256:base",
                size_bytes=10,
                availability="available",
                payload_id="sha256:base:10",
                reason="requested",
            ),
            RawSourceSnapshotReference(
                kind="recipe",
                order=1,
                path="workflow",
                content_digest="sha256:recipe",
                size_bytes=7,
                availability="unavailable",
                payload_id=None,
                reason="unsupported_source_kind",
            ),
            RawSourceSnapshotReference(
                kind="overlay",
                order=2,
                path="/tmp/overlay.yaml",
                content_digest="sha256:overlay",
                size_bytes=11,
                availability="disabled",
                payload_id=None,
                reason="not_requested",
            ),
        ),
        metadata={"request": False},
    )

    payload = bundle.to_dict()
    assert payload["schema_version"] == 1
    assert payload["enabled"] is False
    payloads = cast(list[dict[str, object]], payload["payloads"])
    references = cast(list[dict[str, object]], payload["references"])
    assert len(payloads) == 1
    assert len(references) == 3
    assert references[2]["payload_id"] is None

    round_trip = RawSourceSnapshotBundle.from_dict(payload)
    assert round_trip == bundle


def test_config_fingerprint_record_contract_round_trip() -> None:
    record = _example_fingerprint()
    payload = record.to_dict()
    assert payload["algorithm"] == "sha256"
    assert payload["label"] == "resolved"
    assert record == ConfigFingerprintRecord.from_dict(payload)


def test_artifact_safe_fingerprint_record_contract_round_trip() -> None:
    record = ConfigFingerprintRecord(
        schema_version=1,
        digest="sha256:abcd",
        label=ARTIFACT_SAFE_FINGERPRINT_LABEL,
    metadata={
            "fingerprint_policy": ARTIFACT_SAFE_FINGERPRINT_POLICY,
            "payload_schema_version": ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION,
            "semantic_scope": "authored_composition",
        },
    )
    payload = record.to_dict()
    assert payload["label"] == ARTIFACT_SAFE_FINGERPRINT_LABEL
    fingerprint_metadata = cast(dict[str, object], payload["metadata"])
    assert fingerprint_metadata["fingerprint_policy"] == ARTIFACT_SAFE_FINGERPRINT_POLICY
    assert (
        cast(int, fingerprint_metadata["payload_schema_version"])
        == ARTIFACT_SAFE_FINGERPRINT_PAYLOAD_VERSION
    )
    assert ConfigFingerprintRecord.from_dict(payload) == record


def test_config_provenance_contract_is_still_round_trippable() -> None:
    provenance = ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path="/tmp/base.yaml",
        sources=(
            ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=12),
        ),
        overrides=(
            ParsedOverride(raw="a=1", path="a", operation="update", value=1, order=0),
        ),
        recipe_manifest_count=0,
        metadata={"fingerprint": {"resolved_runtime_fingerprint_included": False}},
        artifact_fingerprint="sha256:artifact",
    )
    payload = provenance.to_dict()
    assert payload["schema_version"] == 2
    assert payload["artifact_fingerprint"] == "sha256:artifact"
    assert "resolved_fingerprint" not in payload
    assert ConfigProvenance.from_dict(payload) == provenance


def test_config_provenance_contract_reads_legacy_v1_resolved_fingerprint() -> None:
    payload = {
        "schema_version": 1,
        "config_path": "/tmp/base.yaml",
        "sources": (
            {
                "kind": "base",
                "path": "/tmp/base.yaml",
                "order": 0,
                "content_digest": "sha256:abcd",
                "size_bytes": 12,
            },
        ),
        "overrides": (),
        "resolved_fingerprint": "sha256:legacy",
        "recipe_manifest_count": 0,
        "metadata": {},
    }

    provenance = ConfigProvenance.from_dict(payload)

    assert provenance.schema_version == 1
    assert provenance.artifact_fingerprint is None
    assert provenance.metadata["legacy_resolved_fingerprint"] == "sha256:legacy"
    serialized = provenance.to_dict()
    serialized_metadata = cast(dict[str, object], serialized["metadata"])
    assert "resolved_fingerprint" not in serialized
    assert serialized_metadata["legacy_resolved_fingerprint"] == "sha256:legacy"


def test_config_provenance_contract_v2_rejects_resolved_fingerprint() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "config_path": "/tmp/base.yaml",
        "sources": (),
        "overrides": (),
        "artifact_fingerprint": "sha256:artifact",
        "resolved_fingerprint": "sha256:legacy",
        "recipe_manifest_count": 0,
        "metadata": {},
    }

    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigProvenance.from_dict(payload)

    serialized = exc.value.to_dict()
    context = cast(dict[str, object], serialized["context"])
    assert context["code"] == "config_provenance_unknown_fields"
    assert context["config_path"] == "ConfigProvenance"


def test_config_provenance_error_context_contract_for_from_dict_failures() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "config_path": "/tmp/base.yaml",
        "sources": (),
        "overrides": (),
        "artifact_fingerprint": "sha256:artifact",
        "recipe_manifest_count": 0,
        "metadata": [],
    }

    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigProvenance.from_dict(payload)

    serialized = exc.value.to_dict()
    context = cast(dict[str, object], serialized["context"])
    details = cast(dict[str, object], context["details"])
    assert context["code"] == "invalid_config_provenance_metadata"
    assert context["source_kind"] == "provenance"
    assert context["config_path"] == "ConfigProvenance.metadata"
    assert context["actual"] == "sequence"
    assert details["stage"] == "provenance_from_dict"


def test_config_fingerprint_record_rejects_non_mapping_metadata() -> None:
    payload = _example_fingerprint().to_dict()
    payload["metadata"] = [1, 2, 3]
    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigFingerprintRecord.from_dict(payload)
    serialized = exc.value.to_dict()
    context = cast(dict[str, object], serialized["context"])
    details = cast(dict[str, object], context["details"])
    assert context["code"] == "config_fingerprint_metadata_not_mapping"
    assert context["source_kind"] == "artifact"
    assert context["config_path"] == "ConfigFingerprintRecord.metadata"
    assert details["stage"] == "artifact_from_dict"
