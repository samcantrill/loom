"""Contract coverage for concrete run import adapters."""

from __future__ import annotations

from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest

from loom.authority._repository import initialize_authority_repository
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_offline_evidence_run_store
from loom.pipeline.offline_evidence import OfflineEvidenceManifest
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import BackendRevision, CompletedRunBundleMetadata, path_to_run_uri
from loom.runs import (
    LocalRunBundleImporter,
    OfflineEvidenceRunImporter,
    RunExchangeOperationStatus,
    RunImporter,
    build_offline_evidence_import_record,
    build_portable_run_import_record,
    export_completed_run_bundle,
)
from tests.support.pipeline_execution_configs import local_execution_config


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
