"""Contract coverage for v10 offline import protocol shapes."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.authority.offline_import import (
    OfflineImportDiagnostic,
    OfflineImportRejectionKind,
    OfflineImportResult,
)
from loom.pipeline.stores import (
    AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH,
    AuthorityClient,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    BackendRevision,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.contract


def test_offline_import_result_contract_shape() -> None:
    result = OfflineImportResult(
        run_uri="file:///runs/offline",
        status="SUCCEEDED",
        revision_sequence=7,
        imported_stage_count=2,
        imported_artifact_count=3,
        import_provenance={
            "source": "offline_evidence",
            "manifest_schema_version": 1,
        },
    )

    assert result.to_dict() == {
        "run_uri": "file:///runs/offline",
        "status": "SUCCEEDED",
        "revision_sequence": 7,
        "imported_stage_count": 2,
        "imported_artifact_count": 3,
        "import_provenance": {
            "source": "offline_evidence",
            "manifest_schema_version": 1,
        },
    }


def test_offline_import_diagnostic_contract_shape() -> None:
    diagnostic = OfflineImportDiagnostic(
        code="offline_import.incomplete_manifest",
        message="offline evidence manifest is incomplete",
        kind=OfflineImportRejectionKind.INCOMPLETE,
        detail={"manifest_status": "incomplete"},
    )

    assert diagnostic.to_dict() == {
        "code": "offline_import.incomplete_manifest",
        "message": "offline evidence manifest is incomplete",
        "kind": "incomplete",
        "detail": {"manifest_status": "incomplete"},
    }


def test_authority_client_offline_import_request_contract() -> None:
    calls: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        calls.append((url, payload))
        return AuthorityProtocolResponse(
            metadata=AuthorityProtocolMetadata(
                request_id="import-1",
                operation_kind=AuthorityProtocolOperationKind.OFFLINE_IMPORT,
                service_generation="generation-1",
                workspace_id="workspace-a",
            ),
            accepted=True,
            result=AuthorityProtocolResult(
                revision=BackendRevision(sequence=1, token="rev-1"),
                service_generation="generation-1",
                body={
                    "offline_import": {
                        "run_uri": "file:///runs/offline",
                        "status": "SUCCEEDED",
                    }
                },
            ),
        ).to_dict()

    client = AuthorityClient("http://authority.test", transport=transport)

    response = client.import_offline_evidence(
        {"run_uri": "file:///runs/offline"},
        request_id="import-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
        imported_by="contract-test",
    )

    assert response.accepted is True
    assert calls[0][0] == f"http://authority.test{AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH}"
    request = calls[0][1]
    metadata = cast_mapping(request["metadata"])
    body = cast_mapping(request["body"])
    manifest = cast_mapping(body["manifest"])
    assert metadata["operation_kind"] == "offline_import"
    assert metadata["request_id"] == "import-1"
    assert request["run_uri"] == "file:///runs/offline"
    assert body["imported_by"] == "contract-test"
    assert manifest["run_uri"] == "file:///runs/offline"


def cast_mapping(value: object) -> Mapping[str, PlainData]:
    assert isinstance(value, Mapping)
    return value
