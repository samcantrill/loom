"""Unit tests for v9 authority contract models."""

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
from loom.pipeline.reliability import (
    ReliabilityPolicy,
    ReliabilityStatusDetail,
    RetryPolicy,
    StageAttemptTransaction,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AUTHORITY_SCHEMA_VERSION,
    ArtifactFactRecord,
    AttemptAllocation,
    AuthoritativeRunSnapshot,
    AuthoritySchemaCheck,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
    AuthorityModelError,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    CapabilitySupport,
    CleanupCandidate,
    CleanupCandidateKind,
    CleanupReportFact,
    CleanupResultFact,
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    CoordinationStoreError,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    MaterializedRef,
    MaterializedRefKind,
    OutputCommit,
    OutputCommitRecord,
    ReadModelWarning,
    ReadModelWarningCode,
    RecoveryKind,
    RecoveryRecord,
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
    ResourceLeaseRecord,
    StageAttempt,
    StageLifecycleSnapshot,
    StatusTransition,
    StaticOutcomeKind,
    StaticOutcomeRecord,
    StoreDiagnostic,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    TrialState,
    UnsupportedCapabilityCode,
    UnsupportedCapability,
    WorkspaceIdentity,
    check_authority_schema_version,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState


def test_backend_capability_set_reports_machine_readable_unsupported_result() -> None:
    capabilities = BackendCapabilitySet(
        backend_name="fake",
        records=(
            BackendCapabilityRecord(
                capability=BackendCapability.ATOMIC_TRANSITIONS,
                scope=CapabilityScope.PER_RUN,
            ),
        ),
    )

    unsupported = capabilities.require(
        BackendCapability.CROSS_RUN_COORDINATION,
        scope=CapabilityScope.CROSS_RUN,
    )

    assert unsupported is not None
    assert unsupported.code is UnsupportedCapabilityCode.MISSING_CAPABILITY
    diagnostic = unsupported.to_diagnostic()
    assert isinstance(diagnostic, StoreDiagnostic)
    assert diagnostic.to_dict()["detail"] == {
        "capability": "cross_run_coordination",
        "scope": "cross_run",
    }


def test_backend_capability_set_preserves_declared_unsupported_detail() -> None:
    capabilities = BackendCapabilitySet(
        backend_name="legacy",
        records=(
            BackendCapabilityRecord(
                capability=BackendCapability.STAGE_LEASES,
                scope=CapabilityScope.PER_RUN,
                support=CapabilitySupport.UNSUPPORTED,
                message="stage leases are unavailable",
                detail={"backend": "legacy"},
            ),
        ),
    )

    unsupported = capabilities.require(
        BackendCapability.STAGE_LEASES,
        scope=CapabilityScope.PER_RUN,
    )

    assert unsupported is not None
    assert unsupported.message == "stage leases are unavailable"
    assert unsupported.detail == {"backend": "legacy"}
    assert unsupported.to_diagnostic().to_dict()["detail"] == {
        "capability": "stage_leases",
        "scope": "per_run",
        "backend": "legacy",
    }
    assert (
        BackendCapabilityRecord.from_dict(capabilities.records[0].to_dict())
        == capabilities.records[0]
    )
    assert BackendCapabilitySet.from_dict(capabilities.to_dict()) == capabilities
    assert UnsupportedCapability.from_dict(unsupported.to_dict()) == unsupported
    diagnostic = unsupported.to_diagnostic()
    assert StoreDiagnostic.from_dict(diagnostic.to_dict()) == diagnostic


def test_authority_schema_policy_loudly_rejects_old_and_new_active_state() -> None:
    current = check_authority_schema_version(
        {"schema_version": AUTHORITY_SCHEMA_VERSION}
    )
    older = check_authority_schema_version({"schema_version": 1}, current_version=2)
    newer = check_authority_schema_version(
        {"schema_version": AUTHORITY_SCHEMA_VERSION + 1}
    )

    assert current.supported
    assert older.failure is not None
    assert older.failure.kind is AuthoritySchemaFailureKind.UNSUPPORTED_OLDER
    assert newer.failure is not None
    assert newer.failure.kind is AuthoritySchemaFailureKind.UNSUPPORTED_NEWER
    assert AuthoritySchemaCheck.from_dict(current.to_dict()) == current
    assert AuthoritySchemaFailure.from_dict(older.failure.to_dict()) == older.failure


def test_authority_read_models_serialize_attempts_leases_commits_and_warnings() -> None:
    revision = BackendRevision(
        sequence=1,
        token="rev-1",
        created_at="2020-01-01T00:00:00Z",
    )
    reason = LifecycleReason(code="not_selected", message="branch was not selected")
    attempt = StageAttempt(
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt=1,
        attempt_id="build-1",
        status=StageStatus.RUNNING,
        revision=revision,
        created_at="2020-01-01T00:00:00Z",
        owner="worker-1",
    )
    lease = LeaseRecord(
        lease_id="lease-1",
        kind=LeaseKind.STAGE,
        owner_id="worker-1",
        fencing_token="fence-1",
        acquired_at="2020-01-01T00:00:00Z",
        renewed_at="2020-01-01T00:00:00Z",
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
    )
    materialized = MaterializedRef(
        kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
        uri="file:///runs/r1/artifacts/build/out.json",
        exists=True,
    )
    commit = OutputCommitRecord(
        commit_id="commit-1",
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
        committed_at="2020-01-01T00:00:01Z",
        revision=revision,
        output_names=("out",),
        materialized_refs=(materialized,),
    )
    fact = ArtifactFactRecord(
        artifact_name="out",
        artifact=ArtifactRef(
            artifact_id="build/out",
            uri="file:///runs/r1/artifacts/build/out.json",
            artifact_type="json",
        ),
        commit_id=commit.commit_id,
        revision=revision,
    )
    policy_fact = ReliabilityPolicyFact(
        run_uri="file:///runs/r1",
        scope=ReliabilityPolicyScope.STAGE,
        stage_name="build",
        recorded_at="2020-01-01T00:00:00Z",
        policy=ReliabilityPolicy(retry=RetryPolicy(enabled=True, max_attempts=2)),
    )
    status_detail = ReliabilityStatusDetail(
        run_uri="file:///runs/r1",
        run_status=RunStatus.RUNNING,
        stage_id="build",
        stage_status=StageStatus.RUNNING,
        attempt=1,
        created_at="2020-01-01T00:00:00Z",
    )
    transaction = StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri="file:///runs/r1",
        stage_id="build",
        attempt=1,
        status=status_detail,
    )
    cleanup = CleanupCandidate(
        candidate_id="cleanup-1",
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri="file:///runs/r1/staging/build/out.tmp",
        reason=LifecycleReason(code="commit_failed"),
        recorded_at="2020-01-01T00:00:02Z",
        revision=revision,
    )
    recovery = RecoveryRecord(
        recovery_id="recovery-1",
        kind=RecoveryKind.EXPIRED_LEASE,
        reason=LifecycleReason(code="lease_expired"),
        detected_at="2020-01-01T00:00:03Z",
        revision=revision,
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
    )
    outcome = StaticOutcomeRecord(
        run_uri="file:///runs/r1",
        stage_name="maybe",
        outcome=StaticOutcomeKind.NOT_SELECTED,
        status=StageStatus.SKIPPED,
        reason=reason,
        revision=revision,
    )
    warning = ReadModelWarning(
        code=ReadModelWarningCode.MISSING_MATERIALIZED_REF,
        message="payload missing",
        revision=revision,
    )
    submitted = SubmittedOperationRecord(
        run_uri="file:///runs/r1",
        submission_id="submission-1",
        backend="local",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/submission-1.json",
        summary_counts={"submitted": 1},
    )
    stage_snapshot = StageLifecycleSnapshot(
        stage_name="build",
        status=StageStatus.SUCCEEDED,
        revision=revision,
        attempts=(attempt,),
        active_lease=lease,
        latest_commit=commit,
        artifact_facts=(fact,),
        reliability_policy_facts=(policy_fact,),
        reliability_status_details=(status_detail,),
        reliability_transactions=(transaction,),
        reason=reason,
    )
    run_snapshot = AuthoritativeRunSnapshot(
        run_uri="file:///runs/r1",
        status=RunStatus.SUCCEEDED,
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
        stages=(stage_snapshot,),
        submitted_operations=(submitted,),
        cleanup_candidates=(cleanup,),
        materialized_refs=(materialized,),
        reliability_policy_facts=(policy_fact,),
        warnings=(warning,),
    )
    transition = StatusTransition(
        run_uri="file:///runs/r1",
        status=RunStatus.RUNNING,
        previous_status=RunStatus.CREATED,
        revision=revision,
        reason=LifecycleReason(code="started"),
    )
    allocation = AttemptAllocation(attempt=attempt, lease=lease)
    output = OutputCommit(
        commit=commit,
        artifact_facts=(fact,),
        cleanup_candidates=(cleanup,),
    )

    assert attempt.to_dict()["attempt_id"] == "build-1"
    assert lease.to_dict()["fencing_token"] == "fence-1"
    assert commit.to_dict()["materialized_refs"] == [materialized.to_dict()]
    assert fact.to_dict()["artifact_name"] == "out"
    assert policy_fact.to_dict()["scope"] == "stage"
    assert cleanup.to_dict()["kind"] == "staged_payload"
    assert recovery.to_dict()["kind"] == "expired_lease"
    assert outcome.to_dict()["outcome"] == "not_selected"
    assert warning.to_dict()["code"] == "missing_materialized_ref"
    assert BackendRevision.from_dict(revision.to_dict()) == revision
    assert LifecycleReason.from_dict(reason.to_dict()) == reason
    assert StageAttempt.from_dict(attempt.to_dict()) == attempt
    assert LeaseRecord.from_dict(lease.to_dict()) == lease
    assert MaterializedRef.from_dict(materialized.to_dict()) == materialized
    assert OutputCommitRecord.from_dict(commit.to_dict()) == commit
    assert ArtifactFactRecord.from_dict(fact.to_dict()) == fact
    assert ReliabilityPolicyFact.from_dict(policy_fact.to_dict()) == policy_fact
    assert CleanupCandidate.from_dict(cleanup.to_dict()) == cleanup
    assert RecoveryRecord.from_dict(recovery.to_dict()) == recovery
    assert StaticOutcomeRecord.from_dict(outcome.to_dict()) == outcome
    assert ReadModelWarning.from_dict(warning.to_dict()) == warning
    assert StageLifecycleSnapshot.from_dict(stage_snapshot.to_dict()) == stage_snapshot
    assert AuthoritativeRunSnapshot.from_dict(run_snapshot.to_dict()) == run_snapshot
    assert StatusTransition.from_dict(transition.to_dict()) == transition
    assert AttemptAllocation.from_dict(allocation.to_dict()) == allocation
    assert OutputCommit.from_dict(output.to_dict()) == output


