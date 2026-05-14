"""Contract coverage for local bundle export and inspect behavior."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from loom.io.uris import path_to_file_uri
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    BackendRevision,
    CompletedRunBundleMetadata,
    MaterializedRef,
    MaterializedRefKind,
)
from loom.runs import (
    LocalRunBundleExporter,
    RunBundleExportOptions,
    RunExchangeOperationStatus,
    RunExporter,
    build_portable_run_export_record,
    export_completed_run_bundle,
    inspect_run_bundle,
)


def _metadata(payload: Path) -> CompletedRunBundleMetadata:
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        materialized_refs=(
            MaterializedRef(
                kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
                uri=path_to_file_uri(payload),
                exists=True,
            ),
        ),
    )


def test_local_bundle_exporter_conforms_to_run_exporter_protocol(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    record = build_portable_run_export_record(
        _metadata(payload),
        options=RunBundleExportOptions(include_payloads=True),
    )
    exporter = LocalRunBundleExporter(tmp_path / "bundle.tar")

    assert isinstance(exporter, RunExporter)
    result = exporter.export(record, options=RunBundleExportOptions(include_payloads=True))

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.exported_payload_count == 1
    inspection = inspect_run_bundle(tmp_path / "bundle.tar", verify_checksums=True)
    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
    assert inspection.to_dict()["included_payload_count"] == 1


def test_metadata_only_export_writes_manifest_without_payload_members(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")

    result = export_completed_run_bundle(_metadata(payload), tmp_path / "bundle.tar")

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.exported_payload_count == 0
    with tarfile.open(tmp_path / "bundle.tar", "r") as archive:
        assert archive.getnames() == ["manifest.json"]


def test_local_bundle_exporter_writes_symlink_payload_as_regular_member(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    payload_link = tmp_path / "payload-link.bin"
    try:
        payload_link.symlink_to(payload)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = export_completed_run_bundle(
        _metadata(payload_link),
        tmp_path / "bundle.tar",
        options=RunBundleExportOptions(include_payloads=True),
    )

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    with tarfile.open(tmp_path / "bundle.tar", "r") as archive:
        payload_members = [
            member for member in archive.getmembers() if member.name != "manifest.json"
        ]
    assert len(payload_members) == 1
    assert payload_members[0].isfile()
    inspection = inspect_run_bundle(tmp_path / "bundle.tar", verify_checksums=True)
    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
