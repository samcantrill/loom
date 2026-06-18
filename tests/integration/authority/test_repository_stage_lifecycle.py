"""File-backed stage lifecycle tests for the private authority repository."""

from __future__ import annotations

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.read_models import RecoveryKind
from loom.authority._repository import (
    AuthorityRepository,
    AuthorityRepositoryError,
)


pytestmark = pytest.mark.integration

RUN_URI = "file:///runs/integration-stage-r1"


def test_stage_output_commit_persists_across_repository_handles(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")
    repository.admit_run(RUN_URI)
    repository.transition_stage(
        RUN_URI,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
    )
    allocation = repository.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    output = ArtifactRef(
        artifact_id="build/out",
        uri=f"{RUN_URI}/artifacts/build/out.json",
        artifact_type="json",
        metadata={"size": 123},
    )
    commit = repository.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
        service_generation="generation-1",
    )

    reopened = AuthorityRepository(tmp_path)
    snapshot = reopened.open_run(RUN_URI)
    stage = snapshot.stages[0]

    assert stage.stage_name == "build"
    assert stage.status is StageStatus.SUCCEEDED
    assert stage.active_lease is None
    assert stage.latest_commit == commit.commit
    assert stage.artifact_facts == commit.artifact_facts


def test_expired_stage_lease_recovery_and_retry(tmp_path) -> None:
    repository = AuthorityRepository(
        tmp_path, clock=lambda: "2020-01-01T00:00:00Z"
    )
    repository.initialize(service_generation="generation-1")
    repository.admit_run(RUN_URI)
    first = repository.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=1,
    )
    assert first.lease is not None

    later = AuthorityRepository(
        tmp_path, clock=lambda: "2020-01-01T00:00:02Z"
    )
    recovery = later.scan_recovery(RUN_URI)

    assert {record.kind for record in recovery} == {
        RecoveryKind.EXPIRED_LEASE,
        RecoveryKind.ABANDONED_ATTEMPT,
    }
    with pytest.raises(AuthorityRepositoryError, match="expired"):
        later.record_output_commit(
            RUN_URI,
            "build",
            attempt_id=first.attempt.attempt_id,
            owner_id="worker-1",
            fencing_token=first.lease.fencing_token,
            outputs={
                "out": ArtifactRef(
                    artifact_id="build/out",
                    uri=f"{RUN_URI}/artifacts/build/out.json",
                    artifact_type="json",
                )
            },
            service_generation="generation-1",
        )

    retry = later.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-2",
        lease_ttl_seconds=30,
    )
    assert retry.attempt.attempt == 2
    assert retry.lease is not None


def test_stage_lifecycle_transaction_rolls_back_failed_write(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")
    repository.admit_run(RUN_URI)

    with pytest.raises(RuntimeError, match="rollback"):
        with repository.transaction() as conn:
            conn.execute(
                """
                INSERT INTO authority_stages (
                    run_uri, stage_name, status, revision_sequence, reason_json
                )
                VALUES ('file:///runs/rolled-back', 'build', 'PENDING', 1, NULL)
                """
            )
            raise RuntimeError("rollback")

    with pytest.raises(AuthorityRepositoryError, match="unknown run"):
        repository.open_run("file:///runs/rolled-back")
