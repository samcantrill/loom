"""Current native capture remains importable as historical evidence."""

from collections.abc import Mapping
import json
from pathlib import Path

import pytest

from loom.authority._repository import initialize_authority_repository
from loom.pipeline.offline_evidence import (
    read_offline_evidence_manifest,
    write_offline_evidence_manifest,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.runs import import_offline_evidence, RunExchangeOperationStatus
from tests.support.native_run_fixture import run_native_fixture
from tests.support.pipeline_execution_configs import local_execution_config

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_native_terminal_capture_imports_without_live_resume(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.json"
    config.write_text(json.dumps(local_execution_config(value=7)))
    admission, local = run_native_fixture(config)
    assert admission.state.value == "SUCCEEDED"
    authority = SQLitePerRunAuthorityStore(admission.run_uri, read_only=True)
    snapshot = authority.snapshot(admission.run_uri)

    manifest = write_offline_evidence_manifest(local, admission.run_uri)
    assert manifest.complete, manifest.diagnostics
    assert manifest.run_status is not None
    assert manifest.run_status["status"] == "SUCCEEDED"
    assert manifest.run_status["started_at"] == snapshot.started_at
    assert manifest.run_status["finished_at"] == snapshot.finished_at
    details = manifest.state_source["details"]
    assert isinstance(details, Mapping)
    assert details["authority_revision"] == snapshot.revision.to_dict()
    assert [stage.stage_name for stage in manifest.stages] == ["build", "report"]
    for stage in manifest.stages:
        assert stage.status is not None
        assert stage.status["status"] == "SUCCEEDED"
        assert len(stage.artifacts) == 1
        payload = stage.artifacts[0].payload
        assert payload is not None
        assert payload.exists is True
        assert payload.checksum is not None
    path = local.local_generated_artifact_path(
        admission.run_uri,
        "offline-evidence/manifest.json",
    )
    retained = read_offline_evidence_manifest(path)
    assert retained == manifest
    repository = initialize_authority_repository(
        tmp_path / "imported-authority",
        service_generation="import-generation",
    )
    result = import_offline_evidence(repository, retained)
    assert result.status is RunExchangeOperationStatus.SUCCEEDED, result.diagnostics
    imported = repository.open_run(admission.run_uri)
    assert imported.status is RunStatus.SUCCEEDED
    assert [stage.status for stage in imported.stages] == [StageStatus.SUCCEEDED] * 2
    assert [stage.active_lease for stage in imported.stages] == [None, None]
    provenance = imported.metadata["authority_import"]
    assert isinstance(provenance, Mapping)
    assert provenance["historical_only"] is True
    assert provenance["resumable_live"] is False
