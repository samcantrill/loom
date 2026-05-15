"""Unit tests for artifact references."""

from collections.abc import Mapping
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
from loom.fingerprints import hash_text
from loom.serialization import PlainData


def test_artifact_ref_to_dict_from_dict_round_trip() -> None:
    ref = ArtifactRef(
        artifact_id="model:best",
        uri="file:///artifacts/model.pt",
        artifact_type="checkpoint",
        checksum="sha256:" + "b" * 64,
        fingerprint="sha256:" + "c" * 64,
        schema_version=1,
        metadata=cast(
            dict[str, PlainData],
            {"training": {"epoch": 42, "labels": ["best", "candidate"]}},
        ),
    )

    restored = ArtifactRef.from_dict(ref.to_dict())
    assert restored == ref
    assert restored.to_dict()["checksum"] == ref.checksum
    assert restored.to_dict()["fingerprint"] == ref.fingerprint


def test_artifact_ref_preserves_created_and_metadata() -> None:
    data = {
        "artifact_id": "model:best",
        "uri": "file:///a",
        "artifact_type": "checkpoint",
        "created_at": "2026-05-03T12:34:56Z",
        "metadata": {"foo": "bar"},
    }
    ref = ArtifactRef.from_dict(data)
    assert ref.created_at == "2026-05-03T12:34:56Z"
    assert ref.metadata["foo"] == "bar"


def test_artifact_ref_preserves_positive_schema_version_compatibility() -> None:
    ref = ArtifactRef.from_dict(
        {
            "artifact_id": "model:best",
            "uri": "file:///a",
            "artifact_type": "checkpoint",
            "schema_version": 2,
        }
    )

    assert ref.schema_version == 2


def test_artifact_ref_checks_checksum_and_fingerprint_distinct() -> None:
    ref = ArtifactRef(
        artifact_id="artifact:1",
        uri="file:///a",
        artifact_type="text",
        checksum=hash_text("payload-a"),
        fingerprint=hash_text("payload-b"),
    )
    assert ref.checksum != ref.fingerprint


def test_artifact_ref_rejects_invalid() -> None:
    with pytest.raises(ArtifactValidationError):
        ArtifactRef.from_dict({"uri": "file:///a", "artifact_type": "text"})
    with pytest.raises(ArtifactValidationError):
        ArtifactRef(
            artifact_id="a",
            uri="file:///a",
            artifact_type="text",
            created_at="not-a-timestamp",
        )
    with pytest.raises(ArtifactValidationError):
        ArtifactRef.from_dict(
            {
                "artifact_id": "a",
                "artifact_type": "text",
                "uri": "file:///a",
                "extra": True,
            }
        )


def test_artifact_ref_has_no_loading_behavior() -> None:
    ref = ArtifactRef(artifact_id="a", uri="file:///a", artifact_type="text")
    assert not hasattr(ref, "load")
    assert not hasattr(ref, "save")


def test_artifact_ref_metadata_is_immutable_and_to_dict_mutations_are_local() -> None:
    source_metadata: dict[str, Any] = {"labels": ["raw", "processed"]}
    ref = ArtifactRef(
        artifact_id="artifact:1",
        uri="file:///artifact",
        artifact_type="checkpoint",
        metadata=cast(dict[str, PlainData], source_metadata),
    )

    source_metadata["labels"].append("archived")
    assert ref.metadata["labels"] == ("raw", "processed")
    with pytest.raises(TypeError):
        cast(Any, ref.metadata["labels"])[0] = "manual"
    with pytest.raises(TypeError):
        cast(Any, ref.metadata)["new"] = "value"

    snapshot = cast(dict[str, Any], ref.to_dict())
    snapshot["metadata"]["labels"].append("archived")
    snapshot["metadata"]["extra"] = "value"

    assert ref.metadata["labels"] == ("raw", "processed")
    assert "extra" not in ref.metadata


def test_artifact_address_round_trip() -> None:
    address = ArtifactAddress(
        run_uri="file:///abs/project/runs/run-1", artifact_id="artifact:best"
    )
    restored = ArtifactAddress.from_dict(address.to_dict())

    assert restored == address
    assert restored.to_dict() == {
        "run_uri": "file:///abs/project/runs/run-1",
        "artifact_id": "artifact:best",
    }


