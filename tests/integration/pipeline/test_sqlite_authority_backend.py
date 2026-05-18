"""Integration coverage for run-local SQLite authority behavior."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from shutil import move

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup import (
    CleanupDeleteIntent,
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupResult,
    CleanupResultEntry,
    CleanupResultOutcome,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.pipeline.status import StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import RecoveryKind, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


pytestmark = pytest.mark.integration


@dataclass(slots=True)
class FrozenClock:
    value: str

    def __call__(self) -> str:
        return self.value


def _submitted_record(run_uri: str) -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="subprocess",
        mode="local",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1.json",
        summary_counts={"submitted": 1},
    )


def _cleanup_target(run_uri: str) -> CleanupTargetRef:
    return CleanupTargetRef(
        kind=CleanupTargetKind.LOCAL_PATH,
        uri=f"{run_uri}/tmp/payload",
        target_id="candidate-1",
        ownership_key="run-r1",
    )


def _cleanup_report(run_uri: str) -> CleanupReport:
    return CleanupReport(
        report_id="report-1",
        run_uri=run_uri,
        created_at="2020-01-01T00:00:03Z",
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=_cleanup_target(run_uri),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
    )


def _cleanup_result(run_uri: str) -> CleanupResult:
    return CleanupResult(
        result_id="result-1",
        run_uri=run_uri,
        created_at="2020-01-01T00:00:04Z",
        intent=CleanupDeleteIntent(
            intent_id="intent-1",
            requested_by="operator",
            requested_at="2020-01-01T00:00:04Z",
            reason="sqlite authority integration",
        ),
        entries=(
            CleanupResultEntry(
                candidate_id="candidate-1",
                target=_cleanup_target(run_uri),
                outcome=CleanupResultOutcome.DELETED,
                reason_code="deleted",
                completed_at="2020-01-01T00:00:05Z",
            ),
        ),
    )


def test_multiple_sqlite_connections_allocate_monotonic_attempts(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    SQLitePerRunAuthorityStore(
        run_uri,
        clock=FrozenClock("2020-01-01T00:00:00Z"),
    ).create_run(run_uri)

    def allocate(owner: str) -> int:
        store = SQLitePerRunAuthorityStore(
            run_uri,
            clock=FrozenClock("2020-01-01T00:00:00Z"),
        )
        allocation = store.allocate_stage_attempt(
            run_uri,
            "build",
            owner_id=owner,
        )
        return allocation.attempt.attempt

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = sorted(executor.map(allocate, ("worker-1", "worker-2")))

    assert attempts == [1, 2]
    snapshot = SQLitePerRunAuthorityStore(run_uri).snapshot(run_uri)
    assert [attempt.attempt for attempt in snapshot.stages[0].attempts] == [1, 2]


def test_stage_lease_fencing_across_store_instances(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    clock = FrozenClock("2020-01-01T00:00:00Z")
    first = SQLitePerRunAuthorityStore(run_uri, clock=clock)
    second = SQLitePerRunAuthorityStore(run_uri, clock=clock)
    first.create_run(run_uri)
    allocation = first.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None

    with pytest.raises(ValueError, match="active lease"):
        second.allocate_stage_attempt(
            run_uri,
            "build",
            owner_id="worker-2",
            lease_ttl_seconds=30,
        )
    with pytest.raises(ValueError, match="active lease"):
        second.allocate_stage_attempt(
            run_uri,
            "build",
            owner_id="worker-2",
        )

    clock.value = "2020-01-01T00:00:05Z"
    renewed = second.renew_lease(
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        lease_ttl_seconds=30,
    )
    output = ArtifactRef(
        artifact_id="build/out",
        uri=f"{run_uri}/artifacts/build/out.json",
        artifact_type="json",
    )
    commit = second.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=renewed.fencing_token,
        outputs={"out": output},
    )

    snapshot = first.snapshot(run_uri)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == commit.commit


def test_run_root_movement_reconstructs_current_run_uri_fields(
    tmp_path: Path,
) -> None:
    original_root = tmp_path / "original"
    moved_root = tmp_path / "moved"
    original_uri = path_to_run_uri(original_root)
    store = SQLitePerRunAuthorityStore(
        original_uri,
        clock=FrozenClock("2020-01-01T00:00:00Z"),
    )
    store.create_run(original_uri)
    allocation = store.allocate_stage_attempt(
        original_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    store.write_submitted_operation(original_uri, _submitted_record(original_uri))

    move(str(original_root), str(moved_root))
    moved_uri = path_to_run_uri(moved_root)
    moved_store = SQLitePerRunAuthorityStore(
        moved_uri,
        clock=FrozenClock("2020-01-01T00:00:05Z"),
    )
    snapshot = moved_store.snapshot(moved_uri)

    assert snapshot.run_uri == moved_uri
    assert snapshot.submitted_operations[0].run_uri == moved_uri
    assert snapshot.stages[0].attempts[0].run_uri == moved_uri
    assert snapshot.stages[0].active_lease is not None
    assert snapshot.stages[0].active_lease.run_uri == moved_uri


def test_cleanup_report_and_result_facts_persist_across_sqlite_instances(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    first = SQLitePerRunAuthorityStore(
        run_uri,
        clock=FrozenClock("2020-01-01T00:00:00Z"),
    )
    first.create_run(run_uri)
    report = _cleanup_report(run_uri)
    result = _cleanup_result(run_uri)

    report_fact = first.append_cleanup_report(run_uri, report)
    result_fact = first.append_cleanup_result(run_uri, result)

    second = SQLitePerRunAuthorityStore(run_uri)
    assert second.list_cleanup_reports(run_uri) == (report_fact,)
    assert second.list_cleanup_results(run_uri) == (result_fact,)
    snapshot = second.snapshot(run_uri)
    assert snapshot.cleanup_reports == (report_fact,)
    assert snapshot.cleanup_results == (result_fact,)
    assert snapshot.revision.sequence == result_fact.revision.sequence


def test_recovery_scan_reports_expired_leases_attempts_and_active_submissions(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(
        run_uri,
        clock=FrozenClock("2020-01-01T00:00:00Z"),
    )
    store.create_run(run_uri)
    store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=1,
    )
    store.write_submitted_operation(run_uri, _submitted_record(run_uri))

    recovery = SQLitePerRunAuthorityStore(
        run_uri,
        clock=FrozenClock("2020-01-01T00:00:02Z"),
    ).scan_recovery(run_uri)
    kinds = {record.kind for record in recovery}

    assert RecoveryKind.EXPIRED_LEASE in kinds
    assert RecoveryKind.ABANDONED_ATTEMPT in kinds
    assert RecoveryKind.INTERRUPTED_SUBMISSION in kinds
