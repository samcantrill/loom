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