def test_artifact_address_rejects_invalid_payloads() -> None:
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress.from_dict({"run_uri": "file:///abs/project/runs/run-1"})
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress.from_dict(
            {
                "run_uri": "file:///abs/project/runs/run-1",
                "artifact_id": "artifact:best",
                "unexpected": 1,
            }
        )
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress.from_dict({"run_id": "run-1", "artifact_id": "artifact:best"})
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress.from_dict("bad")
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress(run_uri="", artifact_id="artifact:best")
    with pytest.raises(ArtifactValidationError):
        ArtifactAddress.from_dict(
            {"run_uri": "file:///abs/project/runs/run-1", "artifact_id": ""}
        )


def test_artifact_store_ref_round_trip_and_summary_shape() -> None:
    store = ArtifactStoreRef(
        schema_version=1,
        kind="tracking-store",
        key="model-registry",
        uri="s3://secret.example/bucket/path/model.pt",
        display_uri="s3://***redacted***/path/model.pt",
        details={"provider": "mock", "region": "au"},
    )

    payload = store.to_dict()
    assert payload["schema_version"] == 1
    assert payload["kind"] == "tracking-store"
    assert payload["key"] == "model-registry"
    assert payload["uri"] == "s3://secret.example/bucket/path/model.pt"
    assert payload["display_uri"] == "s3://***redacted***/path/model.pt"
    assert payload["details"] == {"provider": "mock", "region": "au"}
    assert store == ArtifactStoreRef.from_dict(payload)
    assert store.to_summary() == payload


def test_artifact_store_ref_rejects_invalid_payload_shape() -> None:
    with pytest.raises(ArtifactValidationError):
        ArtifactStoreRef.from_dict(
            {
                "schema_version": 2,
                "kind": ArtifactLocationKind.MANAGED.value,
            }
        )
    with pytest.raises(ArtifactValidationError):
        ArtifactStoreRef.from_dict(
            {
                "schema_version": 1,
                "kind": ArtifactLocationKind.MANAGED.value,
                "extra": "x",
            }
        )
    with pytest.raises(ArtifactValidationError):
        ArtifactStoreRef.from_dict({"schema_version": 1, "kind": ""})
    with pytest.raises(ArtifactValidationError):
        ArtifactStoreRef(
            schema_version=1,
            kind="local",
            details=cast(Any, {"invalid": {1: "no"}}),
        )


def test_artifact_location_summary_rejects_wrong_authority_for_derived_kinds() -> None:
    summary = ArtifactLocationSummary(
        schema_version=1,
        kind=ArtifactLocationKind.STAGING,
        authority="derived",
        display_uri="file:///cache/model.pt",
    )
    assert summary.authority == "derived"

    with pytest.raises(ArtifactValidationError):
        ArtifactLocationSummary(
            schema_version=1,
            kind=ArtifactLocationKind.STAGING,
            authority="authoritative",
            display_uri="file:///cache/model.pt",
        )


def test_artifact_location_summary_handles_nested_store_and_digests() -> None:
    store = ArtifactStoreRef(
        schema_version=1,
        kind="object-store",
        display_uri="s3://***redacted***/path/model.pt",
    )
    location = ArtifactLocationSummary(
        schema_version=1,
        kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
        authority="authoritative",
        uri="s3://secret.example/path/model.pt",
        display_uri="s3://***redacted***/path/model.pt",
        store=store,
        checksum="sha256:" + "1" * 64,
        fingerprint="sha256:" + "2" * 64,
        size_bytes=12345,
        details={"mime": "application/octet-stream"},
    )
    payload = location.to_dict()

    assert payload["store"] == store.to_dict()
    assert payload["checksum"] == "sha256:" + "1" * 64
    assert payload["fingerprint"] == "sha256:" + "2" * 64
    assert payload["size_bytes"] == 12345
    assert ArtifactLocationSummary.from_dict(payload) == location


def test_external_artifact_declaration_round_trips_and_defaults() -> None:
    declaration = ExternalArtifactDeclaration(
        schema_version=1,
        artifact_id="artifact:best",
        uri="s3://secret.example/model.pt",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        location=ArtifactLocationSummary(
            schema_version=1,
            kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
            authority="authoritative",
            display_uri="s3://***redacted***/model.pt",
        ),
        immutability="validated",
        metadata={"labels": ["candidate"]},
        details={"source": "test"},
    )

    assert ExternalArtifactDeclaration.from_dict(declaration.to_dict()) == declaration
    assert declaration.to_dict()["metadata"] == {"labels": ["candidate"]}
    assert declaration.to_dict()["details"] == {"source": "test"}


