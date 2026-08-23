"""Unit coverage for the private SQLite authority backend."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.event_sinks import (
    EventObserverExternalRef,
    EventObserverLinkRecord,
    EventSinkFailureRecord,
)
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.reliability import (
    FailureClassification,
    ReliabilityPolicy,
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    RetryPolicy,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthoritySchemaError,
    AuthorityStoreError,
    AuthoritySchemaFailureKind,
    BackendCapability,
    BackendRevision,
    CapabilityScope,
    CapabilitySupport,
    LeaseState,
    LifecycleReason,
    PreparedAttemptReceipt,
    PreparedAttemptRequest,
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
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


def _prepared_request(
    revision: BackendRevision,
    *,
    operation_id: str = "prepare-1",
    stage_status: StageStatus | None = None,
    attempt_id: str | None = None,
    next_attempt: int = 1,
    retry_decision_id: str | None = None,
) -> PreparedAttemptRequest:
    return PreparedAttemptRequest(
        operation_id=operation_id,
        request_digest=f"digest-{operation_id}",
        admission_id="admission-1",
        stage_name="build",
        readiness_generation=f"generation-{next_attempt}",
        expected_revision=revision,
        expected_stage_status=stage_status,
        expected_attempt_id=attempt_id,
        next_attempt=next_attempt,
        owner_id="coordinator",
        plan_fingerprint="plan-1",
        bound_inputs={},
        upstream_commits={},
        retry_decision_id=retry_decision_id,
    )


def _reliability_status(run_uri: str) -> ReliabilityStatusDetail:
    return ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=RunStatus.RUNNING,
        stage_id="build",
        stage_status=StageStatus.FAILED,
        attempt=1,
        created_at="2020-01-01T00:00:00Z",
    )


def _reliability_transaction(run_uri: str) -> StageAttemptTransaction:
    status = _reliability_status(run_uri)
    return StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri=run_uri,
        stage_id=status.stage_id,
        attempt=status.attempt,
        status=status,
    )


def _retry_decision(run_uri: str) -> RetryDecisionRecord:
    status = _reliability_status(run_uri)
    return RetryDecisionRecord(
        decision_id="retry-1",
        transaction_id="tx-1",
        should_retry=False,
        next_attempt=None,
        decision_reason="policy_disabled",
        policy_max_attempts=1,
        attempt_count=1,
        status=status,
        failure=FailureClassification(
            reason_code="runtime_error",
            status=status,
            retriable=False,
        ),
    )


def _timeout_outcome(run_uri: str) -> TimeoutOutcomeRecord:
    return TimeoutOutcomeRecord(
        outcome_id="timeout-1",
        transaction_id="tx-1",
        timed_out=False,
        duration_seconds=1,
        reason_code="completed",
        status=_reliability_status(run_uri),
    )


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


def test_create_run_fails_loudly_for_incomplete_existing_schema(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    database_path = _authority_database_path(run_uri)
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as conn:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('schema_version', '1')")

    check = store.check_schema(run_uri)
    assert check.failure is not None
    assert check.failure.kind is AuthoritySchemaFailureKind.INVALID

    with pytest.raises(AuthoritySchemaError, match="incomplete or invalid"):
        store.create_run(run_uri)


def test_complete_v1_database_migrates_output_commit_without_losing_facts(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri, "build", owner_id="one", lease_ttl_seconds=30
    )
    assert allocation.lease is not None
    committed = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out", uri=f"{run_uri}/out", artifact_type="json"
            )
        },
    )
    database_path = _authority_database_path(run_uri)
    with sqlite3.connect(database_path) as conn:
        conn.execute("ALTER TABLE commits RENAME TO commits_v2")
        conn.execute("""
            CREATE TABLE commits (
                commit_id TEXT PRIMARY KEY, stage_name TEXT NOT NULL UNIQUE,
                attempt_id TEXT NOT NULL, committed_at TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL, output_names_json TEXT NOT NULL,
                materialized_refs_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO commits SELECT commit_id, stage_name, attempt_id, committed_at,
            revision_sequence, output_names_json, materialized_refs_json FROM commits_v2
        """)
        conn.execute("DROP TABLE commits_v2")
        conn.execute("UPDATE metadata SET value = '1' WHERE key = 'schema_version'")
    history = store.list_output_commits(run_uri)
    assert history == (committed,)
    assert store.check_schema(run_uri).supported


def test_incomplete_v1_database_rejects_migration_without_partial_changes(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    database_path = _authority_database_path(run_uri)
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE artifact_facts")
        conn.execute("UPDATE metadata SET value = '1' WHERE key = 'schema_version'")

    with pytest.raises(AuthoritySchemaError, match="v1 schema is incomplete"):
        store.list_output_commits(run_uri)

    with sqlite3.connect(database_path) as conn:
        version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert version == ("1",)
    assert "commits" in tables
    assert "commits_v1" not in tables


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


def test_sqlite_reliability_facts_are_snapshot_backed_and_immutable(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    policy = ReliabilityPolicyFact(
        run_uri=run_uri,
        scope=ReliabilityPolicyScope.STAGE,
        stage_name="build",
        recorded_at="2020-01-01T00:00:00Z",
        policy=ReliabilityPolicy(retry=RetryPolicy(enabled=False, max_attempts=1)),
    )
    status = _reliability_status(run_uri)
    transaction = _reliability_transaction(run_uri)
    decision = _retry_decision(run_uri)
    timeout = _timeout_outcome(run_uri)

    policy_revision = store.write_reliability_policy_fact(run_uri, policy)
    store.write_reliability_status_detail(run_uri, status)
    transaction_revision = store.write_stage_attempt_transaction(run_uri, transaction)
    same_revision = store.write_stage_attempt_transaction(run_uri, transaction)
    store.write_retry_decision(run_uri, decision)
    store.write_timeout_outcome(run_uri, timeout)

    assert same_revision == transaction_revision
    assert transaction_revision.sequence > policy_revision.sequence
    assert store.list_reliability_policy_facts(run_uri, stage_name="build") == (policy,)
    assert store.read_transaction_chain(run_uri, "tx-1") == (transaction,)
    snapshot = store.snapshot(run_uri)
    stage = snapshot.stages[0]
    assert stage.reliability_policy_facts == (policy,)
    assert stage.reliability_status_details == (status,)
    assert stage.reliability_transactions == (transaction,)
    assert stage.retry_decisions == (decision,)
    assert stage.timeout_outcomes == (timeout,)

    conflicting = StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri=run_uri,
        stage_id="build",
        attempt=2,
        status=ReliabilityStatusDetail(
            run_uri=run_uri,
            run_status=RunStatus.RUNNING,
            stage_id="build",
            stage_status=StageStatus.FAILED,
            attempt=2,
            created_at="2020-01-01T00:00:01Z",
        ),
    )
    with pytest.raises(AuthorityStoreError, match="conflicting reliability fact"):
        store.write_stage_attempt_transaction(run_uri, conflicting)


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


def test_sqlite_authority_persists_observer_facts(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    event = store.append_audit_event(
        run_uri,
        PipelineEvent(scope=EventScope.run(), event_type="run.started"),
    )
    failure = EventSinkFailureRecord(
        sink_name="audit.sink",
        run_uri=run_uri,
        event_reference=event.to_event_reference(),
        failed_at="2020-01-01T00:00:02Z",
        failure_type="RuntimeError",
        failure_message="callback failed",
    )
    link = EventObserverLinkRecord(
        sink_name="audit.sink",
        run_uri=run_uri,
        event_reference=event.to_event_reference(),
        recorded_at="2020-01-01T00:00:03Z",
        external_ref=EventObserverExternalRef(
            kind="trace",
            identifiers={"trace_id": "trace-1"},
        ),
    )

    failure_revision = store.append_event_sink_failure(run_uri, failure)
    link_revision = store.append_event_observer_link(run_uri, link)
    reopened = SQLitePerRunAuthorityStore(clock=FrozenClock())

    assert failure_revision.sequence > event.sequence
    assert link_revision.sequence > failure_revision.sequence
    assert reopened.read_event_sink_failures(run_uri) == (failure,)
    assert reopened.read_event_observer_links(run_uri) == (link,)


def test_expired_lease_cannot_be_released_or_failed(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    clock = FrozenClock()
    store = SQLitePerRunAuthorityStore(clock=clock)
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=1,
    )
    assert allocation.lease is not None
    clock.value = "2020-01-01T00:00:02Z"

    with pytest.raises(ValueError, match="lease has expired"):
        store.release_lease(
            allocation.lease.lease_id,
            owner_id="worker-1",
            fencing_token=allocation.lease.fencing_token,
        )
    with pytest.raises(ValueError, match="lease has expired"):
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
    assert snapshot.stages[0].active_lease is None
    assert (
        SQLitePerRunAuthorityStore(
            run_uri,
            clock=lambda: "2020-01-01T00:01:00Z",
        ).scan_recovery(run_uri)
        == ()
    )


def test_attempt_allocation_after_output_commit_is_rejected(
    tmp_path: Path,
) -> None:
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
    committed = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={"out": output},
    )

    with pytest.raises(ValueError, match="output commit"):
        store.allocate_stage_attempt(
            run_uri,
            "build",
            owner_id="worker-2",
        )

    snapshot = store.snapshot(run_uri)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == committed.commit
    assert snapshot.stages[0].artifact_facts == committed.artifact_facts
    assert [attempt.attempt_id for attempt in snapshot.stages[0].attempts] == [
        allocation.attempt.attempt_id
    ]


def test_attempt_allocation_allows_failed_stage_retry(tmp_path: Path) -> None:
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
    store.transition_stage(
        run_uri,
        "build",
        from_status=StageStatus.RUNNING,
        to_status=StageStatus.FAILED,
    )
    store.release_lease(
        allocation.lease.lease_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
    )

    retry = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-2",
    )

    assert retry.attempt.attempt == 2
    assert retry.attempt.status is StageStatus.RUNNING


def test_output_commit_rejects_terminal_stage_state(tmp_path: Path) -> None:
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
    store.transition_stage(
        run_uri,
        "build",
        from_status=StageStatus.RUNNING,
        to_status=StageStatus.FAILED,
    )

    with pytest.raises(ValueError, match="stage is not running"):
        store.record_output_commit(
            run_uri,
            "build",
            attempt_id=allocation.attempt.attempt_id,
            fencing_token=allocation.lease.fencing_token,
            outputs={
                "out": ArtifactRef(
                    artifact_id="build/out",
                    uri=f"{run_uri}/artifacts/build/out.json",
                    artifact_type="json",
                )
            },
        )


def test_prepared_attempt_is_pending_and_replays_the_authority_receipt(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "prepared-run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    revision = store.create_run(run_uri)
    request = PreparedAttemptRequest(
        operation_id="prepare-1",
        request_digest="digest-1",
        admission_id="admission-1",
        stage_name="build",
        readiness_generation="generation-1",
        expected_revision=revision,
        expected_stage_status=None,
        expected_attempt_id=None,
        next_attempt=1,
        owner_id="coordinator",
        plan_fingerprint="plan-1",
        bound_inputs={},
        upstream_commits={},
    )
    first = store.ensure_prepared_attempt(run_uri, request)
    replay = store.ensure_prepared_attempt(run_uri, request)
    assert first.attempt.status is StageStatus.PENDING
    assert replay.attempt == first.attempt
    assert PreparedAttemptReceipt.from_dict(first.to_dict()) == first
    with pytest.raises(AuthorityStoreError, match="conflicts"):
        store.ensure_prepared_attempt(
            run_uri, replace(request, request_digest="changed")
        )


def test_prepared_attempt_binding_grant_and_start_are_fenced(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "managed-prepared-run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    prepared = store.ensure_prepared_attempt(
        run_uri,
        _prepared_request(store.create_run(run_uri)),
    )

    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-1", attempt_id=prepared.attempt.attempt_id
    )
    fence = store.grant_prepared_attempt(
        run_uri, assignment_id="assignment-1", attempt_id=prepared.attempt.attempt_id
    )
    assert (
        store.grant_prepared_attempt(
            run_uri,
            assignment_id="assignment-1",
            attempt_id=prepared.attempt.attempt_id,
        )
        == fence
    )
    with pytest.raises(AuthorityStoreError, match="ungranted"):
        store.unbind_prepared_attempt(
            run_uri,
            assignment_id="assignment-1",
            attempt_id=prepared.attempt.attempt_id,
        )
    store.confirm_execution_started(run_uri, fence=fence)
    store.confirm_execution_started(run_uri, fence=fence)
    with pytest.raises(AuthorityStoreError, match="stale execution fence"):
        store.confirm_execution_started(
            run_uri,
            fence=replace(fence, fencing_token="stale"),
        )


def test_managed_output_commit_is_current_fence_idempotent_and_terminal(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "managed-output-run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    prepared = store.ensure_prepared_attempt(
        run_uri,
        _prepared_request(store.create_run(run_uri)),
    )
    store.bind_prepared_attempt(
        run_uri,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    fence = store.grant_prepared_attempt(
        run_uri,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    artifact = ArtifactRef(
        artifact_id="build/out",
        uri=f"{run_uri}/artifacts/build/out.json",
        artifact_type="json",
    )

    first = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=prepared.attempt.attempt_id,
        fencing_token=fence.fencing_token,
        outputs={"out": artifact},
        assignment_id="assignment-1",
    )
    replay = store.record_output_commit(
        run_uri,
        "build",
        attempt_id=prepared.attempt.attempt_id,
        fencing_token=fence.fencing_token,
        outputs={"out": artifact},
        assignment_id="assignment-1",
    )

    assert replay == first
    assert store.snapshot(run_uri).stages[0].status is StageStatus.SUCCEEDED
    store.bind_prepared_attempt(
        run_uri,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    assert (
        store.grant_prepared_attempt(
            run_uri,
            assignment_id="assignment-1",
            attempt_id=prepared.attempt.attempt_id,
        )
        == fence
    )
    store.confirm_execution_started(run_uri, fence=fence)
    with pytest.raises(AuthorityStoreError, match="conflicts"):
        store.record_output_commit(
            run_uri,
            "build",
            attempt_id=prepared.attempt.attempt_id,
            fencing_token=fence.fencing_token,
            outputs={"out": artifact},
            reason=LifecycleReason(code="changed-replay"),
            assignment_id="assignment-1",
        )
    with pytest.raises(AuthorityStoreError, match="stale execution fence"):
        store.record_output_commit(
            run_uri,
            "build",
            attempt_id=prepared.attempt.attempt_id,
            fencing_token="stale",
            outputs={"out": artifact},
            assignment_id="assignment-1",
        )


def test_managed_failure_can_terminalize_from_submitted_and_replays(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "managed-failure-run")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    prepared = store.ensure_prepared_attempt(
        run_uri,
        _prepared_request(store.create_run(run_uri)),
    )
    store.bind_prepared_attempt(
        run_uri,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    fence = store.grant_prepared_attempt(
        run_uri,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    reason = LifecycleReason(
        code="managed_start_failed", message="no process was created"
    )

    first = store.record_managed_attempt_terminal(
        run_uri, fence=fence, status=StageStatus.FAILED, reason=reason
    )
    replay = store.record_managed_attempt_terminal(
        run_uri, fence=fence, status=StageStatus.FAILED, reason=reason
    )

    assert replay.revision == first.revision
    assert store.snapshot(run_uri).stages[0].status is StageStatus.FAILED
    with pytest.raises(AuthorityStoreError, match="conflicts"):
        store.record_managed_attempt_terminal(
            run_uri,
            fence=fence,
            status=StageStatus.CANCELLED,
            reason=LifecycleReason(code="managed_cancelled"),
        )


def test_v3_authority_database_migrates_managed_fence_table(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "v3-managed-migration")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    database = _authority_database_path(run_uri)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE managed_attempt_bindings")
        conn.execute("UPDATE metadata SET value = '3' WHERE key = 'schema_version'")

    reopened = SQLitePerRunAuthorityStore(clock=FrozenClock())
    reopened.open_run(run_uri)

    assert reopened.check_schema(run_uri).failure is None
    with sqlite3.connect(database) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(managed_attempt_bindings)")
        }
    assert {"terminal_status", "terminal_digest"}.issubset(columns)


def test_v4_authority_database_migrates_managed_unbind_receipts(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "v4-managed-unbind-migration")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri)
    database = _authority_database_path(run_uri)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE managed_attempt_unbind_receipts")
        conn.execute("UPDATE metadata SET value = '4' WHERE key = 'schema_version'")

    reopened = SQLitePerRunAuthorityStore(clock=FrozenClock())
    reopened.open_run(run_uri)

    assert reopened.check_schema(run_uri).failure is None
    with sqlite3.connect(database) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert "managed_attempt_unbind_receipts" in tables


def test_prepared_attempt_revalidates_revision_and_terminal_run(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "stale-preparation")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    initial = store.create_run(run_uri)
    store.transition_run(
        run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING
    )
    with pytest.raises(AuthorityStoreError, match="stale authority revision"):
        store.ensure_prepared_attempt(run_uri, _prepared_request(initial))

    terminal_uri = path_to_run_uri(tmp_path / "terminal-preparation")
    terminal = SQLitePerRunAuthorityStore(clock=FrozenClock())
    revision = terminal.create_run(terminal_uri, status=RunStatus.CANCELLED)
    with pytest.raises(AuthorityStoreError, match="terminal or cancelling"):
        terminal.ensure_prepared_attempt(terminal_uri, _prepared_request(revision))


def test_prepared_attempt_requires_authority_retry_decision(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "retry-preparation")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri, status=RunStatus.RUNNING)
    allocation = store.allocate_stage_attempt(run_uri, "build", owner_id="worker")
    failed = store.transition_stage(
        run_uri,
        "build",
        from_status=StageStatus.RUNNING,
        to_status=StageStatus.FAILED,
    )
    unauthorized = _prepared_request(
        failed.revision,
        stage_status=StageStatus.FAILED,
        attempt_id=allocation.attempt.attempt_id,
        next_attempt=2,
    )
    with pytest.raises(AuthorityStoreError, match="retry is not authorized"):
        store.ensure_prepared_attempt(run_uri, unauthorized)

    status = _reliability_status(run_uri)
    decision = RetryDecisionRecord(
        decision_id="retry-authorized",
        transaction_id="tx-authorized",
        should_retry=True,
        next_attempt=2,
        decision_reason="transient",
        policy_max_attempts=2,
        attempt_count=1,
        status=status,
        failure=FailureClassification(
            reason_code="runtime_error",
            status=status,
            retriable=True,
        ),
    )
    revision = store.write_retry_decision(run_uri, decision)
    prepared = store.ensure_prepared_attempt(
        run_uri,
        _prepared_request(
            revision,
            stage_status=StageStatus.FAILED,
            attempt_id=allocation.attempt.attempt_id,
            next_attempt=2,
            retry_decision_id=decision.decision_id,
        ),
    )
    assert prepared.attempt.attempt == 2
    assert prepared.attempt.status is StageStatus.PENDING


def test_concurrent_prepared_attempt_replay_creates_one_attempt(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "concurrent-preparation")
    first_store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    revision = first_store.create_run(run_uri, status=RunStatus.RUNNING)
    request = _prepared_request(revision)

    def prepare() -> PreparedAttemptReceipt:
        return SQLitePerRunAuthorityStore(clock=FrozenClock()).ensure_prepared_attempt(
            run_uri, request
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(lambda _: prepare(), range(2)))
    assert receipts[0] == receipts[1]
    snapshot = first_store.open_run(run_uri)
    assert len(snapshot.stages[0].attempts) == 1


def test_v2_migration_preserves_legacy_pending_attempt_without_backfill(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "legacy-pending")
    store = SQLitePerRunAuthorityStore(clock=FrozenClock())
    store.create_run(run_uri, status=RunStatus.RUNNING)
    allocation = store.allocate_stage_attempt(run_uri, "build", owner_id="legacy")
    database_path = _authority_database_path(run_uri)
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "UPDATE attempts SET status = 'PENDING' WHERE attempt_id = ?",
            (allocation.attempt.attempt_id,),
        )
        conn.execute("UPDATE stages SET status = 'PENDING' WHERE stage_name = 'build'")
        conn.execute("DROP TABLE prepared_attempt_receipts")
        conn.execute("UPDATE metadata SET value = '2' WHERE key = 'schema_version'")

    snapshot = store.open_run(run_uri)
    attempt = snapshot.stages[0].attempts[0]
    assert attempt.attempt_id == allocation.attempt.attempt_id
    assert attempt.status is StageStatus.PENDING
    with sqlite3.connect(database_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM prepared_attempt_receipts"
        ).fetchone()
    assert count == (0,)
    with pytest.raises(AuthorityStoreError, match="does not permit"):
        store.ensure_prepared_attempt(
            run_uri,
            _prepared_request(
                snapshot.revision,
                stage_status=StageStatus.PENDING,
                attempt_id=attempt.attempt_id,
                next_attempt=2,
            ),
        )
