"""Transfer verification helpers for queue-consumable evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data

from .models import (
    RunAdapterIdentity,
    RunExchangeDiagnostic,
    RunExchangeDiagnosticSeverity,
    TransferVerificationCheck,
    TransferVerificationRecord,
    TransferVerificationStatus,
    UnsupportedTransferRecord,
)

TRANSFER_VERIFICATION_DELEGATED_KEY = "portable_run_transfer"


def transfer_verification_to_delegated_verification(
    record: TransferVerificationRecord,
    *,
    name: str = TRANSFER_VERIFICATION_DELEGATED_KEY,
) -> dict[str, PlainData]:
    """Convert transfer evidence to a LaunchContract delegated-verification item."""

    if not isinstance(record, TransferVerificationRecord):
        raise TypeError("record must be a TransferVerificationRecord")
    if not isinstance(name, str) or not name:
        raise ValueError("delegated verification name must be a non-empty string")
    payload = {
        name: {
            "status": TransferVerificationStatus(record.status).value,
            "reason": _record_reason(record),
            "adapter": record.adapter.to_dict(),
            "checks": [check.to_dict() for check in record.checks],
            "summary": _verification_summary(record.checks),
            "details": thaw_plain_data(record.details, path="details"),
        }
    }
    normalized = ensure_plain_data(payload, path="delegated_verification")
    return cast(dict[str, PlainData], normalized)


def unsupported_transfer_verification(
    adapter: RunAdapterIdentity,
    reason: str,
    *,
    check_name: str = "transfer_supported",
    details: Mapping[str, PlainData] | None = None,
) -> TransferVerificationRecord:
    """Build an unsupported transfer verification record for deferred providers."""

    if not isinstance(adapter, RunAdapterIdentity):
        raise TypeError("adapter must be a RunAdapterIdentity")
    if not isinstance(reason, str) or not reason:
        raise ValueError("reason must be a non-empty string")
    detail = dict(details or {})
    return TransferVerificationRecord(
        adapter=adapter,
        status=TransferVerificationStatus.UNSUPPORTED,
        checks=(
            TransferVerificationCheck(
                name=check_name,
                status=TransferVerificationStatus.UNSUPPORTED,
                message=reason,
                details=detail,
            ),
        ),
        details={"reason": reason, **detail},
    )


def unsupported_transfer_diagnostic(
    adapter: RunAdapterIdentity,
    reason: str,
    *,
    code: str = "run_transfer.unsupported",
    details: Mapping[str, PlainData] | None = None,
) -> RunExchangeDiagnostic:
    """Build a structured unsupported-transfer diagnostic."""

    if not isinstance(adapter, RunAdapterIdentity):
        raise TypeError("adapter must be a RunAdapterIdentity")
    if not isinstance(reason, str) or not reason:
        raise ValueError("reason must be a non-empty string")
    return RunExchangeDiagnostic(
        code=code,
        message=reason,
        severity=RunExchangeDiagnosticSeverity.ERROR,
        details={
            "adapter": adapter.to_dict(),
            "reason": reason,
            **dict(details or {}),
        },
    )


def unsupported_transfer_record(
    adapter: RunAdapterIdentity,
    reason: str,
    *,
    details: Mapping[str, PlainData] | None = None,
) -> UnsupportedTransferRecord:
    """Build a serializable unsupported transfer/provider record."""

    if not isinstance(adapter, RunAdapterIdentity):
        raise TypeError("adapter must be a RunAdapterIdentity")
    if not isinstance(reason, str) or not reason:
        raise ValueError("reason must be a non-empty string")
    return UnsupportedTransferRecord(
        adapter=adapter,
        reason=reason,
        detail=dict(details or {}),
    )


def _record_reason(record: TransferVerificationRecord) -> str:
    reason = record.details.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    status = TransferVerificationStatus(record.status)
    if status is TransferVerificationStatus.PROVEN:
        return "portable run transfer verification is proven"
    if status is TransferVerificationStatus.UNSUPPORTED:
        return "portable run transfer verification is unsupported"
    return "portable run transfer verification is unproven"


def _verification_summary(
    checks: Sequence[TransferVerificationCheck],
) -> dict[str, PlainData]:
    proven: list[PlainData] = [
        check.name
        for check in checks
        if TransferVerificationStatus(check.status) is TransferVerificationStatus.PROVEN
    ]
    unproven: list[PlainData] = [
        check.name
        for check in checks
        if TransferVerificationStatus(check.status) is TransferVerificationStatus.UNPROVEN
    ]
    unsupported: list[PlainData] = [
        check.name
        for check in checks
        if TransferVerificationStatus(check.status)
        is TransferVerificationStatus.UNSUPPORTED
    ]
    return {
        "proven": proven,
        "unproven": unproven,
        "unsupported": unsupported,
        "proven_count": len(proven),
        "unproven_count": len(unproven),
        "unsupported_count": len(unsupported),
    }


__all__ = [
    "TRANSFER_VERIFICATION_DELEGATED_KEY",
    "transfer_verification_to_delegated_verification",
    "unsupported_transfer_diagnostic",
    "unsupported_transfer_record",
    "unsupported_transfer_verification",
]
