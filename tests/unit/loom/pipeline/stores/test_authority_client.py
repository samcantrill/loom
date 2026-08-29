"""Unit tests for the authority HTTP client adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup import (
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.pipeline.stores import (
    AUTHORITY_MUTATION_RUN_ADMIT_PATH,
    AuthorityClient,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
    AuthorityProtocolResult,
    BackendRevision,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
    accepted_authority_response,
)
from loom.pipeline.stores.authority_client import (
    AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH,
    AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH,
    AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH,
    AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH,
    AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH,
    AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH,
    AUTHORITY_MUTATION_CLEANUP_REPORT_APPEND_PATH,
    AUTHORITY_MUTATION_CLEANUP_REPORT_LIST_PATH,
    AUTHORITY_MUTATION_LIST_OUTPUT_COMMITS_PATH,
    AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH,
    AUTHORITY_MUTATION_RUN_RECOVERY_SCAN_PATH,
    AUTHORITY_MUTATION_STAGE_LEASE_RENEW_PATH,
    AUTHORITY_MUTATION_SUBMITTED_WRITE_PATH,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


def test_authority_client_posts_protocol_payload_and_parses_response() -> None:
    captured: dict[str, object] = {}
    metadata = AuthorityProtocolMetadata(
        request_id="request-1",
        operation_kind=AuthorityProtocolOperationKind.RUN_LIFECYCLE,
    )

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    client = AuthorityClient(
        "http://authority.example/",
        timeout_seconds=1.5,
        transport=transport,
    )

    response = client.send(
        AUTHORITY_MUTATION_RUN_ADMIT_PATH,
        AuthorityProtocolRequest(metadata=metadata, run_uri="file:///runs/r1"),
    )

    assert response.accepted is True
    assert captured["url"] == "http://authority.example/v1/authority/runs/admit"
    assert captured["timeout_seconds"] == 1.5
    payload = cast(Mapping[str, PlainData], captured["payload"])
    assert payload["run_uri"] == "file:///runs/r1"


def test_authority_client_maps_timeout_to_protocol_rejection() -> None:
    def transport(
        _url: str,
        _payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        raise TimeoutError("slow authority")

    client = AuthorityClient("http://authority.example", transport=transport)

    response = client.admit_run(
        "file:///runs/r1",
        request_id="request-1",
        service_generation="generation-1",
    )

    assert response.accepted is False
    assert response.rejection is not None
    assert (
        response.rejection.category
        is AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE
    )
    assert response.rejection.code == "authority_client_timeout"
    assert response.metadata.request_id == "request-1"


def test_authority_client_maps_invalid_payload_to_protocol_rejection() -> None:
    def transport(
        _url: str,
        _payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        return {"not": "a protocol response"}

    client = AuthorityClient("http://authority.example", transport=transport)

    response = client.admit_run("file:///runs/r1", request_id="request-1")

    assert response.accepted is False
    assert response.rejection is not None
    assert response.rejection.category is AuthorityProtocolErrorCategory.INTERNAL_ERROR
    assert response.rejection.code == "authority_client_invalid_response"


def test_authority_client_sends_controller_and_stage_lease_payloads() -> None:
    captured: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured.append((url, payload))
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    client = AuthorityClient("http://authority.example", transport=transport)

    client.acquire_controller_lease(
        "file:///runs/r1",
        owner_id="runner",
        lease_ttl_seconds=60,
        request_id="controller-1",
    )
    client.renew_stage_lease(
        "file:///runs/r1",
        lease_id="lease-1",
        owner_id="runner",
        fencing_token="fence-1",
        lease_ttl_seconds=30,
        request_id="stage-renew-1",
    )

    assert captured[0][0].endswith(AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH)
    assert captured[0][1]["owner_id"] == "runner"
    assert captured[0][1]["body"] == {"lease_ttl_seconds": 60}
    assert captured[1][0].endswith(AUTHORITY_MUTATION_STAGE_LEASE_RENEW_PATH)
    assert captured[1][1]["lease_id"] == "lease-1"
    assert captured[1][1]["fencing_token"] == "fence-1"


def test_authority_client_sends_submitted_operation_payload() -> None:
    from loom.pipeline.submitted import (
        SubmittedOperationRecord,
        SubmittedOperationState,
    )

    captured: dict[str, object] = {}

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    record = SubmittedOperationRecord(
        run_uri="file:///runs/r1",
        submission_id="sub-1",
        backend="local",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1/manifest.json",
    )
    client = AuthorityClient("http://authority.example", transport=transport)

    client.write_submitted_operation("file:///runs/r1", record)

    assert str(captured["url"]).endswith(AUTHORITY_MUTATION_SUBMITTED_WRITE_PATH)
    payload = cast(Mapping[str, PlainData], captured["payload"])
    body = cast(Mapping[str, PlainData], payload["body"])
    submitted = cast(Mapping[str, PlainData], body["record"])
    assert submitted["submission_id"] == "sub-1"


def test_authority_client_sends_cleanup_report_payloads() -> None:
    captured: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured.append((url, payload))
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    report = CleanupReport(
        report_id="report-1",
        run_uri="file:///runs/r1",
        created_at="2020-01-01T00:00:00Z",
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=CleanupTargetRef(
                    kind=CleanupTargetKind.LOCAL_PATH,
                    uri="file:///runs/r1/tmp/payload",
                ),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
    )
    client = AuthorityClient("http://authority.example", transport=transport)

    client.append_cleanup_report("file:///runs/r1", report)
    client.list_cleanup_reports("file:///runs/r1")

    assert captured[0][0].endswith(AUTHORITY_MUTATION_CLEANUP_REPORT_APPEND_PATH)
    first_payload = cast(Mapping[str, PlainData], captured[0][1])
    first_body = cast(Mapping[str, PlainData], first_payload["body"])
    assert first_body["report"] == report.to_dict()
    assert captured[1][0].endswith(AUTHORITY_MUTATION_CLEANUP_REPORT_LIST_PATH)


def test_authority_client_sends_output_supersession_and_history_payloads() -> None:
    captured: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured.append((url, payload))
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    client = AuthorityClient("http://authority.example", transport=transport)
    client.record_output_commit(
        "file:///runs/r1",
        "build",
        attempt_id="build-2",
        owner_id="worker-1",
        fencing_token="fence-2",
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri="file:///runs/r1/artifacts/build/out.json",
                artifact_type="json",
            )
        },
        supersedes_commit_id="build-1-commit",
    )
    client.list_output_commits("file:///runs/r1", stage_name="build")

    assert captured[0][0].endswith(AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH)
    commit_body = cast(Mapping[str, PlainData], captured[0][1]["body"])
    assert commit_body["supersedes_commit_id"] == "build-1-commit"
    assert captured[1][0].endswith(AUTHORITY_MUTATION_LIST_OUTPUT_COMMITS_PATH)
    assert captured[1][1]["stage_name"] == "build"


def test_authority_client_sends_run_recovery_scan_payload() -> None:
    captured: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured.append((url, payload))
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    AuthorityClient("http://authority.example", transport=transport).scan_run_recovery(
        "file:///runs/r1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )

    assert captured[0][0].endswith(AUTHORITY_MUTATION_RUN_RECOVERY_SCAN_PATH)
    assert captured[0][1]["run_uri"] == "file:///runs/r1"
    metadata = AuthorityProtocolMetadata.from_dict(captured[0][1]["metadata"])
    assert metadata.operation_kind is AuthorityProtocolOperationKind.RECOVERY_SCAN


def test_authority_client_sends_workspace_coordination_payloads() -> None:
    captured: list[tuple[str, Mapping[str, PlainData]]] = []

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        captured.append((url, payload))
        metadata = AuthorityProtocolMetadata.from_dict(payload["metadata"])
        return accepted_authority_response(
            metadata,
            AuthorityProtocolResult(service_generation="generation-1"),
        ).to_dict()

    client = AuthorityClient("http://authority.example", transport=transport)
    workspace = WorkspaceIdentity(
        workspace_id="workspace-1",
        root_uri="file:///workspace",
        metadata={"team": "analysis"},
    )
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=1, token="trial-rev"),
    )

    client.create_workspace(workspace, request_id="workspace-create-1")
    client.record_trial(
        trial,
        request_id="trial-record-1",
        workspace_id="workspace-1",
    )
    client.acquire_trial_lease(
        "sweep-1",
        "trial-1",
        owner_id="worker-1",
        lease_ttl_seconds=30,
        request_id="trial-lease-1",
        workspace_id="workspace-1",
    )
    client.set_resource_limit("workspace-1", "gpu", limit=2)
    client.read_resource_limit("workspace-1", "gpu")
    client.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="worker-2",
        amount=1,
        lease_ttl_seconds=30,
    )

    assert captured[0][0].endswith(AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH)
    first_body = cast(Mapping[str, PlainData], captured[0][1]["body"])
    assert first_body["workspace"] == workspace.to_dict()
    first_metadata = AuthorityProtocolMetadata.from_dict(captured[0][1]["metadata"])
    assert (
        first_metadata.operation_kind
        is AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    )
    assert first_metadata.workspace_id == "workspace-1"
    trial_body = cast(Mapping[str, PlainData], captured[1][1]["body"])
    assert trial_body["trial"] == trial.to_dict()
    assert captured[2][0].endswith(AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH)
    assert captured[2][1]["owner_id"] == "worker-1"
    lease_body = cast(Mapping[str, PlainData], captured[2][1]["body"])
    assert lease_body == {
        "sweep_id": "sweep-1",
        "trial_id": "trial-1",
        "lease_ttl_seconds": 30,
    }
    assert captured[3][0].endswith(AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH)
    resource_body = cast(Mapping[str, PlainData], captured[3][1]["body"])
    assert resource_body == {
        "workspace_id": "workspace-1",
        "resource_key": "gpu",
        "limit": 2,
    }
    assert captured[4][0].endswith(AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH)
    read_body = cast(Mapping[str, PlainData], captured[4][1]["body"])
    assert read_body == {
        "workspace_id": "workspace-1",
        "resource_key": "gpu",
    }
    assert captured[5][0].endswith(AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH)
    assert captured[5][1]["owner_id"] == "worker-2"
    resource_lease_body = cast(Mapping[str, PlainData], captured[5][1]["body"])
    assert resource_lease_body == {
        "workspace_id": "workspace-1",
        "resource_key": "gpu",
        "amount": 1,
        "lease_ttl_seconds": 30,
    }
