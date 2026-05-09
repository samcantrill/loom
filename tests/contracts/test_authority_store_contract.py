"""Contract tests for backend-neutral per-run authority stores."""

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import (
    BackendCapability,
    CapabilityScope,
    LeaseState,
    PerRunAuthorityStore,
)
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


RUN_URI = "file:///runs/r1"


def _submitted_record() -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=RUN_URI,
        submission_id="sub-1",
        backend="slurm",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1.json",
        summary_counts={"submitted": 1},
    )


def test_in_memory_store_satisfies_per_run_authority_protocol() -> None:
    store = InMemoryPerRunAuthorityStore()

    assert isinstance(store, PerRunAuthorityStore)
    assert store.capabilities().supports(
        BackendCapability.ATOMIC_OUTPUT_COMMIT,
        scope=CapabilityScope.PER_RUN,
    )


def test_per_run_authority_contract_records_revisioned_lifecycle_facts() -> None:
    store = InMemoryPerRunAuthorityStore()
    initial_revision = store.create_run(RUN_URI)

    assert initial_revision.sequence == 1
    assert store.check_schema(RUN_URI).supported

    transition = store.transition_run(
        RUN_URI,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    )
    assert transition.previous_status is RunStatus.CREATED
    assert transition.status is RunStatus.RUNNING

    store.transition_stage(
        RUN_URI,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
    )
    allocation = store.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.attempt.attempt == 1
    assert allocation.lease is not None
    assert allocation.lease.fencing_token

    submitted_revision = store.write_submitted_operation(RUN_URI, _submitted_record())
    assert submitted_revision.sequence > allocation.attempt.revision.sequence
    assert store.read_submitted_operation(RUN_URI, "sub-1") == _submitted_record()
    assert store.list_submitted_operations(RUN_URI) == (_submitted_record(),)

    output = ArtifactRef(
        artifact_id="build/out",
        uri="file:///runs/r1/artifacts/build/out.json",
        artifact_type="json",
    )
    commit = store.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
    )
    assert commit.commit.output_names == ("out",)
    assert commit.artifact_facts[0].artifact == output

    event = store.append_audit_event(
        RUN_URI,
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.succeeded"),
    )
    assert event.sequence == 1

    snapshot = store.snapshot(RUN_URI)
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.schema_version == 1
    assert snapshot.submitted_operations == (_submitted_record(),)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].attempts[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == commit.commit
    assert snapshot.stages[0].artifact_facts == commit.artifact_facts


def test_per_run_authority_rejects_stale_transitions_and_lease_misuse() -> None:
    store = InMemoryPerRunAuthorityStore()
    store.create_run(RUN_URI)

    with pytest.raises(ValueError, match="stale run transition"):
        store.transition_run(
            RUN_URI,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
        )

    allocation = store.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=1,
    )
    assert allocation.lease is not None

    with pytest.raises(ValueError, match="stale or foreign lease token"):
        store.renew_lease(
            allocation.lease.lease_id,
            owner_id="worker-2",
            fencing_token=allocation.lease.fencing_token,
            lease_ttl_seconds=1,
        )

    with pytest.raises(ValueError, match="active lease"):
        store.allocate_stage_attempt(
            RUN_URI,
            "build",
            owner_id="worker-2",
            lease_ttl_seconds=1,
        )

    released = store.release_lease(
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
    )
    assert released.state is LeaseState.RELEASED

    retry = store.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-2",
        lease_ttl_seconds=1,
    )
    assert retry.lease is not None
    store.advance_time(1)
    recovery = store.scan_recovery(RUN_URI)
    assert recovery[0].kind.value == "expired_lease"
    assert store.snapshot(RUN_URI).stages[0].active_lease is None

    with pytest.raises(ValueError, match="expired"):
        store.record_output_commit(
            RUN_URI,
            "build",
            attempt_id=retry.attempt.attempt_id,
            fencing_token=retry.lease.fencing_token,
            outputs={
                "out": ArtifactRef(
                    artifact_id="build/out",
                    uri="file:///runs/r1/artifacts/build/out.json",
                    artifact_type="json",
                )
            },
        )
