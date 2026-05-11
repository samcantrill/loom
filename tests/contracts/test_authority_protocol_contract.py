"""Contract coverage for authority protocol value-model shapes."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AUTHORITY_PROTOCOL_VERSION,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRejection,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    BackendRevision,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState

pytestmark = pytest.mark.contract


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
        "recovery_scan",
        "cleanup_candidates",
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
        owner_id="worker-1",
        expected_revision=BackendRevision(
            sequence=7,
            token="rev-7",
            created_at="2020-01-01T00:00:00Z",
        ),
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
        "lease_id": None,
        "owner_id": "worker-1",
        "expected_revision": {
            "sequence": 7,
            "token": "rev-7",
            "created_at": "2020-01-01T00:00:00Z",
        },
        "body": {"status": "RUNNING"},
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
            "lease": None,
            "snapshot": None,
            "stage_attempt": None,
            "output_commit": None,
            "submitted_operation": submitted.to_dict(),
            "artifact_facts": [],
            "submitted_operations": [submitted.to_dict()],
            "cleanup_candidates": [],
            "recovery_records": [],
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
