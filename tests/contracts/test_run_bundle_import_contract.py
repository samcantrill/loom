"""Contract coverage for concrete run import adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.historical_offline_evidence import (
    complete_manifest as _complete_manifest,
)

from loom.authority._repository import initialize_authority_repository
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import BackendRevision, CompletedRunBundleMetadata
from loom.runs import (
    LocalRunBundleImporter,
    OfflineEvidenceRunImporter,
    RunExchangeOperationStatus,
    RunImporter,
    build_offline_evidence_import_record,
    build_portable_run_import_record,
    export_completed_run_bundle,
)


pytestmark = pytest.mark.contract


def test_local_bundle_importer_conforms_to_run_importer_protocol(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.tar"
    export_completed_run_bundle(_metadata(), bundle_path)
    importer = LocalRunBundleImporter(tmp_path / "target-runs")
    record = build_portable_run_import_record(bundle_path)

    assert isinstance(importer, RunImporter)
    inspection = importer.inspect(record)
    result = importer.import_record(record)

    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.target_run_uri is not None


def test_offline_evidence_importer_conforms_to_run_importer_protocol(
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(tmp_path)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    importer = OfflineEvidenceRunImporter(
        repository,
        imported_by="pytest",
        workspace_id="workspace-a",
    )
    record = build_offline_evidence_import_record(manifest)

    assert isinstance(importer, RunImporter)
    inspection = importer.inspect(record)
    result = importer.import_record(record)

    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.target_run_uri == manifest.run_uri


def _metadata() -> CompletedRunBundleMetadata:
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
    )
