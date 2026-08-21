"""Unit tests for transport-independent authority protocol models."""

from __future__ import annotations

from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AUTHORITY_PROTOCOL_VERSION,
    AUTHORITY_SCHEMA_VERSION,
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    AuthorityProtocolError,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolReadiness,
    AuthorityProtocolRejection,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    AuthorityProtocolVersion,
    AuthorityReadinessState,
    AuthorityResolutionFailureKind,
    AuthorityResolverDiagnostic,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    CleanupCandidate,
    CleanupCandidateKind,
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    DiagnosticSeverity,
    LeaseKind,
    LeaseRecord,
    LifecycleReason,
    MaterializedRef,
    MaterializedRefKind,
    OutputCommitRecord,
    RecoveryKind,
    RecoveryRecord,
    ResourceLeaseRecord,
    StageAttempt,
    StageLifecycleSnapshot,
    StoreDiagnostic,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
    accepted_authority_response,
    protocol_versions_compatible,
    rejected_authority_response,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.serialization import PlainData


_TS = "2020-01-01T00:00:00Z"


def _revision(sequence: int = 1) -> BackendRevision:
    return BackendRevision(
        sequence=sequence,
        token=f"rev-{sequence}",
        created_at=_TS,
    )


def _submitted_operation(run_uri: str = "file:///runs/r1") -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="submission-1",
        backend="slurm",
        mode="batch",
        created_at=_TS,
        updated_at="2020-01-01T00:00:01Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/submission-1.json",
        summary_counts={"submitted": 1},
        backend_metadata={"cluster": "alpha"},
    )


def _metadata(
    operation_kind: AuthorityProtocolOperationKind,
) -> AuthorityProtocolMetadata:
    return AuthorityProtocolMetadata(
        request_id="request-1",
        operation_kind=operation_kind,
        service_generation="generation-1",
        workspace_id="workspace-1",
        idempotency_key="operation-1",
    )


def test_protocol_readiness_reports_version_schema_and_capabilities() -> None:
    capabilities = BackendCapabilitySet(
        backend_name="service",
        records=(
            BackendCapabilityRecord(
                capability=BackendCapability.SERVICE_ENDPOINT,
                scope=CapabilityScope.PER_RUN,
            ),
        ),
    )
    diagnostic = StoreDiagnostic(
        code="authority.readiness",
        message="ready",
        severity=DiagnosticSeverity.INFO,
        detail={"endpoint": "tcp://127.0.0.1:12345"},
    )
    readiness = AuthorityProtocolReadiness(
        capabilities=capabilities,
        service_generation="generation-1",
        workspace_id="workspace-1",
        diagnostics=(diagnostic,),
    )

    payload = readiness.to_dict()

    assert payload["protocol_version"] == AUTHORITY_PROTOCOL_VERSION
    assert payload["schema_version"] == AUTHORITY_SCHEMA_VERSION
    assert payload["readiness"] == "ready"
    assert payload["ready"] is True
    assert payload["capabilities"] == capabilities.to_dict()
    assert AuthorityProtocolReadiness.from_dict(payload) == readiness
    assert protocol_versions_compatible(readiness.version)


def test_protocol_readiness_marks_incompatible_versions_not_ready() -> None:
    incompatible = AuthorityProtocolVersion(
        protocol_version=AUTHORITY_PROTOCOL_VERSION + 1,
        min_supported_protocol_version=AUTHORITY_PROTOCOL_VERSION + 1,
    )
    readiness = AuthorityProtocolReadiness(
        version=incompatible,
        readiness=AuthorityReadinessState.READY,
    )

    assert incompatible.supported is False
    assert readiness.ready is False
    assert protocol_versions_compatible(incompatible) is False

    payload = readiness.to_dict()
    with pytest.raises(AuthorityProtocolError, match="ready does not match"):
        AuthorityProtocolReadiness.from_dict({**payload, "ready": True})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"protocol_version": AUTHORITY_PROTOCOL_VERSION + 1}, "protocol_version"),
        ({"schema_version": AUTHORITY_SCHEMA_VERSION + 1}, "schema_version"),
    ],
)
def test_protocol_readiness_rejects_conflicting_version_aliases(
    override: dict[str, object],
    message: str,
) -> None:
    payload = AuthorityProtocolReadiness().to_dict()

    with pytest.raises(AuthorityProtocolError, match=message):
        AuthorityProtocolReadiness.from_dict({**payload, **override})


