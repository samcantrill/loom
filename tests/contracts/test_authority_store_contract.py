"""Contract tests for backend-neutral per-run authority stores."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

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
from loom.pipeline.event_sinks import (
    EventObserverExternalRef,
    EventObserverLinkRecord,
    EventSinkFailureRecord,
)
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import (
    BackendCapability,
    CapabilityScope,
    LeaseState,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.pipeline.stores.service_authority import (
    LocalAuthorityService,
    create_service_authority_store,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


RUN_URI = "file:///runs/r1"


pytestmark = pytest.mark.contract


@dataclass(frozen=True, slots=True)
class AuthorityStoreCase:
    store: PerRunAuthorityStore
    run_uri: str


@pytest.fixture(params=["in-memory", "service"])
def authority_case(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[AuthorityStoreCase]:
    if request.param == "in-memory":
        yield AuthorityStoreCase(
            store=InMemoryPerRunAuthorityStore(),
            run_uri=RUN_URI,
        )
        return
    with LocalAuthorityService.start() as service:
        yield AuthorityStoreCase(
            store=create_service_authority_store(service.config()),
            run_uri=path_to_run_uri(tmp_path / "r1"),
        )


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


def _event_sink_failure(
    run_uri: str, event: PipelineEventRecord
) -> EventSinkFailureRecord:
    return EventSinkFailureRecord(
        sink_name="audit.sink",
        run_uri=run_uri,
        event_reference=event.to_event_reference(),
        failed_at="2020-01-01T00:00:02Z",
        failure_type="RuntimeError",
        failure_message="callback failed",
        detail={"phase": "contract"},
    )


def _event_observer_link(
    run_uri: str, event: PipelineEventRecord
) -> EventObserverLinkRecord:
    return EventObserverLinkRecord(
        sink_name="audit.sink",
        run_uri=run_uri,
        event_reference=event.to_event_reference(),
        recorded_at="2020-01-01T00:00:03Z",
        external_ref=EventObserverExternalRef(
            kind="trace",
            identifiers={"trace_id": "trace-1"},
        ),
        metadata={"source": "contract"},
    )


def _cleanup_target(run_uri: str) -> CleanupTargetRef:
    return CleanupTargetRef(
        kind=CleanupTargetKind.LOCAL_PATH,
        uri=f"{run_uri}/tmp/payload",
        target_id="candidate-1",
        ownership_key="run-r1",
    )


def _cleanup_report(run_uri: str) -> CleanupReport:
    target = _cleanup_target(run_uri)
    return CleanupReport(
        report_id="report-1",
        run_uri=run_uri,
        created_at="2020-01-01T00:00:04Z",
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=target,
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
    )


def _cleanup_result(run_uri: str) -> CleanupResult:
    target = _cleanup_target(run_uri)
    return CleanupResult(
        result_id="result-1",
        run_uri=run_uri,
        created_at="2020-01-01T00:00:05Z",
        intent=CleanupDeleteIntent(
            intent_id="intent-1",
            requested_by="operator",
            requested_at="2020-01-01T00:00:05Z",
            reason="cleanup contract",
        ),
        entries=(
            CleanupResultEntry(
                candidate_id="candidate-1",
                target=target,
                outcome=CleanupResultOutcome.DELETED,
                reason_code="deleted",
                completed_at="2020-01-01T00:00:06Z",
            ),
        ),
    )


def test_in_memory_store_satisfies_per_run_authority_protocol() -> None:
    store = InMemoryPerRunAuthorityStore()

    assert isinstance(store, PerRunAuthorityStore)
    assert store.capabilities().supports(
        BackendCapability.ATOMIC_OUTPUT_COMMIT,
        scope=CapabilityScope.PER_RUN,
    )


def test_sqlite_store_satisfies_per_run_authority_protocol(tmp_path: Path) -> None:
    store = SQLitePerRunAuthorityStore(path_to_run_uri(tmp_path / "r1"))

    assert isinstance(store, PerRunAuthorityStore)
    assert store.capabilities().supports(
        BackendCapability.ATOMIC_OUTPUT_COMMIT,
        scope=CapabilityScope.PER_RUN,
    )


def test_per_run_authority_contract_records_revisioned_lifecycle_facts(
    authority_case: AuthorityStoreCase,
) -> None:
    store = authority_case.store
    run_uri = authority_case.run_uri
    submitted_record = _submitted_record(run_uri)
    initial_revision = store.create_run(run_uri)

    assert initial_revision.sequence == 1
    assert store.check_schema(run_uri).supported

    transition = store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    )
    assert transition.previous_status is RunStatus.CREATED
    assert transition.status is RunStatus.RUNNING

    store.transition_stage(
        run_uri,
        "build",
        from_status=None,
        to_status=StageStatus.PENDING,
    )
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.attempt.attempt == 1
    assert allocation.lease is not None
    assert allocation.lease.fencing_token

    submitted_revision = store.write_submitted_operation(run_uri, submitted_record)
    assert submitted_revision.sequence > allocation.attempt.revision.sequence
    assert store.read_submitted_operation(run_uri, "sub-1") == submitted_record
    assert store.list_submitted_operations(run_uri) == (submitted_record,)

    output = ArtifactRef(
        artifact_id="build/out",
        uri=f"{run_uri}/artifacts/build/out.json",
        artifact_type="json",
    )
    commit = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
    )
    assert commit.commit.output_names == ("out",)
    assert commit.artifact_facts[0].artifact == output

    event = store.append_audit_event(
        run_uri,
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.succeeded"),
    )
    assert event.sequence == 1
    failure = _event_sink_failure(run_uri, event)
    failure_revision = store.append_event_sink_failure(run_uri, failure)
    link = _event_observer_link(run_uri, event)
    link_revision = store.append_event_observer_link(run_uri, link)

    assert failure_revision.sequence > submitted_revision.sequence
    assert link_revision.sequence > failure_revision.sequence
    assert store.read_event_sink_failures(run_uri) == (failure,)
    assert store.read_event_observer_links(run_uri) == (link,)

    snapshot = store.snapshot(run_uri)
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.schema_version == 1
    assert snapshot.submitted_operations == (submitted_record,)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].attempts[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == commit.commit
    assert snapshot.stages[0].artifact_facts == commit.artifact_facts


def test_per_run_authority_contract_appends_cleanup_facts(
    authority_case: AuthorityStoreCase,
) -> None:
    store = authority_case.store
    run_uri = authority_case.run_uri
    store.create_run(run_uri)
    report = _cleanup_report(run_uri)
    result = _cleanup_result(run_uri)

    report_fact = store.append_cleanup_report(run_uri, report)
    result_fact = store.append_cleanup_result(run_uri, result)

    assert report_fact.report == report
    assert result_fact.result == result
    assert store.append_cleanup_report(run_uri, report) == report_fact
    assert store.append_cleanup_result(run_uri, result) == result_fact
    assert store.list_cleanup_reports(run_uri) == (report_fact,)
    assert store.list_cleanup_results(run_uri) == (result_fact,)
    snapshot = store.snapshot(run_uri)
    assert snapshot.cleanup_reports == (report_fact,)
    assert snapshot.cleanup_results == (result_fact,)

    with pytest.raises(ValueError, match="conflicting cleanup report"):
        store.append_cleanup_report(
            run_uri,
            CleanupReport(
                report_id=report.report_id,
                run_uri=run_uri,
                created_at=report.created_at,
                metadata={"changed": True},
            ),
        )


def test_per_run_authority_rejects_stale_transitions_and_lease_misuse(
    authority_case: AuthorityStoreCase,
) -> None:
    store = authority_case.store
    run_uri = authority_case.run_uri
    store.create_run(run_uri)

    with pytest.raises(ValueError, match="stale run transition"):
        store.transition_run(
            run_uri,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
        )

    allocation = store.allocate_stage_attempt(
        run_uri,
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
            run_uri,
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
        run_uri,
        "build",
        owner_id="worker-2",
        lease_ttl_seconds=1,
    )
    assert retry.lease is not None
    advance_time = getattr(store, "advance_time", None)
    if callable(advance_time):
        advance_time(1)
    elif isinstance(store, SQLitePerRunAuthorityStore):
        store = SQLitePerRunAuthorityStore(
            run_uri, clock=lambda: "2020-01-01T00:00:02Z"
        )
    else:
        raise AssertionError("authority contract case cannot advance backend time")
    recovery = store.scan_recovery(run_uri)
    assert recovery[0].kind.value == "expired_lease"
    assert store.snapshot(run_uri).stages[0].active_lease is None

    with pytest.raises(ValueError, match="expired"):
        store.release_lease(
            retry.lease.lease_id,
            owner_id="worker-2",
            fencing_token=retry.lease.fencing_token,
        )
    with pytest.raises(ValueError, match="expired"):
        store.record_output_commit(
            run_uri,
            "build",
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
