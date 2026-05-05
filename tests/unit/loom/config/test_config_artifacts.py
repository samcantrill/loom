"""Unit tests for configuration artifact contracts."""

import pytest
from typing import cast
from loom.serialization import PlainData

from loom.config.artifacts import (
    SCHEMA_VERSION,
    RawSourceSnapshotBundle,
    RawSourceSnapshotPayload,
    RawSourceSnapshotReference,
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


def test_raw_source_snapshot_payload_round_trip() -> None:
    payload = RawSourceSnapshotPayload(
        payload_id="sha256:abc:3",
        content="a: 1\n",
        content_digest="sha256:abc",
        size_bytes=3,
        metadata={"source": "base"},
    )

    serialized = payload.to_dict()
    assert serialized["encoding"] == "utf-8"
    assert RawSourceSnapshotPayload.from_dict(serialized) == payload


def test_raw_source_snapshot_reference_round_trip() -> None:
    reference = RawSourceSnapshotReference(
        kind="base",
        order=0,
        path="/tmp/base.yaml",
        content_digest="sha256:abc",
        size_bytes=3,
        availability="available",
        payload_id="sha256:abc:3",
        reason="requested",
    )

    serialized = reference.to_dict()
    assert serialized["payload_id"] == "sha256:abc:3"
    assert RawSourceSnapshotReference.from_dict(serialized) == reference


def test_raw_source_snapshot_bundle_round_trip() -> None:
    bundle = RawSourceSnapshotBundle(
        schema_version=SCHEMA_VERSION,
        enabled=True,
        payloads=(
            RawSourceSnapshotPayload(
                payload_id="sha256:abc:3",
                content="a: 1\n",
                content_digest="sha256:abc",
                size_bytes=3,
            ),
        ),
        references=(
            RawSourceSnapshotReference(
                kind="base",
                order=0,
                path="/tmp/base.yaml",
                content_digest="sha256:abc",
                size_bytes=3,
                availability="available",
                payload_id="sha256:abc:3",
                reason="requested",
            ),
            RawSourceSnapshotReference(
                kind="recipe",
                order=1,
                path="/tmp/recipe.py",
                content_digest="sha256:def",
                size_bytes=4,
                availability="unavailable",
                payload_id=None,
                reason="unsupported_source_kind",
            ),
        ),
        metadata={"request": True},
    )

    serialized = bundle.to_dict()
    assert set(serialized.keys()) == {"schema_version", "enabled", "payloads", "references", "metadata"}
    references = cast(list[dict[str, object]], serialized["references"])
    assert references[1]["payload_id"] is None
    assert references[1]["reason"] == "unsupported_source_kind"
    assert RawSourceSnapshotBundle.from_dict(serialized) == bundle
