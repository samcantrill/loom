"""In-process integration tests for the authority mutation API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from loom.artifacts import ArtifactRef
from loom.authority.app import create_authority_app
from loom.authority._repository import initialize_authority_repository
from loom.authority.services import repository_authority_services
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityClient,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolResponse,
)
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    SubmittedOperationState,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.integration

RUN_URI = "file:///runs/mutation-api-r1"


def _client(tmp_path) -> AuthorityClient:
    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    app_client = TestClient(
        create_authority_app(
            services=repository_authority_services(
                repository,
                workspace_id="workspace-a",
            )
        )
    )

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        path = urlsplit(url).path
        response = app_client.post(path, json=payload)
        assert response.status_code == 200
        parsed = response.json()
        assert isinstance(parsed, Mapping)
        return parsed

    return AuthorityClient("http://authority.test", transport=transport)


def test_authority_client_mutates_repository_through_fastapi_routes(tmp_path) -> None:
    client = _client(tmp_path)
    admitted = client.admit_run(
        RUN_URI,
        request_id="admit-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert admitted.accepted is True
    assert admitted.result is not None
    assert admitted.result.revision is not None

    running = client.transition_run(
        RUN_URI,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
        expected_revision=admitted.result.revision,
        request_id="run-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert running.accepted is True
    assert running.result is not None
    assert running.result.revision is not None

    allocation = client.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
        expected_revision=running.result.revision,
        request_id="attempt-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert allocation.accepted is True
    assert allocation.result is not None
    assert allocation.result.stage_attempt is not None
    assert allocation.result.lease is not None

    commit = client.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.result.stage_attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.result.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=f"{RUN_URI}/artifacts/build/out.json",
                artifact_type="json",
                metadata={"size": 123},
            )
        },
        expected_revision=allocation.result.stage_attempt.revision,
        request_id="commit-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert commit.accepted is True
    assert commit.result is not None
    assert commit.result.output_commit is not None
    assert commit.result.artifact_facts[0].artifact.artifact_id == "build/out"

    snapshot = client.open_run(
        RUN_URI,
        request_id="snapshot-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert snapshot.accepted is True
    assert snapshot.result is not None
    assert snapshot.result.snapshot is not None
    assert snapshot.result.snapshot.status is RunStatus.RUNNING
    assert snapshot.result.snapshot.stages[0].status is StageStatus.SUCCEEDED


def test_mutation_api_rejects_stale_generation_with_protocol_response(
    tmp_path,
) -> None:
    client = _client(tmp_path)
    admitted = client.admit_run(
        RUN_URI,
        request_id="admit-1",
        service_generation="generation-1",
    )
    assert admitted.result is not None
    allocation = client.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
        expected_revision=admitted.result.revision,
        request_id="attempt-1",
        service_generation="generation-1",
    )
    assert allocation.result is not None
    assert allocation.result.stage_attempt is not None
    assert allocation.result.lease is not None

    rejected = client.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.result.stage_attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.result.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=f"{RUN_URI}/artifacts/build/out.json",
                artifact_type="json",
            )
        },
        expected_revision=allocation.result.stage_attempt.revision,
        request_id="commit-1",
        service_generation="generation-old",
    )

    assert rejected.accepted is False
    assert rejected.rejection is not None
    assert rejected.rejection.category is AuthorityProtocolErrorCategory.STALE_GENERATION
    assert rejected.rejection.code == "authority_repository_stale_generation"


def test_mutation_api_maps_conflict_and_stale_fencing_rejections(tmp_path) -> None:
    client = _client(tmp_path)
    admitted = client.admit_run(
        RUN_URI,
        request_id="admit-1",
        service_generation="generation-1",
    )
    duplicate = client.admit_run(
        RUN_URI,
        request_id="admit-2",
        service_generation="generation-1",
    )
    assert duplicate.accepted is False
    assert duplicate.rejection is not None
    assert duplicate.rejection.category is AuthorityProtocolErrorCategory.CONFLICT

    assert admitted.result is not None
    allocation = client.allocate_stage_attempt(
        RUN_URI,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
        expected_revision=admitted.result.revision,
        request_id="attempt-1",
        service_generation="generation-1",
    )
    assert allocation.result is not None
    assert allocation.result.stage_attempt is not None

    rejected = client.record_output_commit(
        RUN_URI,
        "build",
        attempt_id=allocation.result.stage_attempt.attempt_id,
        owner_id="worker-1",
        fencing_token="wrong-fence",
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=f"{RUN_URI}/artifacts/build/out.json",
                artifact_type="json",
            )
        },
        expected_revision=allocation.result.stage_attempt.revision,
        request_id="commit-1",
        service_generation="generation-1",
    )

    assert rejected.accepted is False
    assert rejected.rejection is not None
    assert rejected.rejection.category is AuthorityProtocolErrorCategory.STALE_FENCING


def test_mutation_api_handles_leases_and_submitted_operations(tmp_path) -> None:
    client = _client(tmp_path)
    admitted = client.admit_run(
        RUN_URI,
        request_id="admit-1",
        service_generation="generation-1",
    )
    assert admitted.result is not None

    lease = client.acquire_controller_lease(
        RUN_URI,
        owner_id="runner",
        lease_ttl_seconds=60,
        expected_revision=admitted.result.revision,
        request_id="lease-1",
        service_generation="generation-1",
    )
    assert lease.accepted is True
    assert lease.result is not None
    assert lease.result.lease is not None

    renewed = client.renew_controller_lease(
        RUN_URI,
        lease_id=lease.result.lease.lease_id,
        owner_id="runner",
        fencing_token=lease.result.lease.fencing_token,
        lease_ttl_seconds=60,
        expected_revision=lease.result.lease.revision,
        request_id="lease-renew-1",
        service_generation="generation-1",
    )
    assert renewed.accepted is True

    record = SubmittedOperationRecord(
        run_uri=RUN_URI,
        submission_id="sub-1",
        backend="local",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1/manifest.json",
    )
    written = client.write_submitted_operation(
        RUN_URI,
        record,
        request_id="submitted-write-1",
        service_generation="generation-1",
    )
    assert written.accepted is True

    read = client.read_submitted_operation(
        RUN_URI,
        "sub-1",
        request_id="submitted-read-1",
        service_generation="generation-1",
    )
    assert read.accepted is True
    assert read.result is not None
    assert read.result.submitted_operation == record

    listed = client.list_submitted_operations(
        RUN_URI,
        request_id="submitted-list-1",
        service_generation="generation-1",
    )
    assert listed.accepted is True
    assert listed.result is not None
    assert listed.result.submitted_operations == (record,)


def test_route_level_invalid_request_returns_protocol_rejection(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    app_client = TestClient(
        create_authority_app(services=repository_authority_services(repository))
    )

    response = app_client.post(
        "/v1/authority/runs/admit",
        json={
            "metadata": {
                "request_id": "bad-request",
                "operation_kind": "run_lifecycle",
            },
        },
    )

    payload = response.json()
    protocol_response = AuthorityProtocolResponse.from_dict(payload)
    assert protocol_response.accepted is False
    assert protocol_response.rejection is not None
    assert protocol_response.rejection.category is AuthorityProtocolErrorCategory.VALIDATION
    assert protocol_response.metadata.request_id == "bad-request"
