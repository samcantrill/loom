"""In-process integration tests for the authority FastAPI skeleton."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from loom.authority.app import create_authority_app
from loom.authority.services import AuthorityAppServices


pytestmark = pytest.mark.integration


def test_operational_endpoints_work_with_in_process_test_client() -> None:
    client = TestClient(
        create_authority_app(
            services=AuthorityAppServices(
                service_generation="generation-1",
                workspace_id="workspace-a",
            )
        )
    )

    health = client.get("/health")
    live = client.get("/live")
    ready = client.get("/ready")
    version = client.get("/version")
    capabilities = client.get("/capabilities")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["service_generation"] == "generation-1"
    assert live.status_code == 200
    assert live.json()["live"] is True
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert version.status_code == 200
    assert version.json()["supported"] is True
    assert capabilities.status_code == 200
    assert capabilities.json()["backend_name"] == "fastapi-authority-skeleton"
