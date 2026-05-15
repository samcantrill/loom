"""Contract tests for external artifact records."""

from typing import Any, cast

import pytest

from loom.artifacts import (
    ArtifactAddress,
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ArtifactValidationError,
    ExternalArtifactDeclaration,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
    PublishedArtifactRecord,
)


def _location_summary() -> ArtifactLocationSummary:
    return ArtifactLocationSummary(
        schema_version=1,
        kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
        authority="authoritative",
        uri="s3://secret.example/bucket/model.pt",
        display_uri="s3://***redacted***/bucket/model.pt",
        checksum="sha256:" + "a" * 64,
        fingerprint="sha256:" + "b" * 64,
        size_bytes=1024,
        details={"transport": {"ssl": True}},
    )


def test_artifact_location_kind_values_contract() -> None:
    assert set(v.value for v in ArtifactLocationKind) == {
        "managed",
        "external_immutable",
        "published_immutable",
        "staging",
        "cache",
        "materialized",
    }


def test_artifact_store_ref_shape_and_field_set() -> None:
    summary = ArtifactStoreRef(
        schema_version=1,
        kind="local-cache",
        key="cache-v1",
        uri="file:///tmp/cache/model.pt",
        display_uri="file:///tmp/cache/model.pt",
        details={"path_prefix": "/tmp"},
    )
    payload = summary.to_dict()

    assert set(payload.keys()) == {
        "schema_version",
        "kind",
        "key",
        "uri",
        "display_uri",
        "details",
    }
    assert payload["schema_version"] == 1
    assert payload["kind"] == "local-cache"
    assert payload["details"] == {"path_prefix": "/tmp"}
    assert ArtifactStoreRef.from_dict(payload) == summary


def test_artifact_store_ref_rejects_non_plain_details() -> None:
    with pytest.raises(ArtifactValidationError):
        ArtifactStoreRef(
            schema_version=1,
            kind="local-cache",
            details=cast(Any, {"bad": {1: "x"}}),
        )


def test_artifact_location_summary_shape_and_authority_rules() -> None:
    payload = {
        "schema_version": 1,
        "kind": ArtifactLocationKind.MANAGED.value,
        "authority": "authoritative",
        "uri": "file:///a",
        "display_uri": "file:///a",
        "store": {
            "schema_version": 1,
            "kind": "local",
            "key": "local",
            "details": {},
        },
        "checksum": "sha256:" + "c" * 64,
        "fingerprint": "sha256:" + "d" * 64,
        "size_bytes": 512,
        "details": {"owner": "team"},
    }
    location = ArtifactLocationSummary.from_dict(payload)
    assert location.kind.value == "managed"
    assert location.authority == "authoritative"

    payload["authority"] = "derived"
    assert ArtifactLocationSummary.from_dict(payload).authority == "derived"

    payload["authority"] = "authoritative"
    payload["kind"] = ArtifactLocationKind.STAGING.value
    with pytest.raises(ArtifactValidationError):
        ArtifactLocationSummary.from_dict(payload)


def test_external_declaration_shape_and_immutability_contract() -> None:
    declaration = ExternalArtifactDeclaration(
        schema_version=1,
        artifact_id="artifact:checkpoint",
        uri="s3://secret.example/checkpoint.pt",
        artifact_type="checkpoint",
        artifact_schema_version=3,
        codec_key="torch",
        location=_location_summary(),
        immutability="validated",
        metadata={"owner": "team"},
        details={"backend": "mock"},
        store=ArtifactStoreRef(
            schema_version=1,
            kind="tracking-store",
            display_uri="s3://***redacted***/store",
        ),
    )
    payload = declaration.to_dict()

    assert set(payload.keys()) == {
        "schema_version",
        "artifact_id",
        "uri",
        "artifact_type",
        "codec_key",
        "artifact_schema_version",
        "store",
        "location",
        "checksum",
        "fingerprint",
        "immutability",
        "metadata",
        "details",
    }
    assert payload["immutability"] == "validated"
    assert declaration == ExternalArtifactDeclaration.from_dict(payload)