def test_protocol_request_round_trips_identifiers_revision_and_body() -> None:
    metadata = _metadata(AuthorityProtocolOperationKind.STAGE_ATTEMPT)
    request = AuthorityProtocolRequest(
        metadata=metadata,
        run_uri="file:///runs/r1",
        stage_name="build",
        lease_id="lease-1",
        fencing_token="fence-1",
        owner_id="worker-1",
        expected_revision=_revision(),
        body={"status": "RUNNING", "reason": {"code": "started"}},
    )

    payload = request.to_dict()
    metadata_payload = cast("dict[str, object]", payload["metadata"])

    assert metadata_payload["operation_kind"] == "stage_attempt"
    assert payload["lease_id"] == "lease-1"
    assert payload["fencing_token"] == "fence-1"
    assert payload["expected_revision"] == _revision().to_dict()
    assert payload["body"] == {"status": "RUNNING", "reason": {"code": "started"}}
    assert AuthorityProtocolRequest.from_dict(payload) == request


def test_protocol_models_reject_unknown_fields_and_non_plain_body() -> None:
    metadata = _metadata(AuthorityProtocolOperationKind.RUN_LIFECYCLE)

    with pytest.raises(AuthorityProtocolError, match="unknown field"):
        AuthorityProtocolRequest.from_dict(
            {
                "metadata": metadata.to_dict(),
                "body": {},
                "future_field": True,
            }
        )

    with pytest.raises(AuthorityProtocolError, match="body must contain plain data"):
        AuthorityProtocolRequest(
            metadata=metadata,
            body=cast("dict[str, PlainData]", {"bad": object()}),
        )


def test_protocol_result_carries_authority_read_models() -> None:
    revision = _revision()
    run_uri = "file:///runs/r1"
    reason = LifecycleReason(code="started", message="worker allocated")
    attempt = StageAttempt(
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        attempt_id="build-1",
        status=StageStatus.RUNNING,
        revision=revision,
        created_at=_TS,
        owner="worker-1",
        reason=reason,
    )
    lease = LeaseRecord(
        lease_id="lease-1",
        kind=LeaseKind.STAGE,
        owner_id="worker-1",
        fencing_token="fence-1",
        acquired_at=_TS,
        renewed_at=_TS,
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
        run_uri=run_uri,
        stage_name="build",
        attempt_id="build-1",
    )
    materialized = MaterializedRef(
        kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
        uri="file:///runs/r1/artifacts/build/out.json",
        exists=True,
    )
    output_commit = OutputCommitRecord(
        commit_id="commit-1",
        run_uri=run_uri,
        stage_name="build",
        attempt_id="build-1",
        committed_at="2020-01-01T00:00:02Z",
        revision=revision,
        output_names=("out",),
        materialized_refs=(materialized,),
    )
    artifact_fact = ArtifactFactRecord(
        artifact_name="out",
        artifact=ArtifactRef(
            artifact_id="build/out",
            uri="file:///runs/r1/artifacts/build/out.json",
            artifact_type="json",
        ),
        commit_id="commit-1",
        revision=revision,
    )
    cleanup = CleanupCandidate(
        candidate_id="cleanup-1",
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri="file:///runs/r1/staging/build/out.tmp",
        reason=LifecycleReason(code="committed"),
        recorded_at="2020-01-01T00:00:03Z",
        revision=revision,
    )
    recovery = RecoveryRecord(
        recovery_id="recovery-1",
        kind=RecoveryKind.EXPIRED_LEASE,
        reason=LifecycleReason(code="lease_expired"),
        detected_at="2020-01-01T00:00:04Z",
        revision=revision,
        run_uri=run_uri,
        stage_name="build",
        attempt_id="build-1",
    )
    submitted = _submitted_operation(run_uri)
    snapshot = AuthoritativeRunSnapshot(
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
        stages=(
            StageLifecycleSnapshot(
                stage_name="build",
                status=StageStatus.RUNNING,
                revision=revision,
                attempts=(attempt,),
                active_lease=lease,
                latest_commit=output_commit,
                artifact_facts=(artifact_fact,),
            ),
        ),
        submitted_operations=(submitted,),
        cleanup_candidates=(cleanup,),
        materialized_refs=(materialized,),
    )
    result = AuthorityProtocolResult(
        revision=revision,
        service_generation="generation-1",
        lease=lease,
        snapshot=snapshot,
        stage_attempt=attempt,
        output_commit=output_commit,
        submitted_operation=submitted,
        artifact_facts=(artifact_fact,),
        submitted_operations=(submitted,),
        cleanup_candidates=(cleanup,),
        recovery_records=(recovery,),
        body={"notes": ["accepted"]},
    )

    payload = result.to_dict()

    assert payload["revision"] == revision.to_dict()
    assert payload["lease_id"] == lease.lease_id
    assert payload["fencing_token"] == lease.fencing_token
    assert payload["lease"] == lease.to_dict()
    assert payload["snapshot"] == snapshot.to_dict()
    assert payload["stage_attempt"] == attempt.to_dict()
    assert payload["output_commit"] == output_commit.to_dict()
    assert payload["submitted_operation"] == submitted.to_dict()
    assert payload["submitted_operations"] == [submitted.to_dict()]
    assert payload["artifact_facts"] == [artifact_fact.to_dict()]
    assert payload["cleanup_candidates"] == [cleanup.to_dict()]
    assert payload["recovery_records"] == [recovery.to_dict()]
    assert AuthorityProtocolResult.from_dict(payload) == result

    with pytest.raises(AuthorityProtocolError, match="fencing_token must match"):
        AuthorityProtocolResult(lease=lease, fencing_token="different-fence")


