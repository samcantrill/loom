from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from loom.operations import (
    OperationAdapterIdentity,
    OperationDiagnostic,
    OperationDiagnosticSeverity,
    OperationEvidenceCheck,
    OperationEvidenceRecord,
    OperationEvidenceStatus,
    OperationResult,
    OperationStatus,
    OperationSupport,
    OperationSupportRecord,
    OperationValidationError,
)


pytestmark = pytest.mark.unit


def test_operation_adapter_identity_round_trip_and_validation() -> None:
    identity = OperationAdapterIdentity(name="object-store", kind="backend", version="1.0.0")
    payload = identity.to_dict()
    restored = OperationAdapterIdentity.from_dict(payload)

    assert restored == identity
    assert restored.to_dict() == {"name": "object-store", "kind": "backend", "version": "1.0.0"}

    with pytest.raises(OperationValidationError):
        OperationAdapterIdentity.from_dict({"name": "backend", "kind": "provider"})


def test_operation_diagnostic_sanitizes_sensitive_plain_details() -> None:
    diagnostic = OperationDiagnostic(
        code="provider.unsupported",
        message="provider unsupported",
        severity=OperationDiagnosticSeverity.WARNING,
        details={
            "token": "secret-token",
            "endpoint": "https://user:password@example.com/artifacts",
            "query": "https://example.com?token=abc&mode=ro",
            "provider": "demo",
        },
    )
    emitted = diagnostic.to_dict()

    assert emitted["details"] == {
        "token": "<redacted>",
        "endpoint": "<redacted>",
        "query": "https://example.com?token=<redacted>&mode=ro",
        "provider": "demo",
    }

    with pytest.raises(OperationValidationError):
        OperationDiagnostic(
            code="bad",
            message="bad",
            details=cast(Mapping[str, Any], {"bad": object()}),
        )


def test_operation_evidence_record_rejects_non_record_checks() -> None:
    check = OperationEvidenceCheck(
        name="checksum_match",
        status=OperationEvidenceStatus.PROVEN,
        message="checksum passed",
        details={"mode": "sha256"},
    )
    record = OperationEvidenceRecord(
        status=OperationEvidenceStatus.PROVEN,
        checks=(check,),
        details={"checksum": "abc"},
    )

    payload = record.to_dict()
    assert payload["status"] == "proven"
    assert payload["checks"] == [
        {
            "name": "checksum_match",
            "status": "proven",
            "message": "checksum passed",
            "details": {"mode": "sha256"},
        }
    ]

    assert OperationEvidenceRecord.from_dict(payload) == record

    with pytest.raises(OperationValidationError):
        OperationEvidenceRecord.from_dict(
            {
                "status": "proven",
                "checks": ["bad"],
                "details": {},
            }
        )

    with pytest.raises(OperationValidationError):
        OperationEvidenceRecord(
            status="proven",
            checks=cast(tuple[OperationEvidenceCheck, ...], ("bad",)),
            details={},
        )


def test_operation_support_record_from_dict_accepts_serialized_diagnostics() -> None:
    serialized = {
        "operation": "materialize",
        "support": "supported",
        "message": "capability present",
        "diagnostics": (
            {
                "code": "materialize.supported",
                "message": "materialize supported",
                "severity": "info",
                "details": {"provider": "local"},
            },
        ),
        "details": {"backend": "local"},
    }
    record = OperationSupportRecord.from_dict(serialized)

    assert record == OperationSupportRecord(
        operation="materialize",
        support=OperationSupport.SUPPORTED,
        message="capability present",
        diagnostics=(
            OperationDiagnostic(
                code="materialize.supported",
                message="materialize supported",
                severity=OperationDiagnosticSeverity.INFO,
                details={"provider": "local"},
            ),
        ),
        details={"backend": "local"},
    )


def test_operation_support_result_constructors_are_strict_and_plain() -> None:
    support = OperationSupportRecord.unsupported(
        "materialize",
        message="publish path is unsupported",
        details={"backend": "object-store"},
    )
    not_impl = OperationSupportRecord.not_implemented(
        "publish",
        message="publish requires configured executor",
    )

    assert support.support is OperationSupport.UNSUPPORTED
    assert support.message == "publish path is unsupported"
    support_payload = cast(dict[str, object], support.to_dict())
    assert support_payload["support"] == "unsupported"
    assert support.diagnostics[0].code == "operation.support.unsupported"
    support_details = cast(dict[str, object], support_payload["details"])
    assert support_details["backend"] == "object-store"

    assert not_impl.support is OperationSupport.NOT_IMPLEMENTED
    assert not_impl.diagnostics


def test_operation_result_supports_unsupported_and_not_implemented_constructors() -> None:
    adapter = OperationAdapterIdentity(name="fake", kind="backend", version="1")
    unsupported = OperationResult.unsupported(
        "materialize",
        reason="materialize is unsupported in Phase 1",
        adapter=adapter,
    )
    not_implemented = OperationResult.not_implemented(
        "publish",
        reason="publish is deferred",
        adapter=adapter,
    )

    assert unsupported.status is OperationStatus.UNSUPPORTED
    assert not_implemented.status is OperationStatus.NOT_IMPLEMENTED
    assert unsupported.evidence is not None
    assert unsupported.evidence.status is OperationEvidenceStatus.UNSUPPORTED
    assert not_implemented.evidence is not None
    assert not_implemented.evidence.status is OperationEvidenceStatus.NOT_IMPLEMENTED
    assert unsupported.to_dict()["status"] == "unsupported"
    assert not_implemented.to_dict()["status"] == "not_implemented"
    assert unsupported.diagnostics[0].code == "operation.unsupported"
    unsupported_payload = cast(dict[str, object], unsupported.to_dict())
    unsupported_details = cast(dict[str, object], unsupported_payload["details"])
    assert unsupported_details["reason"] == "materialize is unsupported in Phase 1"

    with pytest.raises(OperationValidationError):
        OperationResult.unsupported("materialize", reason="", adapter=adapter)