def test_authority_read_models_default_missing_reliability_fields() -> None:
    revision = BackendRevision(sequence=1, token="rev-1")
    stage = StageLifecycleSnapshot(
        stage_name="build",
        status=StageStatus.PENDING,
        revision=revision,
    ).to_dict()
    for field in (
        "reliability_policy_facts",
        "reliability_status_details",
        "reliability_transactions",
        "retry_decisions",
        "timeout_outcomes",
    ):
        stage.pop(field)
    snapshot = AuthoritativeRunSnapshot(
        run_uri="file:///runs/r1",
        status=RunStatus.CREATED,
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
    ).to_dict()
    snapshot["stages"] = [stage]
    snapshot.pop("reliability_policy_facts")

    parsed = AuthoritativeRunSnapshot.from_dict(snapshot)

    assert parsed.reliability_policy_facts == ()
    assert parsed.stages[0].reliability_status_details == ()
    assert parsed.stages[0].retry_decisions == ()


def test_cleanup_report_and_result_facts_round_trip_with_snapshot() -> None:
    revision = BackendRevision(
        sequence=1,
        token="rev-1",
        created_at="2020-01-01T00:00:00Z",
    )
    target = CleanupTargetRef(
        kind=CleanupTargetKind.LOCAL_PATH,
        uri="file:///runs/r1/tmp/payload",
    )
    report = CleanupReport(
        report_id="report-1",
        run_uri="file:///runs/r1",
        created_at="2020-01-01T00:00:01Z",
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=target,
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
    )
    result = CleanupResult(
        result_id="result-1",
        run_uri="file:///runs/r1",
        created_at="2020-01-01T00:00:02Z",
        intent=CleanupDeleteIntent(
            intent_id="intent-1",
            requested_by="operator",
            requested_at="2020-01-01T00:00:02Z",
            reason="cleanup test",
        ),
        entries=(
            CleanupResultEntry(
                candidate_id="candidate-1",
                target=target,
                outcome=CleanupResultOutcome.DELETED,
                reason_code="deleted",
                completed_at="2020-01-01T00:00:03Z",
            ),
        ),
    )
    report_fact = CleanupReportFact(
        report=report,
        recorded_at="2020-01-01T00:00:04Z",
        revision=revision,
    )
    result_fact = CleanupResultFact(
        result=result,
        recorded_at="2020-01-01T00:00:05Z",
        revision=revision,
    )
    snapshot = AuthoritativeRunSnapshot(
        run_uri="file:///runs/r1",
        status=RunStatus.SUCCEEDED,
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
        cleanup_reports=(report_fact,),
        cleanup_results=(result_fact,),
    )

    assert report_fact.report_id == "report-1"
    assert report_fact.run_uri == "file:///runs/r1"
    assert result_fact.result_id == "result-1"
    assert result_fact.run_uri == "file:///runs/r1"
    assert CleanupReportFact.from_dict(report_fact.to_dict()) == report_fact
    assert CleanupResultFact.from_dict(result_fact.to_dict()) == result_fact
    assert AuthoritativeRunSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_workspace_coordination_records_round_trip_with_cross_run_identity() -> None:
    revision = BackendRevision(sequence=1, token="coord-rev-1")
    workspace = WorkspaceIdentity(
        workspace_id="workspace-1",
        root_uri="file:///workspace",
        metadata={"owner": "team"},
    )
    sweep = SweepIdentity(
        sweep_id="sweep-1",
        workspace_id="workspace-1",
        metadata={"budget": 3},
    )
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.CLAIMED,
        revision=revision,
        metadata={"index": 1},
    )
    trial_lease = LeaseRecord(
        lease_id="trial-lease-1",
        kind=LeaseKind.TRIAL,
        owner_id="worker-1",
        fencing_token="trial-fence-1",
        acquired_at="2020-01-01T00:00:00Z",
        renewed_at="2020-01-01T00:00:00Z",
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
    )
    resource_lease = LeaseRecord(
        lease_id="resource-lease-1",
        kind=LeaseKind.RESOURCE,
        owner_id="worker-1",
        fencing_token="resource-fence-1",
        acquired_at="2020-01-01T00:00:00Z",
        renewed_at="2020-01-01T00:00:00Z",
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
        state=LeaseState.ACTIVE,
    )
    trial_record = TrialLeaseRecord(
        workspace_id="workspace-1",
        sweep_id="sweep-1",
        trial_id="trial-1",
        lease=trial_lease,
    )
    resource_record = ResourceLeaseRecord(
        workspace_id="workspace-1",
        resource_key="gpu",
        lease=resource_lease,
        amount=2,
    )
    recovery = CoordinationRecoveryRecord(
        workspace_id="workspace-1",
        sweep_id="sweep-1",
        trial_id="trial-1",
        recovery=RecoveryRecord(
            recovery_id="expired-trial-lease-1",
            kind=RecoveryKind.EXPIRED_LEASE,
            reason=LifecycleReason(code="lease_expired"),
            detected_at="2020-01-01T00:01:01Z",
            revision=revision,
        ),
    )
    resource_recovery = CoordinationRecoveryRecord(
        workspace_id="workspace-1",
        resource_key="gpu",
        amount=2,
        recovery=RecoveryRecord(
            recovery_id="expired-resource-lease-1",
            kind=RecoveryKind.EXPIRED_LEASE,
            reason=LifecycleReason(code="lease_expired"),
            detected_at="2020-01-01T00:01:01Z",
            revision=revision,
        ),
    )
    counter = ConcurrencyCounter(
        counter_name="active_trials",
        value=2,
        limit=4,
        revision=revision,
    )

    assert WorkspaceIdentity.from_dict(workspace.to_dict()) == workspace
    assert SweepIdentity.from_dict(sweep.to_dict()) == sweep
    assert TrialReference.from_dict(trial.to_dict()) == trial
    assert TrialLeaseRecord.from_dict(trial_record.to_dict()) == trial_record
    assert ResourceLeaseRecord.from_dict(resource_record.to_dict()) == resource_record
    assert CoordinationRecoveryRecord.from_dict(recovery.to_dict()) == recovery
    assert (
        CoordinationRecoveryRecord.from_dict(resource_recovery.to_dict())
        == resource_recovery
    )
    assert ConcurrencyCounter.from_dict(counter.to_dict()) == counter
    with pytest.raises(CoordinationStoreError):
        CoordinationRecoveryRecord(
            workspace_id="workspace-1",
            resource_key="gpu",
            recovery=recovery.recovery,
        )


def test_static_not_selected_outcome_keeps_status_enum_coarse() -> None:
    revision = BackendRevision(sequence=1, token="rev-1")

    assert {status.value for status in RunStatus} == {
        "CREATED",
        "PLANNED",
        "RUNNING",
        "SUBMITTED",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "INTERRUPTED",
    }
    with pytest.raises(AuthorityModelError):
        StaticOutcomeRecord(
            run_uri="file:///runs/r1",
            stage_name="maybe",
            outcome=StaticOutcomeKind.NOT_SELECTED,
            status=StageStatus.BLOCKED,
            reason=LifecycleReason(code="not_selected"),
            revision=revision,
        )
