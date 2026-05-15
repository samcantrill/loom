"""Unit coverage for transfer evidence helper mappings."""

from __future__ import annotations

from typing import cast

import pytest

from loom.runs import (
    TRANSFER_VERIFICATION_DELEGATED_KEY,
    RunAdapterIdentity,
    RunExchangeDiagnosticSeverity,
    TransferRecordKind,
    TransferVerificationCheck,
    TransferVerificationRecord,
    TransferVerificationStatus,
    transfer_verification_to_delegated_verification,
    unsupported_transfer_diagnostic,
    unsupported_transfer_record,
    unsupported_transfer_verification,
)


pytestmark = pytest.mark.unit


def test_transfer_verification_maps_to_delegated_verification_plain_data() -> None:
    adapter = RunAdapterIdentity(name="fake-transfer", kind=TransferRecordKind.FAKE)
    record = TransferVerificationRecord(
        adapter=adapter,
        status=TransferVerificationStatus.UNPROVEN,
        checks=(
            TransferVerificationCheck(
                name="payload_present",
                status=TransferVerificationStatus.PROVEN,
                message="payload was staged",
            ),
            TransferVerificationCheck(
                name="remote_visibility",
                status=TransferVerificationStatus.UNPROVEN,
                message="remote visibility was not checked",
            ),
            TransferVerificationCheck(
                name="provider_support",
                status=TransferVerificationStatus.UNSUPPORTED,
                message="provider support is deferred",
            ),
        ),
        details={"reason": "transfer evidence is partial"},
    )

    delegated = transfer_verification_to_delegated_verification(record)

    item = cast(dict[str, object], delegated[TRANSFER_VERIFICATION_DELEGATED_KEY])
    summary = cast(dict[str, object], item["summary"])
    assert item["status"] == "unproven"
    assert item["reason"] == "transfer evidence is partial"
    assert item["adapter"] == adapter.to_dict()
    assert summary["proven"] == ["payload_present"]
    assert summary["unproven"] == ["remote_visibility"]
    assert summary["unsupported"] == ["provider_support"]


def test_unsupported_transfer_helpers_share_adapter_identity() -> None:
    adapter = RunAdapterIdentity(name="object-store", kind=TransferRecordKind.UNKNOWN)

    verification = unsupported_transfer_verification(
        adapter,
        "object-store transfer is not implemented",
        details={"provider": "object-store"},
    )
    diagnostic = unsupported_transfer_diagnostic(
        adapter,
        "object-store transfer is not implemented",
        details={"provider": "object-store"},
    )
    record = unsupported_transfer_record(
        adapter,
        "object-store transfer is not implemented",
        details={"provider": "object-store"},
    )

    assert verification.status is TransferVerificationStatus.UNSUPPORTED
    assert verification.checks[0].status is TransferVerificationStatus.UNSUPPORTED
    assert verification.details["reason"] == "object-store transfer is not implemented"
    assert diagnostic.code == "run_transfer.unsupported"
    assert diagnostic.severity is RunExchangeDiagnosticSeverity.ERROR
    assert diagnostic.details["adapter"] == adapter.to_dict()
    assert diagnostic.details["reason"] == "object-store transfer is not implemented"
    assert record.adapter == adapter
    assert record.to_dict()["detail"] == {"provider": "object-store"}


def test_unsupported_transfer_details_cannot_override_canonical_fields() -> None:
    adapter = RunAdapterIdentity(name="object-store", kind=TransferRecordKind.UNKNOWN)
    details = {
        "adapter": {"name": "wrong"},
        "reason": "wrong reason",
        "provider": "object-store",
    }

    verification = unsupported_transfer_verification(
        adapter,
        "object-store transfer is not implemented",
        details=details,
    )
    diagnostic = unsupported_transfer_diagnostic(
        adapter,
        "object-store transfer is not implemented",
        details=details,
    )

    assert verification.details["reason"] == "object-store transfer is not implemented"
    assert verification.details["provider"] == "object-store"
    assert diagnostic.details["adapter"] == adapter.to_dict()
    assert diagnostic.details["reason"] == "object-store transfer is not implemented"
    assert diagnostic.details["provider"] == "object-store"
