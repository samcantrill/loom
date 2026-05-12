"""Integration coverage for offline import through authority API routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from loom.authority._repository import (
    AuthorityRepository,
    AuthorityRepositoryError,
    initialize_authority_repository,
)
from loom.authority.app import create_authority_app
from loom.authority.services import repository_authority_services
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_offline_evidence_run_store
from loom.pipeline.offline_evidence import OfflineEvidenceManifest
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityClient,
    AuthorityProtocolErrorCategory,
    path_to_run_uri,
)
from loom.serialization import PlainData
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.integration


def test_offline_import_api_imports_manifest_and_exposes_snapshot(
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(tmp_path)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    client = _client(repository)

    response = client.import_offline_evidence(
        manifest.to_dict(),
        request_id="import-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )

    assert response.accepted is True
    assert response.result is not None
    result = response.result.body["offline_import"]
    assert isinstance(result, Mapping)
    assert result["run_uri"] == manifest.run_uri
    assert result["imported_stage_count"] == 2
    snapshot_response = client.open_run(
        manifest.run_uri,
        request_id="open-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )
    assert snapshot_response.accepted is True
    assert snapshot_response.result is not None
    assert snapshot_response.result.snapshot is not None
    snapshot = snapshot_response.result.snapshot
    assert snapshot.status is RunStatus.SUCCEEDED
    assert [stage.status for stage in snapshot.stages] == [
        StageStatus.SUCCEEDED,
        StageStatus.SUCCEEDED,
    ]
    import_provenance = snapshot.metadata["authority_import"]
    assert isinstance(import_provenance, Mapping)
    assert import_provenance["source"] == "offline_evidence"


def test_offline_import_api_rejects_invalid_manifest_without_mutating(
    tmp_path: Path,
) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    payload["manifest_status"] = "incomplete"
    manifest = OfflineEvidenceManifest.from_dict(payload)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    client = _client(repository)

    response = client.import_offline_evidence(
        manifest.to_dict(),
        request_id="import-1",
        service_generation="generation-1",
        workspace_id="workspace-a",
    )

    assert response.accepted is False
    assert response.rejection is not None
    assert response.rejection.category is AuthorityProtocolErrorCategory.VALIDATION
    assert response.rejection.code == "authority_offline_import_incomplete"
    with pytest.raises(AuthorityRepositoryError, match="unknown run"):
        repository.open_run(manifest.run_uri)


def _client(repository: AuthorityRepository) -> AuthorityClient:
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
        response = app_client.post(urlsplit(url).path, json=payload)
        assert response.status_code == 200
        parsed = response.json()
        assert isinstance(parsed, Mapping)
        return cast(Mapping[str, object], parsed)

    return AuthorityClient("http://authority.test", transport=transport)


def _complete_manifest(tmp_path: Path, *, name: str = "offline-run") -> OfflineEvidenceManifest:
    run_store = create_offline_evidence_run_store(
        tmp_path / "offline-runs",
        owner_id="offline-test",
        workspace_id="workspace-a",
    )
    run_uri = path_to_run_uri(tmp_path / "offline-runs" / name)
    result = PipelineRunner(run_store=run_store, clock=_sequence_clock()).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )
    assert result.status is RunStatus.SUCCEEDED
    manifest = run_store.read_offline_evidence_manifest(run_uri)
    assert manifest is not None
    return manifest


def _sequence_clock() -> Callable[[], str]:
    ticks = count(1)

    def clock() -> str:
        return f"2020-01-01T00:00:{next(ticks):02d}Z"

    return clock
