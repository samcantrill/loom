"""Unit tests for artifact references."""

from typing import Any, cast

import pytest

from loom.artifacts import ArtifactAddress, ArtifactRef, ArtifactValidationError
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
