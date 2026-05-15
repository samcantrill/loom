from __future__ import annotations

from pathlib import Path

import pytest

from loom.artifacts import ArtifactLocationKind, ArtifactRef
from loom.fingerprints import hash_bytes
from loom.io.uris import path_to_file_uri
from loom.operations import OperationEvidenceStatus, OperationStatus
from loom.pipeline.stores import (
    ArtifactMaterializationRequest,
    LocalMaterializationPolicy,
    MaterializedRefKind,
    artifact_materialization_location,
    artifact_materialized_ref,
    materialize_artifact_locally,
)


pytestmark = pytest.mark.unit


def _artifact(path: Path, *, checksum: str | None = None) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="stage/output",
        uri=path_to_file_uri(path),
        artifact_type="bytes",
        codec_key="bytes.v1",
        checksum=checksum,
        producer_stage="stage",
    )


def test_local_copy_materialization_succeeds_with_checksum_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    checksum = hash_bytes(b"payload")
    target = tmp_path / "materialized" / "output.bin"

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source, checksum=checksum),
            target_path=target,
        )
    )

    assert result.succeeded
    assert result.operation.status is OperationStatus.SUCCEEDED
    assert result.operation.evidence is not None
    assert result.operation.evidence.status is OperationEvidenceStatus.PROVEN
    assert target.read_bytes() == b"payload"
    assert result.bytes_copied == len(b"payload")
    assert result.location is not None
    assert result.location.kind is ArtifactLocationKind.MATERIALIZED
    assert result.location.authority == "derived"
    assert result.materialized_ref is not None
    assert result.materialized_ref.kind is MaterializedRefKind.ARTIFACT_PAYLOAD
    assert result.materialized_ref.exists is True
    assert result.materialized_ref.checksum == checksum
    assert result == result.from_dict(result.to_dict())


def test_local_copy_materialization_without_checksum_records_unproven_check(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source),
            target_path=tmp_path / "target.bin",
        )
    )

    assert result.succeeded
    assert result.operation.evidence is not None
    assert result.operation.evidence.status is OperationEvidenceStatus.UNPROVEN
    checks = {check.name: check for check in result.operation.evidence.checks}
    assert checks["copy_checksum_match"].status is OperationEvidenceStatus.PROVEN
    assert (
        checks["expected_checksum_available"].status
        is OperationEvidenceStatus.UNPROVEN
    )


def test_local_copy_checksum_mismatch_fails_without_copying(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    target = tmp_path / "target.bin"

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source, checksum=f"sha256:{'0' * 64}"),
            target_path=target,
        )
    )

    assert not result.succeeded
    assert result.operation.status is OperationStatus.FAILED
    assert result.operation.diagnostics[0].code == (
        "artifact_materialization.checksum_mismatch"
    )
    assert result.operation.evidence is not None
    assert result.operation.evidence.status is OperationEvidenceStatus.FAILED
    assert not target.exists()


def test_existing_target_requires_explicit_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"new")
    target = tmp_path / "target.bin"
    target.write_bytes(b"old")

    blocked = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source, checksum=hash_bytes(b"new")),
            target_path=target,
        )
    )

    assert blocked.operation.status is OperationStatus.BLOCKED
    assert blocked.operation.diagnostics[0].code == "artifact_materialization.target_exists"
    assert target.read_bytes() == b"old"

    replaced = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source, checksum=hash_bytes(b"new")),
            target_path=target,
            overwrite=True,
        )
    )
    assert replaced.succeeded
    assert target.read_bytes() == b"new"


@pytest.mark.parametrize(
    "policy",
    [
        LocalMaterializationPolicy.HARDLINK,
        LocalMaterializationPolicy.SYMLINK,
        LocalMaterializationPolicy.REFLINK,
        LocalMaterializationPolicy.MOVE,
        LocalMaterializationPolicy.CACHE_PROMOTE,
    ],
)
def test_non_copy_policies_fail_closed_without_copying(
    tmp_path: Path,
    policy: LocalMaterializationPolicy,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    target = tmp_path / f"{policy.value}.bin"

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source, checksum=hash_bytes(b"payload")),
            target_path=target,
            policy=policy,
        )
    )

    assert result.operation.status is OperationStatus.UNSUPPORTED
    assert result.operation.diagnostics[0].code == "operation.unsupported"
    assert not target.exists()


def test_missing_source_fails_without_creating_target(tmp_path: Path) -> None:
    source = tmp_path / "missing.bin"
    target = tmp_path / "target.bin"

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source),
            target_path=target,
        )
    )

    assert result.operation.status is OperationStatus.FAILED
    assert result.operation.diagnostics[0].code == (
        "artifact_materialization.source_missing"
    )
    assert not target.exists()


def test_projection_helpers_return_derived_local_refs(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    artifact = _artifact(source, checksum=hash_bytes(b"payload"))
    target = tmp_path / "target.bin"
    target.write_bytes(b"payload")

    location = artifact_materialization_location(
        artifact,
        target,
        checksum=hash_bytes(b"payload"),
        size_bytes=len(b"payload"),
    )
    materialized_ref = artifact_materialized_ref(
        artifact,
        target,
        checksum=hash_bytes(b"payload"),
    )

    assert location.kind is ArtifactLocationKind.MATERIALIZED
    assert location.authority == "derived"
    assert location.details["artifact_id"] == artifact.artifact_id
    assert materialized_ref.kind is MaterializedRefKind.ARTIFACT_PAYLOAD
    assert materialized_ref.exists is True
    assert materialized_ref.metadata["source_uri"] == artifact.uri
