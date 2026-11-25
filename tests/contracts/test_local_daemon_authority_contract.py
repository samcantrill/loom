"""Contract coverage for the private production-daemon authority extension."""

from pathlib import Path

import pytest

from loom.pipeline.status import RunStatus
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
        operation_id="cancel-1",
        coordinator_id="coordinator-1",
        run_uri=run_uri,
        stage_names=("stage-a",),
    )
    cancellation_receipt = authority.install_cancellation_epoch(run_uri, cancellation)
    assert (
        CancellationEpochReceipt.from_dict(cancellation_receipt.to_dict())
        == cancellation_receipt
    )
    assert authority.finalize_cancellation(run_uri, cancellation) is RunStatus.CANCELLED


def test_resident_authority_protocol_accepts_an_adapter_without_slurm_receipt_reads(
    tmp_path, monkeypatch
):
    from loom.pipeline.stores.authority import PreparedBindingState
    from loom.queue._coordinator_run_authority import _ScopedCoordinatorAuthority
    from loom.queue._lifecycle_observers import LifecycleObservers
    from loom.queue.coordinator_authority import CoordinatorAuthorityStore
    from loom.queue.errors import QueueServiceError

    uri = path_to_run_uri(tmp_path / "resident-only")
    authority = SQLitePerRunAuthorityStore(uri)
    authority.create_run(uri)
    scoped = _ScopedCoordinatorAuthority(
        LifecycleObservers().authority(authority, uri),
        run_uri=uri,
        coordinator_id="coordinator",
    )
    binding = {"assignment_id": "assignment", "attempt_id": "attempt"}
    assert (
        scoped.read_prepared_binding(uri, **binding).state
        is PreparedBindingState.ABSENT
    )

    monkeypatch.delattr(SQLitePerRunAuthorityStore, "read_prepared_binding")
    assert isinstance(authority, CoordinatorAuthorityStore)
    assert scoped.open_run(uri).run_uri == uri
    with pytest.raises(QueueServiceError, match="SLURM recovery requires"):
        scoped.read_prepared_binding(uri, **binding)