def test_external_artifact_declaration_invalid_immutability() -> None:
    with pytest.raises(ArtifactValidationError):
        ExternalArtifactDeclaration(
            schema_version=1,
            artifact_id="artifact:best",
            uri="s3://secret",
            artifact_type="checkpoint",
            artifact_schema_version=1,
            location=ArtifactLocationSummary(
                schema_version=1,
                kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
                authority="authoritative",
                display_uri="s3://***redacted***/model.pt",
            ),
            immutability="wrong",
        )


def test_published_artifact_record_rejects_invalid_schema() -> None:
    with pytest.raises(ArtifactValidationError):
        PublishedArtifactRecord.from_dict(
            {
                "schema_version": 1,
                "artifact_id": "artifact:best",
                "uri": "s3://example/model.pt",
                "artifact_type": "checkpoint",
                "artifact_schema_version": 1,
                "producer_run_uri": "file:///runs/run-1",
                "producer_stage": "train",
                "producer_artifact_id": "artifact:input",
                "reuse_key": "reuse-01",
                "validation_policy": {},
                "owner": {},
                "retention": {},
                "evidence": {},
                "metadata": {},
                "details": {},
                "store": {"schema_version": 1, "kind": "cache", "details": {}},
                "location": {
                    "schema_version": 1,
                    "kind": "staging",
                    "authority": "authoritative",
                },
            }
        )


def test_published_artifact_record_immutability_fields_are_optional() -> None:
    record = PublishedArtifactRecord(
        schema_version=1,
        artifact_id="artifact:best",
        uri="s3://example/model.pt",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        producer_run_uri="file:///runs/run-1",
        producer_stage="train",
        producer_artifact_id="artifact:input",
        reuse_key="reuse-01",
        owner={"team": "ml"},
        retention={"days": 30},
        validation_policy={"policy": {"mode": "strict"}},
        evidence={"matched": True},
        metadata={"project": "demo"},
        details={"source": "declaration"},
    )
    assert record.location is None
    assert record.store is None
    payload = record.to_dict()
    assert payload["schema_version"] == 1
    assert payload["store"] is None
    assert payload["location"] is None


def test_immutable_lookup_request_and_result_round_trip() -> None:
    request = ImmutableArtifactLookupRequest(
        schema_version=1,
        reuse_key="reuse-01",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        validation_policy={"policy": {"min_size": 1}},
        store=ArtifactStoreRef(
            schema_version=1,
            kind="object-store",
            display_uri="s3://***redacted***/artifact.pt",
        ),
        details={"candidate": True},
    )

    published = PublishedArtifactRecord(
        schema_version=1,
        artifact_id="artifact:best",
        uri="s3://example/model.pt",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        producer_run_uri="file:///runs/run-1",
        producer_stage="train",
        producer_artifact_id="artifact:input",
        reuse_key="reuse-01",
        validation_policy={"policy": "strict"},
        owner={"team": "ml"},
        retention={"days": 30},
        evidence={"matched": True},
        metadata={"project": "demo"},
        details={"source": "declaration"},
    )

    result = ImmutableArtifactLookupResult(
        schema_version=1,
        status="compatible",
        request=request,
        published=published,
        location=ArtifactLocationSummary(
            schema_version=1,
            kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
            authority="authoritative",
            display_uri="s3://***redacted***/artifact.pt",
        ),
        diagnostics={"notes": ["cached"]},
        details={"request_id": "req-1"},
    )

    restored_request = ImmutableArtifactLookupRequest.from_dict(request.to_dict())
    restored_result = ImmutableArtifactLookupResult.from_dict(result.to_dict())
    assert restored_request == request
    assert restored_result == result


def test_external_artifact_records_plain_data_is_frozen() -> None:
    source_mapping: dict[str, PlainData] = {"labels": ["raw", "processed"]}
    record = ExternalArtifactDeclaration(
        schema_version=1,
        artifact_id="artifact:best",
        uri="s3://example/model.pt",
        artifact_type="checkpoint",
        artifact_schema_version=1,
        location=ArtifactLocationSummary(
            schema_version=1,
            kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
            authority="authoritative",
            display_uri="s3://***redacted***/model.pt",
        ),
        immutability="declared",
        metadata=cast(Mapping[str, PlainData], source_mapping),
        details={"extra": {"nested": [1, 2]}},
    )

    source_mapping["labels"].append("archived")  # type: ignore[union-attr]
    assert record.metadata["labels"] == ("raw", "processed")

    payload = record.to_dict()
    payload["metadata"]["labels"].append("archived")
    payload["metadata"]["extra"] = "value"
    assert record.metadata == {"labels": ("raw", "processed")}
    assert record.details == {"extra": {"nested": (1, 2)}}
