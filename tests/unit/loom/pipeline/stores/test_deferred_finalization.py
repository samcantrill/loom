"""Unit coverage for deferred result envelopes."""

from __future__ import annotations

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    DeferredFinalizationError,
    DeferredReconciliationCode,
    DeferredResultEnvelope,
    reconcile_deferred_result,
)
from tests.support.authority_stores import InMemoryPerRunAuthorityStore

from tests.support.deferred_finalization import (
    ready_deferred_authority,
    submitted_operation,
)


def test_deferred_result_envelope_round_trips_plain_data() -> None:
    envelope = DeferredResultEnvelope(
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
        submission_id="sub-1",
        owner_id="worker-1",
        produced_at="2020-01-01T00:00:00Z",
        producer_id="offline-worker",
        status=StageStatus.SUCCEEDED,
        output_refs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri="file:///runs/r1/artifacts/build/out.json",
                artifact_type="json",
            )
        },
        materialized_refs={"manifest": "deferred/sub-1/envelope.json"},
        plan_fingerprint="plan-1",
    )

    restored = DeferredResultEnvelope.from_dict(envelope.to_dict())

    assert restored == envelope
    assert restored.to_dict()["output_refs"] == envelope.to_dict()["output_refs"]


def test_deferred_result_envelope_rejects_live_fencing_material() -> None:
    data = DeferredResultEnvelope(
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
        submission_id="sub-1",
        owner_id="worker-1",
        produced_at="2020-01-01T00:00:00Z",
        producer_id="offline-worker",
        status=StageStatus.FAILED,
    ).to_dict()
    data["fencing_token"] = "worker-must-not-carry-live-fence"

    with pytest.raises(DeferredFinalizationError, match="unknown field"):
        DeferredResultEnvelope.from_dict(data)


def test_deferred_reconciliation_requires_reconciler_fence_for_success() -> None:
    authority, envelope, _lease = ready_deferred_authority()

    result = reconcile_deferred_result(authority, envelope)

    assert not result.accepted
    assert result.code is DeferredReconciliationCode.MISSING_RECONCILER_FENCE


def test_deferred_reconciliation_rejects_terminal_submission() -> None:
    authority = InMemoryPerRunAuthorityStore()
    authority.create_run("file:///runs/r1")
    allocation = authority.allocate_stage_attempt(
        "file:///runs/r1",
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=60,
    )
    authority.write_submitted_operation(
        "file:///runs/r1",
        submitted_operation("file:///runs/r1", state="COMPLETED"),
    )
    envelope = DeferredResultEnvelope(
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id=allocation.attempt.attempt_id,
        submission_id="sub-1",
        owner_id="worker-1",
        produced_at="2020-01-01T00:00:00Z",
        producer_id="offline-worker",
        status=StageStatus.FAILED,
    )

    result = reconcile_deferred_result(authority, envelope)

    assert not result.accepted
    assert result.code is DeferredReconciliationCode.SUBMISSION_MISMATCH