def test_protocol_result_carries_workspace_coordination_models() -> None:
    revision = _revision()
    workspace = WorkspaceIdentity(
        workspace_id="workspace-1",
        root_uri="file:///workspace",
        metadata={"owner": "team-a"},
    )
    sweep = SweepIdentity(
        sweep_id="sweep-1",
        workspace_id="workspace-1",
        metadata={"strategy": "grid"},
    )
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.PENDING,
        revision=revision,
        metadata={"candidate": 1},
    )
    lease = LeaseRecord(
        lease_id="trial-lease-1",
        kind=LeaseKind.TRIAL,
        owner_id="worker-1",
        fencing_token="trial-fence-1",
        acquired_at=_TS,
        renewed_at=_TS,
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
    )
    trial_lease = TrialLeaseRecord(
        workspace_id="workspace-1",
        sweep_id="sweep-1",
        trial_id="trial-1",
        lease=lease,
    )
    resource_lease = ResourceLeaseRecord(
        workspace_id="workspace-1",
        resource_key="gpu",
        lease=LeaseRecord(
            lease_id="resource-lease-1",
            kind=LeaseKind.RESOURCE,
            owner_id="worker-2",
            fencing_token="resource-fence-1",
            acquired_at=_TS,
            renewed_at=_TS,
            expires_at="2020-01-01T00:01:00Z",
            revision=revision,
        ),
        amount=2,
    )
    counter = ConcurrencyCounter(
        counter_name="active_trials",
        value=1,
        limit=4,
        revision=revision,
    )
    recovery = CoordinationRecoveryRecord(
        workspace_id="workspace-1",
        sweep_id="sweep-1",
        trial_id="trial-1",
        recovery=RecoveryRecord(
            recovery_id="coordination-recovery-1",
            kind=RecoveryKind.EXPIRED_LEASE,
            reason=LifecycleReason(code="lease_expired"),
            detected_at="2020-01-01T00:00:10Z",
            revision=revision,
        ),
    )
    result = AuthorityProtocolResult(
        revision=revision,
        workspace=workspace,
        sweep=sweep,
        trial=trial,
        trial_lease=trial_lease,
        resource_lease=resource_lease,
        lease=lease,
        counter=counter,
        trials=(trial,),
        coordination_recovery_records=(recovery,),
    )

    payload = result.to_dict()

    assert payload["workspace"] == workspace.to_dict()
    assert payload["sweep"] == sweep.to_dict()
    assert payload["trial"] == trial.to_dict()
    assert payload["trial_lease"] == trial_lease.to_dict()
    assert payload["resource_lease"] == resource_lease.to_dict()
    assert payload["counter"] == counter.to_dict()
    assert payload["trials"] == [trial.to_dict()]
    assert payload["coordination_recovery_records"] == [recovery.to_dict()]
    assert AuthorityProtocolResult.from_dict(payload) == result


def test_protocol_response_enforces_accepted_or_rejected_payloads() -> None:
    metadata = _metadata(AuthorityProtocolOperationKind.OUTPUT_COMMIT)
    result = AuthorityProtocolResult(revision=_revision())
    accepted = accepted_authority_response(metadata, result)

    assert AuthorityProtocolResponse.from_dict(accepted.to_dict()) == accepted

    rejection = AuthorityProtocolRejection(
        category=AuthorityProtocolErrorCategory.STALE_REVISION,
        code="stale_revision",
        message="request revision is stale",
        detail={"expected": "rev-2", "observed": "rev-1"},
        diagnostics=(
            StoreDiagnostic(
                code="authority.stale_revision",
                message="refresh before retrying",
            ),
        ),
        resolver_failure_kind=AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
        resolver_diagnostics=(
            AuthorityResolverDiagnostic(
                code="authority_resolution.incompatible_version",
                message="authority service protocol is incompatible",
            ),
        ),
    )
    rejected = rejected_authority_response(metadata, rejection)

    assert AuthorityProtocolResponse.from_dict(rejected.to_dict()) == rejected
    assert rejected.to_dict()["accepted"] is False
    assert rejected.to_dict()["rejection"] == rejection.to_dict()

    with pytest.raises(AuthorityProtocolError, match="accepted responses require"):
        AuthorityProtocolResponse(metadata=metadata, accepted=True)

    with pytest.raises(AuthorityProtocolError, match="rejected responses require"):
        AuthorityProtocolResponse(metadata=metadata, accepted=False, result=result)
