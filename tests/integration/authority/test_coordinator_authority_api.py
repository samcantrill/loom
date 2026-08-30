"""Integration coverage for the scoped coordinator authority adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from loom.artifacts import ArtifactRef
from loom.authority._repository import initialize_authority_repository
from loom.authority.app import create_authority_app
from loom.authority.services import repository_authority_services
from loom.pipeline.reliability import ReliabilityPolicy
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import AuthorityClient
from loom.pipeline.stores.authority import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    PreparedAttemptRequest,
)
from loom.pipeline.stores.coordinator_authority import (
    AuthenticatedCoordinatorAuthorityError,
    authenticated_coordinator_authority_factory,
)
from loom.pipeline.stores.read_models import (
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.integration

RUN_URI = "file:///runs/coordinator-api-r1"


def _authority(tmp_path, *, workspace_id: str = "workspace-a"):
    repository = initialize_authority_repository(
        tmp_path / "authority", service_generation="generation-1"
    )
    services = repository_authority_services(
        repository, workspace_id="workspace-a"
    )
    app_client = TestClient(create_authority_app(services=services))

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        response = app_client.post(urlsplit(url).path, json=payload)
        assert response.status_code == 200
        parsed = response.json()
        assert isinstance(parsed, dict)
        return parsed

    factory = authenticated_coordinator_authority_factory(
        AuthorityClient("https://authority.test", transport=transport),
        service_id="research-authority",
        workspace_id=workspace_id,
        service_generation="generation-1",
    )
    return repository, factory(RUN_URI)


def _prepared_request(revision) -> PreparedAttemptRequest:
    return PreparedAttemptRequest(
        operation_id="prepare-1",
        request_digest="digest-1",
        admission_id="admission-1",
        stage_name="build",
        readiness_generation="ready-1",
        expected_revision=revision,
        expected_stage_status=None,
        expected_attempt_id=None,
        next_attempt=1,
        owner_id="coordinator-1",
        plan_fingerprint="plan-1",
        bound_inputs={},
        upstream_commits={},
    )


def test_scoped_adapter_preserves_receipts_fences_outputs_and_reliability(
    tmp_path,
) -> None:
    repository, authority = _authority(tmp_path)
    revision = repository.admit_run(RUN_URI)
    admission = CoordinatorAdmissionRequest(
        operation_id="admit-1",
        coordinator_id="coordinator-1",
        run_uri=RUN_URI,
        intent_digest="intent-1",
    )

    assert authority.bind_coordinator_admission(RUN_URI, admission).request == admission
    prepared = authority.ensure_prepared_attempt(RUN_URI, _prepared_request(revision))
    assert prepared == authority.ensure_prepared_attempt(
        RUN_URI, _prepared_request(revision)
    )
    authority.bind_prepared_attempt(
        RUN_URI,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    fence = authority.grant_prepared_attempt(
        RUN_URI,
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
    )
    authority.confirm_execution_started(RUN_URI, fence=fence)
    artifact = ArtifactRef(
        artifact_id="build/out",
        uri="file:///artifacts/build/out.json",
        artifact_type="json",
    )
    commit = authority.record_output_commit(
        RUN_URI,
        "build",
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
        fencing_token=fence.fencing_token,
        outputs={"out": artifact},
    )
    replay = authority.record_output_commit(
        RUN_URI,
        "build",
        assignment_id="assignment-1",
        attempt_id=prepared.attempt.attempt_id,
        fencing_token=fence.fencing_token,
        outputs={"out": artifact},
    )
    assert replay == commit
    assert authority.open_run(RUN_URI).stages[0].status is StageStatus.SUCCEEDED

    fact = ReliabilityPolicyFact(
        run_uri=RUN_URI,
        scope=ReliabilityPolicyScope.RUN,
        policy=ReliabilityPolicy(),
        recorded_at="2026-08-30T00:00:00Z",
    )
    authority.write_reliability_policy_fact(RUN_URI, fact)
    authority.write_reliability_policy_fact(RUN_URI, fact)
    assert authority.list_reliability_policy_facts(RUN_URI) == (fact,)


def test_scoped_adapter_rejects_workspace_and_changed_retry_payload(tmp_path) -> None:
    repository, authority = _authority(tmp_path, workspace_id="workspace-b")
    repository.admit_run(RUN_URI)

    with pytest.raises(
        AuthenticatedCoordinatorAuthorityError,
        match="workspace conflicts",
    ):
        authority.open_run(RUN_URI)

    _repository, valid = _authority(tmp_path / "valid")
    valid_revision = _repository.admit_run(RUN_URI)
    valid.ensure_prepared_attempt(RUN_URI, _prepared_request(valid_revision))
    with pytest.raises(AuthenticatedCoordinatorAuthorityError, match="conflicts"):
        valid.ensure_prepared_attempt(
            RUN_URI,
            replace(_prepared_request(valid_revision), request_digest="changed"),
        )


def test_scoped_cancellation_is_durable_and_replay_safe(tmp_path) -> None:
    repository, authority = _authority(tmp_path)
    repository.admit_run(RUN_URI)
    authority.bind_coordinator_admission(
        RUN_URI,
        CoordinatorAdmissionRequest(
            operation_id="admit-1",
            coordinator_id="coordinator-1",
            run_uri=RUN_URI,
            intent_digest="intent-1",
        ),
    )
    cancellation = CancellationEpochRequest(
        operation_id="cancel-1",
        coordinator_id="coordinator-1",
        run_uri=RUN_URI,
        stage_names=("build",),
    )
    receipt = authority.install_cancellation_epoch(RUN_URI, cancellation)
    assert authority.read_cancellation_epoch_receipt(RUN_URI, "cancel-1") == receipt
    assert authority.finalize_cancellation(RUN_URI, cancellation).value == "CANCELLED"
    assert authority.finalize_cancellation(RUN_URI, cancellation).value == "CANCELLED"
