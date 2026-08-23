"""Contract coverage for the private production-daemon authority extension."""

from pathlib import Path

import pytest

from loom.pipeline.stores import (
    CancellationEpochReceipt,
    CancellationEpochRequest,
    CoordinatorAdmissionReceipt,
    CoordinatorAdmissionRequest,
    LocalDaemonAuthority,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


pytestmark = pytest.mark.contract


def test_sqlite_daemon_authority_receipts_are_exact_and_serializable(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "daemon-authority-contract")
    authority = SQLitePerRunAuthorityStore()
    authority.create_run(run_uri)

    assert isinstance(authority, LocalDaemonAuthority)
    admission = CoordinatorAdmissionRequest(
        operation_id="admit-1",
        coordinator_id="coordinator-1",
        run_uri=run_uri,
        intent_digest="intent-1",
    )
    admission_receipt = authority.bind_coordinator_admission(run_uri, admission)
    assert (
        CoordinatorAdmissionReceipt.from_dict(admission_receipt.to_dict())
        == admission_receipt
    )

    cancellation = CancellationEpochRequest(
        operation_id="cancel-1", coordinator_id="coordinator-1", run_uri=run_uri
    )
    cancellation_receipt = authority.install_cancellation_epoch(run_uri, cancellation)
    assert (
        CancellationEpochReceipt.from_dict(cancellation_receipt.to_dict())
        == cancellation_receipt
    )
