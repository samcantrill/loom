"""Unit tests for v9 authority contract models."""

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AUTHORITY_SCHEMA_VERSION,
    ArtifactFactRecord,
    AuthorityModelError,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    CleanupCandidate,
    CleanupCandidateKind,
    LeaseKind,
    LeaseRecord,
    LifecycleReason,
    MaterializedRef,
    MaterializedRefKind,
    OutputCommitRecord,
    ReadModelWarning,
    ReadModelWarningCode,
    RecoveryKind,
    RecoveryRecord,
    StageAttempt,
    StaticOutcomeKind,
    StaticOutcomeRecord,
    StoreDiagnostic,
    UnsupportedCapabilityCode,
    check_authority_schema_version,
)


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


def test_authority_schema_policy_loudly_rejects_old_and_new_active_state() -> None:
    current = check_authority_schema_version(
        {"schema_version": AUTHORITY_SCHEMA_VERSION}
    )
    older = check_authority_schema_version({"schema_version": 1}, current_version=2)
    newer = check_authority_schema_version({"schema_version": 2})

    assert current.supported
    assert older.failure is not None
    assert older.failure.kind.value == "unsupported_older"
    assert newer.failure is not None
    assert newer.failure.kind.value == "unsupported_newer"


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

    assert attempt.to_dict()["attempt_id"] == "build-1"
    assert lease.to_dict()["fencing_token"] == "fence-1"
    assert commit.to_dict()["materialized_refs"] == [materialized.to_dict()]
    assert fact.to_dict()["artifact_name"] == "out"
    assert cleanup.to_dict()["kind"] == "staged_payload"
    assert recovery.to_dict()["kind"] == "expired_lease"
    assert outcome.to_dict()["outcome"] == "not_selected"
    assert warning.to_dict()["code"] == "missing_materialized_ref"


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
