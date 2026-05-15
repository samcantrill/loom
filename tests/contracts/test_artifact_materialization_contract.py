from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_bytes
from loom.io.uris import path_to_file_uri
from loom.operations import OperationStatus
from loom.pipeline.stores import (
    ArtifactMaterializationError,
    ArtifactMaterializationRequest,
    ArtifactMaterializationResult,
    LocalMaterializationPolicy,
    materialize_artifact_locally,
)


pytestmark = pytest.mark.contract


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="stage/output",
        uri=path_to_file_uri(path),
        artifact_type="bytes",
        codec_key="bytes.v1",
        checksum=hash_bytes(path.read_bytes()),
        producer_stage="stage",
    )


def test_materialization_request_contract_is_strict_and_plain(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    request = ArtifactMaterializationRequest(
        artifact=_artifact(source),
        target_path=tmp_path / "target.bin",
        policy=LocalMaterializationPolicy.COPY,
        overwrite=True,
        verify_checksum=False,
        details={"caller": "contract"},
    )

    payload = request.to_dict()

    assert payload["policy"] == "copy"
    assert payload["overwrite"] is True
    assert payload["verify_checksum"] is False
    assert payload["details"] == {"caller": "contract"}
    assert ArtifactMaterializationRequest.from_dict(payload) == request

    with pytest.raises(ArtifactMaterializationError):
        ArtifactMaterializationRequest.from_dict({**payload, "unknown": True})

    with pytest.raises(ArtifactMaterializationError):
        ArtifactMaterializationRequest.from_dict(
            {**payload, "policy": "transparent_cache"}
        )


def test_materialization_result_contract_uses_operation_result(
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

    payload = result.to_dict()
    operation = cast(dict[str, object], payload["operation"])
    location = cast(dict[str, object], payload["location"])
    materialized_ref = cast(dict[str, object], payload["materialized_ref"])

    assert operation["status"] == "succeeded"
    assert operation["operation"] == "artifact.materialize.local.copy"
    assert location["kind"] == "materialized"
    assert location["authority"] == "derived"
    assert materialized_ref["kind"] == "artifact_payload"
    assert ArtifactMaterializationResult.from_dict(payload) == result

    with pytest.raises(ArtifactMaterializationError):
        ArtifactMaterializationResult.from_dict({**payload, "unknown": True})


def test_non_copy_policy_contract_is_structured_unsupported(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"payload")

    result = materialize_artifact_locally(
        ArtifactMaterializationRequest(
            artifact=_artifact(source),
            target_path=target,
            policy=LocalMaterializationPolicy.SYMLINK,
        )
    )

    assert result.operation.status is OperationStatus.UNSUPPORTED
    assert not target.exists()
    payload = result.to_dict()
    operation = cast(dict[str, object], payload["operation"])
    diagnostics = cast(list[dict[str, object]], operation["diagnostics"])
    details = cast(dict[str, object], operation["details"])

    assert diagnostics[0]["code"] == "operation.unsupported"
    assert details["policy"] == "symlink"