def test_published_record_requires_plain_metadata_maps_and_lookup_projection() -> None:
    published = PublishedArtifactRecord(
        schema_version=1,
        artifact_id="artifact:checkpoint",
        uri="s3://secret.example/checkpoint.pt",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        producer_run_uri="file:///runs/run-1",
        producer_stage="train",
        producer_artifact_id="artifact:source",
        reuse_key="reuse-1",
        validation_policy={"min_size": 1},
        owner={"name": "team"},
        retention={"days": 14},
        evidence={"policy_checked": True},
        metadata={"project": "demo"},
        details={"origin": "contract"},
    )
    payload = published.to_dict()
    assert set(payload.keys()) >= {
        "schema_version",
        "artifact_id",
        "uri",
        "artifact_type",
        "artifact_schema_version",
        "producer_run_uri",
        "producer_stage",
        "producer_artifact_id",
        "reuse_key",
        "validation_policy",
        "owner",
        "retention",
        "evidence",
    }
    assert PublishedArtifactRecord.from_dict(payload) == published

    with pytest.raises(ArtifactValidationError):
        PublishedArtifactRecord.from_dict({**payload, "validation_policy": []})


def test_lookup_request_result_contract_and_statuses() -> None:
    request = ImmutableArtifactLookupRequest(
        schema_version=1,
        reuse_key="reuse-1",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        validation_policy={"policy": {"mode": "strict"}},
        store=ArtifactStoreRef(
            schema_version=1,
            kind="object-cache",
            display_uri="file:///cache",
        ),
        details={"cache_hint": "enabled"},
    )
    request_payload = request.to_dict()
    assert request_payload["schema_version"] == 1
    assert request_payload["store"]["kind"] == "object-cache"

    result = ImmutableArtifactLookupResult(
        schema_version=1,
        status="compatible",
        request=request,
        diagnostics={"mode": "cache"},
        details={"attempted": False},
    )
    assert set(result.to_dict().keys()) == {
        "schema_version",
        "status",
        "request",
        "published",
        "location",
        "diagnostics",
        "details",
    }
    assert result == ImmutableArtifactLookupResult.from_dict(result.to_dict())

    for status in ("compatible", "incompatible", "missing", "unsupported"):
        result = ImmutableArtifactLookupResult(
            schema_version=1,
            status=status,
            request=request,
            diagnostics={},
            details={},
        )
        assert result.to_dict()["status"] == status

    with pytest.raises(ArtifactValidationError):
        ImmutableArtifactLookupResult.from_dict(
            {
                "schema_version": 1,
                "status": "not-a-status",
                "request": request_payload,
                "published": None,
                "location": None,
                "diagnostics": {},
                "details": {},
            }
        )


def test_phase_1_round_trip_preserves_artifact_ref_contract() -> None:
    legacy_payload = {
        "artifact_id": "model:best",
        "uri": "file:///artifact.pt",
        "artifact_type": "checkpoint",
        "checksum": "sha256:" + "e" * 64,
        "fingerprint": "sha256:" + "f" * 64,
        "metadata": {"project": "demo"},
    }
    legacy = ArtifactRef.from_dict(legacy_payload)
    assert legacy == ArtifactRef.from_dict(legacy.to_dict())

    address = ArtifactAddress(run_uri="file:///run", artifact_id="artifact:best")
    assert ArtifactAddress.from_dict(address.to_dict()) == address


def test_display_uri_contract_is_separate_from_storage_uri() -> None:
    store = ArtifactStoreRef(
        schema_version=1,
        kind="object-store",
        uri="s3://token:secret@example.com/model.pt",
        display_uri="s3://***redacted***/model.pt",
    )
    payload = store.to_dict()
    assert payload["uri"] != payload["display_uri"]

    location = ArtifactLocationSummary(
        schema_version=1,
        kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
        authority="authoritative",
        uri="s3://token:secret@example.com/model.pt",
        display_uri="s3://***redacted***/model.pt",
        store=store,
        details={},
    )
    assert location.to_summary()["display_uri"] == "s3://***redacted***/model.pt"
    assert location.to_summary()["uri"].startswith("s3://token:")
