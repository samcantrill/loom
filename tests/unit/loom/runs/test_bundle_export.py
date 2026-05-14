"""Unit tests for local run bundle export helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

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
    CatalogValidationError,
    RunBundleExportOptions,
    RunExchangeOperationStatus,
    build_portable_run_export_record,
    export_completed_run_bundle,
    normalize_bundle_member_path,
)


def _metadata(refs: tuple[MaterializedRef, ...] = ()) -> CompletedRunBundleMetadata:
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        materialized_refs=refs,
    )


def test_bundle_member_path_normalization_rejects_unsafe_paths() -> None:
    assert normalize_bundle_member_path("payloads/out.txt") == "payloads/out.txt"

    for unsafe in ("/absolute", "../escape", "payloads/../escape", r"bad\path"):
        with pytest.raises(CatalogValidationError):
            normalize_bundle_member_path(unsafe)


def test_export_record_is_metadata_only_by_default(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    record = build_portable_run_export_record(
        _metadata(
            (
                MaterializedRef(
                    kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
                    uri=path_to_file_uri(payload),
                    exists=True,
                ),
            )
        )
    )

    assert record.selected_payload_refs == ()
    assert record.manifest is not None
    assert record.manifest.entries == ()
    assert record.manifest.payload_selection.include_artifacts is False
    completed_run = cast(dict[str, object], record.manifest.extensions["completed_run"])
    assert completed_run["status"] == "SUCCEEDED"


def test_explicit_payload_selection_reports_missing_file(tmp_path: Path) -> None:
    missing_uri = path_to_file_uri(tmp_path / "missing.bin")
    result = export_completed_run_bundle(
        _metadata(
            (
                MaterializedRef(
                    kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
                    uri=missing_uri,
                    exists=False,
                ),
            )
        ),
        tmp_path / "bundle.tar",
        options=RunBundleExportOptions(include_payloads=True),
    )

    assert result.status is RunExchangeOperationStatus.FAILED
    assert result.manifest is not None
    assert result.manifest.entries == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "run_bundle_export.payload_missing"
    ]
    assert not (tmp_path / "bundle.tar").exists()
