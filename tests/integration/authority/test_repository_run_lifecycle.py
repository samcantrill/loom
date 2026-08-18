"""File-backed run lifecycle tests for the private authority repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores.read_models import (
    CleanupCandidateKind,
    LifecycleReason,
    RecoveryKind,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.authority._repository import (
    AuthorityRepository,
    AuthorityRepositoryError,
    initialize_authority_repository,
)


pytestmark = pytest.mark.integration

RUN_URI = "file:///runs/integration-r1"


def _submitted_record(run_uri: str) -> SubmittedOperationRecord:
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


def test_run_lifecycle_records_persist_across_repository_handles(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    initial = repository.admit_run(RUN_URI)
    running = repository.transition_run(
        RUN_URI,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
        expected_revision=initial,
    )
    submitted_revision = repository.write_submitted_operation(
        RUN_URI,
        _submitted_record(RUN_URI),
        expected_revision=running.revision,
    )
    event = repository.append_audit_event(
        RUN_URI,
        PipelineEvent(
            scope=EventScope.run(),
            event_type="run.started",
            payload={"owner": "controller-1"},
        ),
        expected_revision=submitted_revision,
    )
    cleanup = repository.record_cleanup_candidate(
        RUN_URI,
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri="file:///tmp/payload",
        reason=LifecycleReason(code="test_cleanup"),
        expected_revision=repository.open_run(RUN_URI).revision,
    )
    recovery = repository.record_recovery(
        RUN_URI,
        kind=RecoveryKind.INTERRUPTED_SUBMISSION,
        reason=LifecycleReason(code="manual_recovery"),
        expected_revision=repository.open_run(RUN_URI).revision,
    )

    reopened = AuthorityRepository(tmp_path)
    snapshot = reopened.open_run(RUN_URI)

    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.submitted_operations == (_submitted_record(RUN_URI),)
    assert snapshot.cleanup_candidates == (cleanup,)
    assert reopened.list_audit_events(RUN_URI) == (event,)
    assert reopened.list_recovery_records(RUN_URI) == (recovery,)


def test_repository_enforces_transition_policy_before_persisting(tmp_path) -> None:
    repository = initialize_authority_repository(tmp_path)
    initial = repository.admit_run(RUN_URI)
    running = repository.transition_run(
        RUN_URI,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
        expected_revision=initial,
    )
    succeeded = repository.transition_run(
        RUN_URI,
        from_status=RunStatus.RUNNING,
        to_status=RunStatus.SUCCEEDED,
        expected_revision=running.revision,
    )
    with pytest.raises(AuthorityRepositoryError):
        repository.transition_run(
            RUN_URI,
            from_status=RunStatus.SUCCEEDED,
            to_status=RunStatus.RUNNING,
            expected_revision=succeeded.revision,
        )
    resumed = repository.transition_run(
        RUN_URI,
        from_status=RunStatus.SUCCEEDED,
        to_status=RunStatus.RUNNING,
        expected_revision=succeeded.revision,
        intent=TransitionIntent.RESUME,
    )
    pending = repository.transition_stage(
        RUN_URI,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
        expected_revision=resumed.revision,
    )
    stage_running = repository.transition_stage(
        RUN_URI,
        "build",
        from_status=StageStatus.PENDING,
        to_status=StageStatus.RUNNING,
        expected_revision=pending.revision,
    )
    stage_succeeded = repository.transition_stage(
        RUN_URI,
        "build",
        from_status=StageStatus.RUNNING,
        to_status=StageStatus.SUCCEEDED,
        expected_revision=stage_running.revision,
    )
    with pytest.raises(AuthorityRepositoryError):
        repository.transition_stage(
            RUN_URI,
            "build",
            from_status=StageStatus.SUCCEEDED,
            to_status=StageStatus.PENDING,
            expected_revision=stage_succeeded.revision,
        )
    repository.transition_stage(
        RUN_URI,
        "build",
        from_status=StageStatus.SUCCEEDED,
        to_status=StageStatus.PENDING,
        expected_revision=stage_succeeded.revision,
        intent=TransitionIntent.RESUME,
    )


def test_repository_event_retry_precedes_stale_revision_rejection(tmp_path) -> None:
    repository = initialize_authority_repository(tmp_path)
    initial = repository.admit_run(RUN_URI)
    event = PipelineEvent(
        event_id="event-1",
        scope=EventScope.run(),
        event_type="run.started",
    )

    first = repository.append_audit_event(
        RUN_URI,
        event,
        expected_revision=initial,
    )
    assert (
        repository.append_audit_event(
            RUN_URI,
            event,
            expected_revision=initial,
        )
        == first
    )
    with pytest.raises(AuthorityRepositoryError, match="conflicts"):
        repository.append_audit_event(
            RUN_URI,
            PipelineEvent(
                event_id="event-1",
                scope=EventScope.run(),
                event_type="run.failed",
            ),
            expected_revision=initial,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale run revision"):
        repository.append_audit_event(
            RUN_URI,
            PipelineEvent(
                event_id="event-2",
                scope=EventScope.run(),
                event_type="run.completed",
            ),
            expected_revision=initial,
        )


def test_legacy_audit_table_accepts_per_run_event_sequences(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    run_a = "file:///runs/integration-r1"
    run_b = "file:///runs/integration-r2"
    repository.admit_run(run_a)
    repository.admit_run(run_b)
    _replace_audit_events_with_legacy_table(repository.database_path, run_uri=run_a)

    event_b = repository.append_audit_event(
        run_b,
        PipelineEvent(scope=EventScope.run(), event_type="run.started"),
    )
    event_a = repository.append_audit_event(
        run_a,
        PipelineEvent(scope=EventScope.run(), event_type="run.completed"),
    )

    assert event_b.sequence == 1
    assert event_a.sequence == 2
    assert [event.event_type for event in repository.list_audit_events(run_a)] == [
        "run.legacy",
        "run.completed",
    ]
    assert repository.list_audit_events(run_b) == (event_b,)
    with sqlite3.connect(repository.database_path) as conn:
        conn.row_factory = sqlite3.Row
        pk_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(audit_events)")
            if row["pk"]
        }
    assert pk_columns == {"run_uri", "sequence"}


def test_controller_lease_expiry_is_recovered_from_file_backed_state(tmp_path) -> None:
    now = "2020-01-01T00:00:00Z"
    repository = AuthorityRepository(tmp_path, clock=lambda: now)
    repository.initialize(service_generation="generation-1")
    revision = repository.admit_run(RUN_URI)
    lease = repository.acquire_controller_lease(
        RUN_URI,
        owner_id="controller-1",
        lease_ttl_seconds=1,
        expected_revision=revision,
    )

    later = AuthorityRepository(
        tmp_path,
        clock=lambda: "2020-01-01T00:00:02Z",
    )
    recovery = later.scan_recovery(RUN_URI)

    assert recovery[0].kind is RecoveryKind.EXPIRED_LEASE
    assert recovery[0].recovery_id == f"expired-{lease.lease_id}"
    with pytest.raises(AuthorityRepositoryError, match="expired"):
        later.release_controller_lease(
            RUN_URI,
            lease.lease_id,
            owner_id="controller-1",
            fencing_token=lease.fencing_token,
        )


def test_run_lifecycle_transaction_rolls_back_failed_write(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    repository.admit_run(RUN_URI)

    with pytest.raises(RuntimeError, match="rollback"):
        with repository.transaction() as conn:
            conn.execute(
                """
                INSERT INTO authority_runs (
                    run_uri, status, metadata_json, created_revision_sequence,
                    updated_revision_sequence, reason_json
                )
                VALUES ('file:///runs/rolled-back', 'CREATED', '{}', 1, 1, NULL)
                """
            )
            raise RuntimeError("rollback")

    with pytest.raises(AuthorityRepositoryError, match="unknown run"):
        repository.open_run("file:///runs/rolled-back")


def _replace_audit_events_with_legacy_table(
    database_path: Path, *, run_uri: str
) -> None:
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_audit_events_run")
        conn.execute("DROP TABLE audit_events")
        conn.execute(
            """
            CREATE TABLE audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_uri TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_run
                ON audit_events(run_uri, sequence)
            """
        )
        conn.execute(
            """
            INSERT INTO audit_events (
                run_uri, timestamp, scope_json, event_type, payload_json,
                revision_sequence
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_uri,
                "2020-01-01T00:00:00Z",
                '{"kind":"RUN","stage_name":null}',
                "run.legacy",
                "{}",
                1,
            ),
        )
