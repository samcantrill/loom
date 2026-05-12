"""Unit tests for the authority HTTP client adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from loom.pipeline.stores import (
    AUTHORITY_MUTATION_RUN_ADMIT_PATH,
    AuthorityClient,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
    AuthorityProtocolResult,
    accepted_authority_response,
)
from loom.pipeline.stores.authority_client import (
    AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH,
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
    assert response.rejection.category is AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE
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
