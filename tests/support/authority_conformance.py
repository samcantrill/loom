"""Reusable public RunStore/StageStore authority conformance checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import LeaseState, RunStore, StageStore


@dataclass(frozen=True, slots=True)
class PublicAuthorityCase:
    store: RunStore
    run_uri: str
    advance_time: Callable[[int], None] | None = None


def submitted_record(run_uri: str) -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="slurm",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1.json",
        summary_counts={"submitted": 1},
    )


def assert_public_authority_lifecycle(case: PublicAuthorityCase) -> None:
    store = case.store
    run_uri = case.run_uri
    submitted = submitted_record(run_uri)

    assert isinstance(store, RunStore)
    initial_revision = store.admit_run(run_uri)
    assert initial_revision.sequence == 1
    assert store.check_schema(run_uri).supported

    transition = store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    )
    assert transition.previous_status is RunStatus.CREATED
    assert transition.status is RunStatus.RUNNING

    stage = store.stage_store(run_uri, "build")
    assert isinstance(stage, StageStore)
    assert stage.run_uri == run_uri
    assert stage.stage_name == "build"
    stage.transition(from_status=None, to_status=StageStatus.PENDING)
    allocation = stage.allocate_attempt(owner_id="worker-1", lease_ttl_seconds=30)
    assert allocation.attempt.attempt == 1
    assert allocation.lease is not None
    assert allocation.lease.fencing_token

    revision = stage.write_submitted_operation(submitted)
    assert revision.sequence > allocation.attempt.revision.sequence
    assert stage.read_submitted_operation("sub-1") == submitted
    assert stage.list_submitted_operations() == (submitted,)
    assert store.list_submitted_operations(run_uri) == (submitted,)

    output = ArtifactRef(
        artifact_id="build/out",
        uri=f"{run_uri}/artifacts/build/out.json",
        artifact_type="json",
    )
    commit = stage.record_output_commit(
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
    )
    assert commit.commit.output_names == ("out",)
    assert commit.artifact_facts[0].artifact == output

    run_snapshot = store.snapshot(run_uri)
    stage_snapshot = stage.snapshot()
    assert run_snapshot.status is RunStatus.RUNNING
    assert run_snapshot.submitted_operations == (submitted,)
    assert stage_snapshot.status is StageStatus.SUCCEEDED
    assert stage_snapshot.latest_commit == commit.commit
    assert stage_snapshot.artifact_facts == commit.artifact_facts


def assert_public_authority_rejects_stale_and_foreign_writes(
    case: PublicAuthorityCase,
) -> None:
    store = case.store
    run_uri = case.run_uri
    store.admit_run(run_uri)
    stage = store.stage_store(run_uri, "build")

    with pytest.raises(ValueError, match="stale run transition"):
        store.transition_run(
            run_uri,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
        )

    allocation = stage.allocate_attempt(owner_id="worker-1", lease_ttl_seconds=1)
    assert allocation.lease is not None

    with pytest.raises(ValueError, match="stale or foreign lease token"):
        stage.renew_lease(
            allocation.lease.lease_id,
            owner_id="worker-2",
            fencing_token=allocation.lease.fencing_token,
            lease_ttl_seconds=1,
        )

    with pytest.raises(ValueError, match="active lease"):
        stage.allocate_attempt(owner_id="worker-2", lease_ttl_seconds=1)

    released = stage.release_lease(
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
    )
    assert released.state is LeaseState.RELEASED

    retry = stage.allocate_attempt(owner_id="worker-2", lease_ttl_seconds=1)
    assert retry.lease is not None
    assert case.advance_time is not None
    case.advance_time(2)
    recovery = stage.scan_recovery()
    assert recovery[0].kind.value == "expired_lease"
    assert stage.snapshot().active_lease is None

    with pytest.raises(ValueError, match="expired"):
        stage.record_output_commit(
            attempt_id=retry.attempt.attempt_id,
            fencing_token=retry.lease.fencing_token,
            outputs={
                "out": ArtifactRef(
                    artifact_id="build/out",
                    uri=f"{run_uri}/artifacts/build/out.json",
                    artifact_type="json",
                )
            },
        )
