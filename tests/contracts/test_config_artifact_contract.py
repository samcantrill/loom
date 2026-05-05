"""Contract tests for phase-1 configuration artifact records."""

from typing import cast

import pytest

from loom.config.artifacts import CompositionManifest, ConfigFingerprintRecord, SourceArtifactRecord
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
        recipe_manifest=({"path": "pipeline"},),
    )
    assert CompositionManifest.from_dict(manifest.to_dict()) == manifest


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
        resolved_fingerprint="sha256:abcd",
        recipe_manifest_count=0,
        metadata={},
    )
    payload = provenance.to_dict()
    assert ConfigProvenance.from_dict(payload) == provenance


def test_config_fingerprint_record_rejects_non_mapping_metadata() -> None:
    payload = _example_fingerprint().to_dict()
    payload["metadata"] = [1, 2, 3]
    with pytest.raises(ConfigProvenanceError):
        ConfigFingerprintRecord.from_dict(payload)
