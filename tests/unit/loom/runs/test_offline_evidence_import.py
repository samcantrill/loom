"""Unit tests for the offline evidence import adapter surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.historical_offline_evidence import (
    complete_manifest as _complete_manifest,
)

from loom.authority._repository import initialize_authority_repository
from loom.pipeline.offline_evidence import OfflineEvidenceManifest
from loom.pipeline.status import RunStatus, StageStatus
from loom.runs import (
    OFFLINE_EVIDENCE_IMPORT_ADAPTER,
    MigrationReadinessBlockerCode,
    RunExchangeOperationStatus,
    build_offline_evidence_import_record,
    import_offline_evidence,
)
from loom.serialization import thaw_plain_data


pytestmark = pytest.mark.unit


def test_offline_evidence_record_uses_shared_import_shape(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)

    record = build_offline_evidence_import_record(manifest)

    assert record.adapter == OFFLINE_EVIDENCE_IMPORT_ADAPTER
    assert record.manifest.run_uri == manifest.run_uri
    assert record.manifest.entries == ()
    assert record.manifest.payload_refs == ()
    assert thaw_plain_data(record.extensions["offline_evidence_manifest"]) == (
        manifest.to_dict()
    )


def test_import_offline_evidence_returns_shared_result_and_authority_facts(
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(tmp_path)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )

    result = import_offline_evidence(
        repository,
        manifest,
        imported_by="pytest",
        workspace_id="workspace-a",
    )

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.adapter == OFFLINE_EVIDENCE_IMPORT_ADAPTER
    assert result.target_run_uri == manifest.run_uri
    assert result.imported_entry_count == 4
    assert result.imported_payload_count == 0
    assert [blocker.code for blocker in result.readiness.blockers] == [
        MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY
    ]
    snapshot = repository.open_run(manifest.run_uri)
    assert snapshot.status is RunStatus.SUCCEEDED
    assert [stage.status for stage in snapshot.stages] == [
        StageStatus.SUCCEEDED,
        StageStatus.SUCCEEDED,
    ]


def test_import_offline_evidence_maps_validation_diagnostics(tmp_path: Path) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    payload["manifest_status"] = "incomplete"
    manifest = OfflineEvidenceManifest.from_dict(payload)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )

    result = import_offline_evidence(repository, manifest)

    assert result.status is RunExchangeOperationStatus.FAILED
    assert result.target_run_uri is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "offline_import.incomplete_manifest"
    ]
    assert {blocker.code for blocker in result.readiness.blockers} == {
        MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY
    }
