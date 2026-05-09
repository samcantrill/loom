"""Unit coverage for the private SQLite authority backend."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthoritySchemaFailureKind,
    BackendCapability,
    CapabilityScope,
    CapabilitySupport,
    LeaseState,
    LifecycleReason,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import (
    SQLitePerRunAuthorityStore,
    _authority_database_path,
)


pytestmark = pytest.mark.unit


@dataclass(slots=True)
class FrozenClock:
    value: str = "2020-01-01T00:00:00Z"

    def __call__(self) -> str:
        return self.value


def test_schema_policy_reports_missing_invalid_older_and_newer(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())

    missing = store.check_schema(run_uri)
    assert missing.failure is not None
    assert missing.failure.kind is AuthoritySchemaFailureKind.MISSING

    database_path = _authority_database_path(run_uri)
    database_path.parent.mkdir(parents=True)
    database_path.write_text("not sqlite", encoding="utf-8")
    invalid = store.check_schema(run_uri)
    assert invalid.failure is not None
    assert invalid.failure.kind is AuthoritySchemaFailureKind.INVALID

    database_path.unlink()
    store.create_run(run_uri)
    with sqlite3.connect(database_path) as conn:
        conn.execute("UPDATE metadata SET value = '0' WHERE key = 'schema_version'")
    older = store.check_schema(run_uri)
    assert older.failure is not None
    assert older.failure.kind is AuthoritySchemaFailureKind.INVALID

    with sqlite3.connect(database_path) as conn:
        conn.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
    newer = store.check_schema(run_uri)
    assert newer.failure is not None
    assert newer.failure.kind is AuthoritySchemaFailureKind.UNSUPPORTED_NEWER


def test_capabilities_are_honest_about_phase_2_limits() -> None:
    capabilities = SQLitePerRunAuthorityStore().capabilities()

    assert capabilities.supports(
        BackendCapability.ATOMIC_OUTPUT_COMMIT,
        scope=CapabilityScope.PER_RUN,
    )
    assert not capabilities.supports(
        BackendCapability.MATERIALIZATION_REFS,
        scope=CapabilityScope.PER_RUN,
    )
    assert not capabilities.supports(
        BackendCapability.CROSS_RUN_COORDINATION,
        scope=CapabilityScope.CROSS_RUN,
    )
    unsupported = capabilities.require(
        BackendCapability.GLOBAL_COUNTERS,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert unsupported is not None
    record = next(
        record
        for record in capabilities.records
        if record.capability is BackendCapability.GLOBAL_COUNTERS
    )
    assert record.support is CapabilitySupport.UNSUPPORTED


def test_revisions_advance_with_each_sqlite_mutation(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())

    first = store.create_run(run_uri)
    second = store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    ).revision
    third = store.transition_stage(
        run_uri,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
    ).revision

    assert [first.sequence, second.sequence, third.sequence] == [1, 2, 3]
    assert store.snapshot(run_uri).revision.sequence == 3


def test_lease_fencing_release_failure_and_audit_sequence(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None

    with pytest.raises(ValueError, match="stale or foreign lease token"):
        store.release_lease(
            allocation.lease.lease_id,
            owner_id="worker-2",
            fencing_token=allocation.lease.fencing_token,
        )

    event_1 = store.append_audit_event(
        run_uri,
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.started"),
    )
    event_2 = store.append_audit_event(
        run_uri,
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.running"),
    )
    assert (event_1.sequence, event_2.sequence) == (1, 2)

    released = store.release_lease(
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
    )
    assert released.state is LeaseState.RELEASED

    with pytest.raises(ValueError, match="lease is not active"):
        store.fail_lease(
            allocation.lease.lease_id,
            owner_id="worker-1",
            fencing_token=allocation.lease.fencing_token,
            reason=LifecycleReason(code="worker_failed"),
        )


def test_output_commit_requires_active_stage_fence(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    output = ArtifactRef(
        artifact_id="build/out",
        uri=f"{run_uri}/artifacts/build/out.json",
        artifact_type="json",
    )

    with pytest.raises(ValueError, match="stale or foreign lease token"):
        store.record_output_commit(
            run_uri,
            "build",
            attempt_id=allocation.attempt.attempt_id,
            fencing_token="wrong-token",
            outputs={"out": output},
        )

    committed = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
    )

    assert committed.commit.revision.sequence > allocation.attempt.revision.sequence
    assert committed.artifact_facts[0].artifact == output
    snapshot = store.snapshot(run_uri)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == committed.commit
