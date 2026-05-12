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
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
    BackendRevision,
    LeaseKind,
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


def test_mutation_service_dispatches_resource_coordination_operations(
    tmp_path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    service = AuthorityMutationService(repository)
    workspace = WorkspaceIdentity(workspace_id="workspace-1")

    assert service.handle(
        AuthorityMutationOperation.CREATE_WORKSPACE,
        _request("create-workspace", {"workspace": workspace.to_dict()}),
    ).accepted

    limit = service.handle(
        AuthorityMutationOperation.SET_RESOURCE_LIMIT,
        _request(
            "resource-limit-1",
            {"workspace_id": "workspace-1", "resource_key": "gpu", "limit": 2},
        ),
    )
    assert limit.accepted is True
    assert limit.result is not None
    assert limit.result.counter is not None
    assert limit.result.counter.counter_name == "resource:gpu"
    assert limit.result.counter.limit == 2

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

    assert response.accepted is True
    assert response.result is not None
    assert response.result.resource_lease is not None
    assert response.result.resource_lease.workspace_id == "workspace-1"
    assert response.result.resource_lease.resource_key == "gpu"
    assert response.result.resource_lease.amount == 1
    assert response.result.resource_lease.lease.kind is LeaseKind.RESOURCE
    assert response.result.lease == response.result.resource_lease.lease


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
