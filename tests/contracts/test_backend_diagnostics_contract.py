"""Contract tests for backend-neutral diagnostics helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.diagnostics.backend import inspect_backend, inspect_backend_capabilities
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


pytestmark = pytest.mark.contract


def test_backend_diagnostics_accept_per_run_authority_contract(tmp_path: Path) -> None:
    store = InMemoryPerRunAuthorityStore()
    run_uri = path_to_run_uri(tmp_path / "runs" / "contract")
    store.create_run(run_uri)
    store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    )

    result = inspect_backend(run_uri, authority_store=store)
    capabilities = inspect_backend_capabilities(run_uri, authority_store=store)

    assert result.run_uri == run_uri
    assert result.status == "RUNNING"
    assert result.backend_name == "in-memory-authority-test-store"
    assert result.state_source["label"] == "authoritative_service_truth"
    assert capabilities.backend_name == result.backend_name
    assert capabilities.state_source["label"] == "authoritative_service_truth"
    assert capabilities.capabilities
