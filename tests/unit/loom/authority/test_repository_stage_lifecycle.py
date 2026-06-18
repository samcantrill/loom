"""Unit tests for private authority repository stage lifecycle behavior."""

from __future__ import annotations

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.read_models import LeaseState, LifecycleReason
from loom.authority._repository import (
    AuthorityRepositoryError,
    initialize_authority_repository,
)


pytestmark = pytest.mark.unit

RUN_URI = "file:///runs/unit-stage-r1"


def _repository(tmp_path):
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    repository.admit_run(RUN_URI)
    return repository


def test_stage_transition_and_attempt_allocation_updates_snapshot(tmp_path) -> None:
    repository = _repository(tmp_path)
    initial = repository.open_run(RUN_URI).revision

    transition = repository.transition_stage(
        RUN_URI,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
        expected_revision=initial,
    )
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
        expected_revision=transition.revision,
    )

    assert allocation.attempt.attempt == 1
    assert allocation.attempt.status is StageStatus.RUNNING
    assert allocation.lease is not None
    assert allocation.lease.kind.value == "stage"

    snapshot = repository.open_run(RUN_URI)
    assert snapshot.stages[0].stage_name == "build"
    assert snapshot.stages[0].status is StageStatus.RUNNING
    assert snapshot.stages[0].attempts == (allocation.attempt,)
    assert snapshot.stages[0].active_lease == allocation.lease


def test_stage_transition_rejects_stale_status_and_revision(tmp_path) -> None:
    repository = _repository(tmp_path)
    initial = repository.open_run(RUN_URI).revision
    repository.transition_stage(
        RUN_URI,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
        expected_revision=initial,
    )

    with pytest.raises(AuthorityRepositoryError, match="stale stage transition"):
        repository.transition_stage(
            RUN_URI,
            "build",
            from_status=None,
            to_status=StageStatus.RUNNING,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale run revision"):
        repository.transition_stage(
            RUN_URI,
            "build",
            from_status=StageStatus.PENDING,
            to_status=StageStatus.RUNNING,
            expected_revision=initial,
        )


def test_stage_lease_rejects_bad_fence_and_can_be_released(tmp_path) -> None:
    repository = _repository(tmp_path)
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None

    with pytest.raises(AuthorityRepositoryError, match="stale or foreign"):
        repository.renew_stage_lease(
            RUN_URI,
            allocation.lease.lease_id,
            owner_id="worker-2",
            fencing_token=allocation.lease.fencing_token,
            lease_ttl_seconds=30,
        )

    renewed = repository.renew_stage_lease(
        RUN_URI,
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        lease_ttl_seconds=60,
    )
    released = repository.release_stage_lease(
        RUN_URI,
        renewed.lease_id,
        owner_id="worker-1",
        fencing_token=renewed.fencing_token,
    )

    assert released.state is LeaseState.RELEASED


def test_output_commit_persists_artifacts_and_rejects_stale_generation(tmp_path) -> None:
    repository = _repository(tmp_path)
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    artifact = ArtifactRef(
        artifact_id="build/out",
        uri=f"{RUN_URI}/artifacts/build/out.json",
        artifact_type="json",
        metadata={"size": 123},
    )

    with pytest.raises(AuthorityRepositoryError, match="stale service generation"):
        repository.record_output_commit(
            RUN_URI,
            "build",
            attempt_id=allocation.attempt.attempt_id,
            owner_id="worker-1",
            fencing_token=allocation.lease.fencing_token,
            outputs={"out": artifact},
            service_generation="wrong-generation",
        )

    commit = repository.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": artifact},
        service_generation="generation-1",
    )

    snapshot = repository.open_run(RUN_URI)
    stage = snapshot.stages[0]
    assert stage.status is StageStatus.SUCCEEDED
    assert stage.attempts[0].status is StageStatus.SUCCEEDED
    assert stage.latest_commit == commit.commit
    assert stage.artifact_facts == commit.artifact_facts


def test_finish_stage_attempt_records_terminal_state(tmp_path) -> None:
    repository = _repository(tmp_path)
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "test",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    reason = LifecycleReason(code="stage_failed")

    attempt = repository.finish_stage_attempt(
        RUN_URI,
        "test",
        attempt_id=allocation.attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        to_status=StageStatus.FAILED,
        service_generation="generation-1",
        reason=reason,
    )

    snapshot = repository.open_run(RUN_URI)
    assert attempt.status is StageStatus.FAILED
    assert snapshot.stages[0].status is StageStatus.FAILED
    assert snapshot.stages[0].attempts[0].reason == reason


def test_finish_stage_attempt_rejects_success_without_output_commit(tmp_path) -> None:
    repository = _repository(tmp_path)
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "test",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None

    with pytest.raises(
        AuthorityRepositoryError,
        match="terminal success requires record_output_commit",
    ):
        repository.finish_stage_attempt(
            RUN_URI,
            "test",
            attempt_id=allocation.attempt.attempt_id,
            owner_id="worker-1",
            fencing_token=allocation.lease.fencing_token,
            to_status=StageStatus.SUCCEEDED,
            service_generation="generation-1",
        )

    snapshot = repository.open_run(RUN_URI)
    assert snapshot.stages[0].status is StageStatus.RUNNING
    assert snapshot.stages[0].attempts[0].status is StageStatus.RUNNING
    assert snapshot.stages[0].active_lease == allocation.lease
