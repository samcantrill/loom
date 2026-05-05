"""Unit tests for configuration artifact contracts."""

import pytest
from typing import cast
from loom.serialization import PlainData

from loom.config.artifacts import (
    SCHEMA_VERSION,
    CompositionManifest,
    ConfigFingerprintRecord,
    SourceArtifactRecord,
)
from loom.config.errors import ConfigProvenanceError


def test_source_artifact_round_trip() -> None:
    record = SourceArtifactRecord(
        schema_version=SCHEMA_VERSION,
        kind="base",
        path="/tmp/base.yaml",
        order=0,
        content_digest="sha256:abcd",
        size_bytes=12,
        metadata={"nested": {"a": [1, 2, 3]}},
    )
    assert SourceArtifactRecord.from_dict(record.to_dict()) == record


def test_source_artifact_defaults_round_trip() -> None:
    record = SourceArtifactRecord(
        schema_version=SCHEMA_VERSION,
        kind="overlay",
        path="/tmp/overlay.yaml",
        order=1,
        content_digest="sha256:def0",
        size_bytes=3,
    )
    payload = record.to_dict()
    assert payload["metadata"] == {}
    assert SourceArtifactRecord.from_dict(payload) == record


def test_source_artifact_future_source_roles_round_trip() -> None:
    for kind in ("include", "recipe"):
        record = SourceArtifactRecord(
            schema_version=SCHEMA_VERSION,
            kind=kind,
            path=f"/tmp/{kind}.yaml",
            order=2,
            content_digest="sha256:feed",
            size_bytes=8,
        )
        assert SourceArtifactRecord.from_dict(record.to_dict()) == record


def test_source_artifact_rejects_unknown_kind() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "runtime",
        "path": "/tmp/runtime.yaml",
        "order": 0,
        "content_digest": "sha256:beef",
        "size_bytes": 4,
    }
    with pytest.raises(ConfigProvenanceError, match="kind"):
        SourceArtifactRecord.from_dict(payload)


def test_config_fingerprint_record_round_trip() -> None:
    record = ConfigFingerprintRecord(
        schema_version=SCHEMA_VERSION,
        digest="sha256:aaaa",
        label="expanded",
        metadata={"k": "v"},
    )
    assert ConfigFingerprintRecord.from_dict(record.to_dict()) == record


def test_composition_manifest_round_trip_minimal() -> None:
    source_artifact = SourceArtifactRecord(
        schema_version=SCHEMA_VERSION,
        kind="base",
        path="/tmp/base.yaml",
        order=0,
        content_digest="sha256:abcd",
        size_bytes=12,
    )
    fingerprint_record = ConfigFingerprintRecord(
        schema_version=SCHEMA_VERSION,
        digest="sha256:bbbb",
        label="resolved",
    )
    manifest = CompositionManifest(
        schema_version=SCHEMA_VERSION,
        source_artifacts=(source_artifact,),
        fingerprint_records=(fingerprint_record,),
        recipe_manifest=({"path": "pipeline", "name": "demo", "tags": ["base"]},),
        metadata={"run": {"id": "local"}},
    )

    round_trip = CompositionManifest.from_dict(manifest.to_dict())
    assert round_trip == manifest
    assert isinstance(round_trip.source_artifacts, tuple)
    assert isinstance(round_trip.fingerprint_records, tuple)
    assert manifest.to_dict()["recipe_manifest"] == [
        {"path": "pipeline", "name": "demo", "tags": ["base"]}
    ]
    recipe_entry = cast(dict[str, PlainData], manifest.recipe_manifest[0])
    with pytest.raises(TypeError):
        recipe_entry["path"] = "other"


def test_composition_manifest_rejects_non_plain_recipe_manifest_at_construction() -> None:
    with pytest.raises(ConfigProvenanceError, match="recipe_manifest"):
        CompositionManifest(
            schema_version=SCHEMA_VERSION,
            recipe_manifest=(cast(dict[str, PlainData], {"bad": {1, 2}}),),
        )


def test_composition_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ConfigProvenanceError, match="unknown"):
        CompositionManifest.from_dict(
            {
                "schema_version": SCHEMA_VERSION,
                "extra": 1,
            }
        )


def test_config_artifact_metadata_must_be_plain_data() -> None:
    with pytest.raises(ConfigProvenanceError):
        invalid_metadata = cast(dict[str, PlainData], {"value": {1: "x"}})
        CompositionManifest(
            schema_version=SCHEMA_VERSION,
            metadata=invalid_metadata,
        )
