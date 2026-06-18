from __future__ import annotations

import pytest
from typing import cast

from loom.operations import (
    OperationAdapterIdentity,
    OperationEvidenceCheck,
    OperationEvidenceRecord,
    OperationEvidenceStatus,
    OperationSupport,
    OperationResult,
    OperationStatus,
    OperationSupportRecord,
    OperationValidationError,
)


pytestmark = pytest.mark.contract


def test_operation_evidence_contract_uses_plain_plain_data_and_checksums() -> None:
    adapter = OperationAdapterIdentity(name="checksum-verifier", kind="object-store", version="1")
    evidence = OperationEvidenceRecord(
        status=OperationEvidenceStatus.PROVEN,
        checks=(
            OperationEvidenceCheck(
                name="checksum_match",
                status=OperationEvidenceStatus.PROVEN,
                message="payload checksum validated",
                details={"algorithm": "sha256", "value": "cafebabe"},
            ),
        ),
        adapter=adapter,
        details={"checksum": "sha256:cafebabe", "size_bytes": 42},
    )

    contract = evidence.to_dict()

    assert contract == {
        "status": "proven",
        "checks": [
            {
                "name": "checksum_match",
                "status": "proven",
                "message": "payload checksum validated",
                "details": {"algorithm": "sha256", "value": "cafebabe"},
            }
        ],
        "adapter": {"name": "checksum-verifier", "kind": "object-store", "version": "1"},
        "details": {"checksum": "sha256:cafebabe", "size_bytes": 42},
    }
    assert OperationEvidenceRecord.from_dict(contract) == evidence


def test_operation_result_contract_covers_unsupported_and_not_implemented() -> None:
    adapter = OperationAdapterIdentity(name="backend", kind="remote", version=None)
    unsupported = OperationResult.unsupported(
        "materialize",
        reason="materialize unsupported by provider",
        adapter=adapter,
    )
    not_implemented = OperationResult.not_implemented(
        "publish",
        reason="publish intentionally not implemented in Phase 1",
        adapter=adapter,
    )
    unsupported_payload = cast(dict[str, object], unsupported.to_dict())
    unsupported_evidence = cast(dict[str, object], unsupported_payload["evidence"])
    unsupported_diagnostics = cast(list[dict[str, object]], unsupported_payload["diagnostics"])

    assert unsupported_payload["status"] == "unsupported"
    assert unsupported_evidence["status"] == "unsupported"
    assert cast(list[object], unsupported_evidence["checks"]) == []
    assert unsupported_diagnostics[0]["code"] == "operation.unsupported"
    not_implemented_payload = cast(dict[str, object], not_implemented.to_dict())
    not_implemented_evidence = cast(
        dict[str, object],
        not_implemented_payload["evidence"],
    )
    assert not_implemented_payload["status"] == "not_implemented"
    assert not_implemented_evidence["status"] == "not_implemented"
    assert not_implemented.evidence
    assert not_implemented.evidence.checks == ()

    assert unsupported.evidence is not None
    assert not_implemented.evidence is not None
    assert unsupported.evidence.status is OperationEvidenceStatus.UNSUPPORTED
    assert not_implemented.evidence.status is OperationEvidenceStatus.NOT_IMPLEMENTED
    assert unsupported == OperationResult.from_dict(unsupported.to_dict())
    assert not_implemented == OperationResult.from_dict(not_implemented.to_dict())


def test_operation_support_record_contract_strict_from_dict_shape() -> None:
    support = OperationSupportRecord.unsupported(
        "publish",
        message="provider does not support publish",
    )
    payload = support.to_dict()

    payload_dict = cast(dict[str, object], payload)
    assert payload_dict["support"] == "unsupported"
    diagnostics_payload = cast(list[dict[str, object]], payload_dict["diagnostics"])
    assert diagnostics_payload[0]["severity"] == "error"

    restored = OperationSupportRecord.from_dict(payload)
    assert restored.support is OperationSupport.UNSUPPORTED
    assert restored == support

    with pytest.raises(OperationValidationError):
        OperationSupportRecord.from_dict({**payload, "unknown": True})

    with pytest.raises(OperationValidationError):
        OperationSupportRecord.from_dict({"operation": "x", "support": "unsupported"})


def test_operation_status_and_support_have_expected_wire_values() -> None:
    support_values = [item.value for item in OperationSupport]
    status_values = [status.value for status in OperationStatus]

    assert status_values == [
        "succeeded",
        "failed",
        "blocked",
        "unsupported",
        "not_implemented",
        "unknown",
    ]
    assert support_values == [
        "supported",
        "unsupported",
        "unknown",
        "not_implemented",
    ]
