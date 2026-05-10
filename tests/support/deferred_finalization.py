"""Helpers for deferred-finalization tests."""

from __future__ import annotations

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import DeferredResultEnvelope, LeaseRecord
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


def submitted_operation(
    run_uri: str,
    *,
    state: SubmittedOperationState | str = SubmittedOperationState.SUBMITTED,
) -> SubmittedOperationRecord:
    resolved_state = SubmittedOperationState(state)
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="slurm",
        mode="deferred_finalization",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        state=resolved_state,
        manifest_relative_path="submitted/sub-1/manifest.json",
        summary_counts={"submitted": 1}
        if resolved_state is SubmittedOperationState.SUBMITTED
        else {},
    )


def ready_deferred_authority() -> tuple[
    InMemoryPerRunAuthorityStore,
    DeferredResultEnvelope,
    LeaseRecord,
]:
    run_uri = "file:///runs/r1"
    authority = InMemoryPerRunAuthorityStore()
    authority.create_run(run_uri)
    allocation = authority.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=60,
    )
    assert allocation.lease is not None
    authority.write_submitted_operation(run_uri, submitted_operation(run_uri))
    envelope = DeferredResultEnvelope(
        run_uri=run_uri,
        stage_name="build",
        attempt_id=allocation.attempt.attempt_id,
        submission_id="sub-1",
        owner_id="worker-1",
        produced_at="2020-01-01T00:00:02Z",
        producer_id="offline-worker",
        status=StageStatus.SUCCEEDED,
        output_refs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri="file:///runs/r1/artifacts/build/out.json",
                artifact_type="json",
            )
        },
    )
    return authority, envelope, allocation.lease
