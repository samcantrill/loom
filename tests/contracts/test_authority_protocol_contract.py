"""Contract coverage for authority protocol value-model shapes."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AUTHORITY_PROTOCOL_VERSION,
    AUTHORITY_SCHEMA_VERSION,
    AuthoritativeRunSnapshot,
    AuthorityProtocolReadiness,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRejection,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    AuthorityReadinessState,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    LeaseKind,
    LeaseRecord,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState

pytestmark = pytest.mark.contract


def _revision(sequence: int = 1) -> BackendRevision:
    return BackendRevision(
        sequence=sequence,
        token=f"rev-{sequence}",
        created_at="2020-01-01T00:00:00Z",
    )


def _submitted_operation() -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri="file:///runs/r1",
        submission_id="submission-1",
        backend="slurm",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/submission-1.json",
        summary_counts={"submitted": 1},
    )


def test_authority_protocol_contract_exposes_stable_vocabulary() -> None:
    assert {kind.value for kind in AuthorityProtocolOperationKind} == {
        "readiness",
        "capabilities",
        "run_lifecycle",
        "run_snapshot",
        "stage_lifecycle",
        "stage_attempt",
        "submitted_operation",
        "output_commit",
        "artifact_facts",
        "lease",
        "workspace_coordination",
        "recovery_scan",
        "cleanup_candidates",
        "cleanup_reports",
        "cleanup_results",
        "offline_import",
    }
    assert {category.value for category in AuthorityProtocolErrorCategory} == {
        "resolver",
        "validation",
        "conflict",
        "stale_generation",
        "stale_revision",
        "stale_fencing",
        "unsupported_capability",
        "unavailable_service",
        "internal_error",
    }


def test_authority_protocol_readiness_contract_shape() -> None:
    capabilities = BackendCapabilitySet(
        backend_name="authority-service",
        records=(
            BackendCapabilityRecord(
                capability=BackendCapability.SERVICE_ENDPOINT,
                scope=CapabilityScope.PER_RUN,
            ),
        ),
    )
    readiness = AuthorityProtocolReadiness(
        readiness=AuthorityReadinessState.READY,
        capabilities=capabilities,
        service_generation="generation-1",
        workspace_id="workspace-1",
    )

    assert readiness.to_dict() == {
        "protocol_version": AUTHORITY_PROTOCOL_VERSION,
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "service_generation": "generation-1",
        "workspace_id": "workspace-1",
        "readiness": "ready",
        "ready": True,
        "version": {
            "protocol_version": AUTHORITY_PROTOCOL_VERSION,
            "min_supported_protocol_version": AUTHORITY_PROTOCOL_VERSION,
            "schema_version": AUTHORITY_SCHEMA_VERSION,
            "schema_check": {
                "current_version": AUTHORITY_SCHEMA_VERSION,
                "found_version": AUTHORITY_SCHEMA_VERSION,
                "supported": True,
                "failure": None,
            },
            "supported": True,
        },
        "capabilities": capabilities.to_dict(),
        "diagnostics": [],
    }


def test_authority_protocol_request_contract_shape() -> None:
    metadata = AuthorityProtocolMetadata(
        request_id="request-1",
        operation_kind=AuthorityProtocolOperationKind.STAGE_ATTEMPT,
        service_generation="generation-1",
        workspace_id="workspace-1",
        idempotency_key="stage-build-1",
    )
    request = AuthorityProtocolRequest(
        metadata=metadata,
        run_uri="file:///runs/r1",
        stage_name="build",
        lease_id="lease-1",
        fencing_token="fence-1",
        owner_id="worker-1",
        expected_revision=_revision(7),
        body={"status": "RUNNING"},
    )

    assert request.to_dict() == {
        "metadata": {
            "request_id": "request-1",
            "operation_kind": "stage_attempt",
            "protocol_version": AUTHORITY_PROTOCOL_VERSION,
            "service_generation": "generation-1",
            "workspace_id": "workspace-1",
            "idempotency_key": "stage-build-1",
        },
        "run_uri": "file:///runs/r1",
        "stage_name": "build",
        "submission_id": None,
        "lease_id": "lease-1",
        "fencing_token": "fence-1",
        "owner_id": "worker-1",
        "expected_revision": {
            "sequence": 7,
            "token": "rev-7",
            "created_at": "2020-01-01T00:00:00Z",
        },
        "body": {"status": "RUNNING"},
    }


def test_authority_protocol_fenced_mutation_ack_contract_shape() -> None:
    metadata = AuthorityProtocolMetadata(
        request_id="request-1",
        operation_kind=AuthorityProtocolOperationKind.STAGE_ATTEMPT,
        service_generation="generation-1",
    )
    revision = _revision(8)
    lease = LeaseRecord(
        lease_id="lease-1",
        kind=LeaseKind.STAGE,
        owner_id="worker-1",
        fencing_token="fence-1",
        acquired_at="2020-01-01T00:00:00Z",
        renewed_at="2020-01-01T00:00:01Z",
        expires_at="2020-01-01T00:01:00Z",
        revision=revision,
        run_uri="file:///runs/r1",
        stage_name="build",
        attempt_id="build-1",
    )
    response = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=True,
        result=AuthorityProtocolResult(
            revision=revision,
            service_generation="generation-1",
            lease=lease,
        ),
    )

    assert response.to_dict() == {
        "metadata": {
            "request_id": "request-1",
            "operation_kind": "stage_attempt",
            "protocol_version": AUTHORITY_PROTOCOL_VERSION,
            "service_generation": "generation-1",
            "workspace_id": None,
            "idempotency_key": None,
        },
        "accepted": True,
        "result": {
            "revision": revision.to_dict(),
            "service_generation": "generation-1",
            "lease_id": "lease-1",
            "fencing_token": "fence-1",
            "lease": lease.to_dict(),
            "snapshot": None,
            "stage_attempt": None,
            "output_commit": None,
            "submitted_operation": None,
            "workspace": None,
            "sweep": None,
            "trial": None,
            "trial_lease": None,
            "resource_lease": None,
            "counter": None,
            "artifact_facts": [],
            "submitted_operations": [],
            "trials": [],
            "cleanup_candidates": [],
            "cleanup_reports": [],
            "cleanup_results": [],
            "recovery_records": [],
            "coordination_recovery_records": [],
            "body": {},
        },
        "rejection": None,
    }


def test_authority_protocol_snapshot_response_contract_shape() -> None:
    metadata = AuthorityProtocolMetadata(
        request_id="request-2",
        operation_kind=AuthorityProtocolOperationKind.RUN_SNAPSHOT,
    )
    revision = _revision(9)
    snapshot = AuthoritativeRunSnapshot(
        run_uri="file:///runs/r1",
        status=RunStatus.RUNNING,
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
    )
    response = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=True,
        result=AuthorityProtocolResult(revision=revision, snapshot=snapshot),
    )

    assert response.to_dict() == {
        "metadata": metadata.to_dict(),
        "accepted": True,
        "result": {
            "revision": revision.to_dict(),
            "service_generation": None,
            "lease_id": None,
            "fencing_token": None,
            "lease": None,
            "snapshot": snapshot.to_dict(),
            "stage_attempt": None,
            "output_commit": None,
            "submitted_operation": None,
            "workspace": None,
            "sweep": None,
            "trial": None,
            "trial_lease": None,
            "resource_lease": None,
            "counter": None,
            "artifact_facts": [],
            "submitted_operations": [],
            "trials": [],
            "cleanup_candidates": [],
            "cleanup_reports": [],
            "cleanup_results": [],
            "recovery_records": [],
            "coordination_recovery_records": [],
            "body": {},
        },
        "rejection": None,
    }


def test_authority_protocol_response_contract_shapes() -> None:
    metadata = AuthorityProtocolMetadata(
        request_id="request-1",
        operation_kind=AuthorityProtocolOperationKind.SUBMITTED_OPERATION,
    )
    submitted = _submitted_operation()
    result = AuthorityProtocolResult(
        submitted_operation=submitted,
        submitted_operations=(submitted,),
    )
    accepted = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=True,
        result=result,
    )

    assert accepted.to_dict() == {
        "metadata": {
            "request_id": "request-1",
            "operation_kind": "submitted_operation",
            "protocol_version": AUTHORITY_PROTOCOL_VERSION,
            "service_generation": None,
            "workspace_id": None,
            "idempotency_key": None,
        },
        "accepted": True,
        "result": {
            "revision": None,
            "service_generation": None,
            "lease_id": None,
            "fencing_token": None,
            "lease": None,
            "snapshot": None,
            "stage_attempt": None,
            "output_commit": None,
            "submitted_operation": submitted.to_dict(),
            "workspace": None,
            "sweep": None,
            "trial": None,
            "trial_lease": None,
            "resource_lease": None,
            "counter": None,
            "artifact_facts": [],
            "submitted_operations": [submitted.to_dict()],
            "trials": [],
            "cleanup_candidates": [],
            "cleanup_reports": [],
            "cleanup_results": [],
            "recovery_records": [],
            "coordination_recovery_records": [],
            "body": {},
        },
        "rejection": None,
    }

    rejection = AuthorityProtocolRejection(
        category=AuthorityProtocolErrorCategory.RESOLVER,
        code="missing_authority",
        message="no authority service reference was available",
        detail={"mode": "online_mutation"},
    )
    rejected = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=False,
        rejection=rejection,
    )

    assert rejected.to_dict() == {
        "metadata": metadata.to_dict(),
        "accepted": False,
        "result": None,
        "rejection": {
            "category": "resolver",
            "code": "missing_authority",
            "message": "no authority service reference was available",
            "detail": {"mode": "online_mutation"},
            "diagnostics": [],
            "resolver_failure_kind": None,
            "resolver_diagnostics": [],
        },
    }


def test_authority_protocol_rejection_contract_shapes() -> None:
    metadata = AuthorityProtocolMetadata(
        request_id="request-3",
        operation_kind=AuthorityProtocolOperationKind.OUTPUT_COMMIT,
    )
    stale_generation = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=False,
        rejection=AuthorityProtocolRejection(
            category=AuthorityProtocolErrorCategory.STALE_GENERATION,
            code="stale_generation",
            message="service generation changed before mutation",
            detail={"expected": "generation-1", "observed": "generation-2"},
        ),
    )
    unsupported = AuthorityProtocolResponse(
        metadata=metadata,
        accepted=False,
        rejection=AuthorityProtocolRejection(
            category=AuthorityProtocolErrorCategory.UNSUPPORTED_CAPABILITY,
            code="unsupported_capability",
            message="authority service does not support fenced output commits",
            detail={"capability": "fencing_tokens"},
        ),
    )

    assert stale_generation.to_dict()["rejection"] == {
        "category": "stale_generation",
        "code": "stale_generation",
        "message": "service generation changed before mutation",
        "detail": {"expected": "generation-1", "observed": "generation-2"},
        "diagnostics": [],
        "resolver_failure_kind": None,
        "resolver_diagnostics": [],
    }
    assert unsupported.to_dict()["rejection"] == {
        "category": "unsupported_capability",
        "code": "unsupported_capability",
        "message": "authority service does not support fenced output commits",
        "detail": {"capability": "fencing_tokens"},
        "diagnostics": [],
        "resolver_failure_kind": None,
        "resolver_diagnostics": [],
    }
