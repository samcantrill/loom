"""Integration coverage for the scoped coordinator authority adapter."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
import json
import socket
import ssl
import subprocess
import sys
from time import monotonic, sleep
from urllib import error, request
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
from loom.pipeline.stores.authority_client import AUTHORITY_MUTATION_RUN_ADMIT_PATH
from loom.pipeline.stores.authority import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    PreparedAttemptRequest,
)
from loom.pipeline.stores.coordinator_authority import (
    AuthenticatedCoordinatorAuthorityError,
    COORDINATOR_AUTHORITY_SERVICE_HEADER,
    COORDINATOR_OPEN_RUN_PATH,
    CoordinatorAuthorityTlsConfig,
    authenticated_coordinator_authority_factory,
    https_coordinator_authority_factory,
)
from loom.pipeline.stores.authority_protocol import (
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
)
from loom.authority.services import (
    AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY,
)
from loom.pipeline.stores.read_models import (
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
)
from loom.serialization import PlainData
from tests.support.mutual_tls import (
    certificate_fingerprint,
    mutual_tls_credentials,
)


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
    fact_revision = authority.write_reliability_policy_fact(RUN_URI, fact)
    replay_revision = authority.write_reliability_policy_fact(RUN_URI, fact)
    assert replay_revision == fact_revision
    assert authority.open_run(RUN_URI).revision == fact_revision
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
    valid.bind_coordinator_admission(
        RUN_URI,
        CoordinatorAdmissionRequest(
            operation_id="admit-valid",
            coordinator_id="coordinator-1",
            run_uri=RUN_URI,
            intent_digest="intent-valid",
        ),
    )
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


def test_coordinator_route_binds_service_id_to_verified_peer_certificate(
    tmp_path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path / "authority", service_generation="generation-1"
    )
    repository.admit_run(RUN_URI)
    peer_fingerprint = "a" * 64
    repository.bind_coordinator_admission(
        RUN_URI,
        CoordinatorAdmissionRequest(
            operation_id="admit-route-principal",
            coordinator_id="coordinator-1",
            run_uri=RUN_URI,
            intent_digest="intent-route-principal",
        ),
        service_principal="research-authority",
    )
    services = repository_authority_services(
        repository,
        workspace_id="workspace-a",
        coordinator_credentials={"research-authority": peer_fingerprint},
    )
    app = create_authority_app(services=services)

    @app.middleware("http")
    async def verified_peer(request, call_next):  # type: ignore[no-untyped-def]
        setattr(
            request.state,
            AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY,
            peer_fingerprint,
        )
        return await call_next(request)

    client = TestClient(app)
    payload = AuthorityProtocolRequest(
        AuthorityProtocolMetadata(
            request_id="coordinator-open-1",
            operation_kind=AuthorityProtocolOperationKind.COORDINATOR_EXECUTION,
            service_generation="generation-1",
            workspace_id="workspace-a",
            idempotency_key="coordinator-open-1",
        ),
        run_uri=RUN_URI,
    ).to_dict()

    accepted = client.post(
        COORDINATOR_OPEN_RUN_PATH,
        json=payload,
        headers={COORDINATOR_AUTHORITY_SERVICE_HEADER: "research-authority"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True

    wrong_service = client.post(
        COORDINATOR_OPEN_RUN_PATH,
        json=payload,
        headers={COORDINATOR_AUTHORITY_SERVICE_HEADER: "another-service"},
    )
    assert wrong_service.status_code == 403


def test_live_mutual_tls_authority_rejects_a_different_same_ca_peer(
    tmp_path: Path,
) -> None:
    credentials = mutual_tls_credentials(tmp_path / "tls")
    state_dir = tmp_path / "authority"
    repository = initialize_authority_repository(
        state_dir, service_generation="generation-1"
    )
    repository.admit_run(RUN_URI)
    other_run_uri = "file:///runs/coordinator-api-r2"
    repository.admit_run(other_run_uri)
    port = _available_port()
    endpoint = f"https://localhost:{port}"
    allowed_fingerprint = certificate_fingerprint(
        credentials["agent"].with_suffix(".crt")
    )
    other_fingerprint = certificate_fingerprint(
        credentials["other"].with_suffix(".crt")
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "loom.authority._server",
            "--state-dir",
            str(state_dir),
            "--workspace-id",
            "workspace-a",
            "--host",
            "localhost",
            "--port",
            str(port),
            "--tls-certificate",
            str(credentials["server"].with_suffix(".crt")),
            "--tls-private-key",
            str(credentials["server"].with_suffix(".key")),
            "--client-ca",
            str(credentials["ca"].with_suffix(".crt")),
            "--coordinator-credential",
            f"research-authority={allowed_fingerprint}",
            "--coordinator-credential",
            f"other-authority={other_fingerprint}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        allowed_factory = _wait_for_authority(
            endpoint,
            credentials=credentials,
            process=process,
        )
        allowed = allowed_factory(RUN_URI)
        allowed.bind_coordinator_admission(
            RUN_URI,
            CoordinatorAdmissionRequest(
                operation_id="admit-live-a",
                coordinator_id="coordinator-a",
                run_uri=RUN_URI,
                intent_digest="intent-live-a",
            ),
        )
        assert allowed.open_run(RUN_URI).run_uri == RUN_URI

        other_factory = https_coordinator_authority_factory(
            endpoint,
            service_id="other-authority",
            workspace_id="workspace-a",
            tls=CoordinatorAuthorityTlsConfig(
                credentials["ca"].with_suffix(".crt"),
                credentials["other"].with_suffix(".crt"),
                credentials["other"].with_suffix(".key"),
            ),
            timeout_seconds=1.0,
        )
        other = other_factory(other_run_uri)
        other.bind_coordinator_admission(
            other_run_uri,
            CoordinatorAdmissionRequest(
                operation_id="admit-live-b",
                coordinator_id="coordinator-b",
                run_uri=other_run_uri,
                intent_digest="intent-live-b",
            ),
        )
        assert other.open_run(other_run_uri).run_uri == other_run_uri
        for authority, foreign_run in (
            (allowed_factory(other_run_uri), other_run_uri),
            (other_factory(RUN_URI), RUN_URI),
        ):
            with pytest.raises(
                AuthenticatedCoordinatorAuthorityError,
                match="principal conflicts",
            ):
                authority.open_run(foreign_run)
        with pytest.raises(
            AuthenticatedCoordinatorAuthorityError,
            match="principal conflicts",
        ):
            other_factory(RUN_URI).bind_coordinator_admission(
                RUN_URI,
                CoordinatorAdmissionRequest(
                    operation_id="admit-live-a",
                    coordinator_id="coordinator-a",
                    run_uri=RUN_URI,
                    intent_digest="intent-live-a",
                ),
            )

        denied_factory = https_coordinator_authority_factory(
            endpoint,
            service_id="research-authority",
            workspace_id="workspace-a",
            tls=CoordinatorAuthorityTlsConfig(
                credentials["ca"].with_suffix(".crt"),
                credentials["other"].with_suffix(".crt"),
                credentials["other"].with_suffix(".key"),
            ),
            timeout_seconds=1.0,
        )
        with pytest.raises(
            AuthenticatedCoordinatorAuthorityError,
            match="authority service is unavailable",
        ) as denied:
            denied_factory(RUN_URI).open_run(RUN_URI)
        assert denied.value.code == "authority_client_unavailable"

        context = ssl.create_default_context(
            cafile=str(credentials["ca"].with_suffix(".crt"))
        )
        context.load_cert_chain(
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
        generic_mutation = request.Request(
            f"{endpoint}{AUTHORITY_MUTATION_RUN_ADMIT_PATH}",
            data=json.dumps({}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(error.HTTPError) as hidden:
            request.urlopen(generic_mutation, context=context, timeout=1.0)
        assert hidden.value.code == 404
    finally:
        process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5.0)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_authority(
    endpoint: str,
    *,
    credentials: Mapping[str, Path],
    process: subprocess.Popen[str],
):
    deadline = monotonic() + 10.0
    last_error: Exception | None = None
    tls = CoordinatorAuthorityTlsConfig(
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
    )
    while monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                "authority process exited before readiness\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            return https_coordinator_authority_factory(
                endpoint,
                service_id="research-authority",
                workspace_id="workspace-a",
                tls=tls,
                timeout_seconds=0.2,
            )
        except Exception as exc:  # readiness spans socket, TLS, and protocol startup
            last_error = exc
            sleep(0.05)
    pytest.fail(f"authority process did not become ready: {last_error}")
