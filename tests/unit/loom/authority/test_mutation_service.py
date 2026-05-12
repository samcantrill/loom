"""Unit tests for server-side authority mutation dispatch."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.authority._repository import initialize_authority_repository
from loom.authority.mutation_service import (
    AuthorityMutationOperation,
    AuthorityMutationService,
)
from loom.pipeline.stores import (
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
    BackendRevision,
    SweepIdentity,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


def test_mutation_service_dispatches_workspace_coordination_operations(
    tmp_path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    service = AuthorityMutationService(repository)
    workspace = WorkspaceIdentity(workspace_id="workspace-1")
    sweep = SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1")
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=1, token="trial-rev"),
    )

    created_workspace = service.handle(
        AuthorityMutationOperation.CREATE_WORKSPACE,
        _request("create-workspace", {"workspace": workspace.to_dict()}),
    )
    assert created_workspace.accepted is True
    assert created_workspace.result is not None
    assert created_workspace.result.workspace == workspace

    assert service.handle(
        AuthorityMutationOperation.CREATE_SWEEP,
        _request("create-sweep", {"sweep": sweep.to_dict()}),
    ).accepted
    recorded = service.handle(
        AuthorityMutationOperation.RECORD_TRIAL,
        _request("record-trial", {"trial": trial.to_dict()}),
    )
    assert recorded.accepted is True

    listed = service.handle(
        AuthorityMutationOperation.LIST_TRIALS,
        _request("list-trials", {"sweep_id": "sweep-1"}),
    )
    assert listed.accepted is True
    assert listed.result is not None
    assert listed.result.trials == (trial,)


def test_mutation_service_reports_resource_coordination_as_unsupported(
    tmp_path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    service = AuthorityMutationService(repository)

    response = service.handle(
        AuthorityMutationOperation.ACQUIRE_RESOURCE_LEASE,
        AuthorityProtocolRequest(
            metadata=AuthorityProtocolMetadata(
                request_id="resource-lease-1",
                operation_kind=AuthorityProtocolOperationKind.WORKSPACE_COORDINATION,
            ),
            owner_id="worker-1",
            body={
                "workspace_id": "workspace-1",
                "resource_key": "gpu",
                "amount": 1,
                "lease_ttl_seconds": 30,
            },
        ).to_dict(),
    )

    assert response.accepted is False
    assert response.rejection is not None
    assert response.rejection.category is (
        AuthorityProtocolErrorCategory.UNSUPPORTED_CAPABILITY
    )
    assert response.rejection.code == "authority_coordination_unsupported_resource"
    assert response.rejection.detail["operation"] == "acquire_resource_lease"


def _request(
    request_id: str,
    body: Mapping[str, PlainData],
) -> Mapping[str, object]:
    return AuthorityProtocolRequest(
        metadata=AuthorityProtocolMetadata(
            request_id=request_id,
            operation_kind=AuthorityProtocolOperationKind.WORKSPACE_COORDINATION,
            service_generation="generation-1",
        ),
        body=body,
    ).to_dict()
