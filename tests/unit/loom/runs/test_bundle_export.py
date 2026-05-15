"""Unit tests for local run bundle export helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ExternalArtifactDeclaration,
)
from loom.io.uris import path_to_file_uri
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    ArtifactFactRecord,
    BackendRevision,
    CompletedRunBundleMetadata,
    MaterializedRef,
    MaterializedRefKind,
)
from loom.runs import (
    EXTERNAL_ARTIFACT_METADATA_KEY,
    RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY,
    UNSUPPORTED_MATERIALIZATION_METADATA_KEY,
    CatalogValidationError,
    RunBundleExportOptions,
    RunExchangeDiagnosticSeverity,
    RunExchangeOperationStatus,
    build_portable_run_export_record,
    export_completed_run_bundle,
    normalize_bundle_member_path,
    unsupported_materialization_summary,
)
from loom.serialization import thaw_plain_data


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


def test_metadata_only_export_projects_stage_15_artifact_summaries(
    tmp_path: Path,
) -> None:
    result = export_completed_run_bundle(
        _metadata_with_external_artifact(),
        tmp_path / "bundle.tar",
    )

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.exported_payload_count == 0
    assert result.manifest is not None
    summary = cast(
        dict[str, Any],
        result.manifest.extensions[RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY],
    )
    artifact = cast(list[dict[str, Any]], summary["artifacts"])[0]
    summaries = cast(dict[str, Any], artifact["summaries"])
    external = cast(dict[str, Any], summaries[EXTERNAL_ARTIFACT_METADATA_KEY])
    assert external["artifact_id"] == "external-model"
    assert external["store"]["uri"] is None
    assert external["store"]["display_uri"] == "s3://bucket/redacted/model"
    assert (
        summaries[UNSUPPORTED_MATERIALIZATION_METADATA_KEY]["code"]
        == "artifact_materialization.unsupported"
    )
    assert result.extensions[RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY] == summary
    assert [
        diagnostic.code
        for diagnostic in result.manifest.warnings
        if diagnostic.severity is RunExchangeDiagnosticSeverity.WARNING
    ] == ["run_exchange.artifact_materialization_unsupported"]


def _metadata_with_external_artifact() -> CompletedRunBundleMetadata:
    artifact = _external_artifact_ref()
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        artifact_facts=(
            ArtifactFactRecord(
                artifact_name="model",
                artifact=artifact,
                commit_id="commit-1",
                revision=BackendRevision(sequence=1, token="rev-1"),
            ),
        ),
    )


def _external_artifact_ref() -> ArtifactRef:
    checksum = "sha256:" + "3" * 64
    location = ArtifactLocationSummary(
        kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
        authority="authoritative",
        display_uri="s3://bucket/redacted/model",
        store=ArtifactStoreRef(kind="object-store", display_uri="s3://bucket"),
        checksum=checksum,
    )
    declaration = ExternalArtifactDeclaration(
        artifact_id="external-model",
        uri="s3://bucket/private/model",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        store=ArtifactStoreRef(
            kind="object-store",
            display_uri="s3://bucket/redacted/model",
        ),
        location=location,
        checksum=checksum,
    )
    return ArtifactRef(
        artifact_id="external-model",
        uri="s3://bucket/private/model",
        artifact_type="model",
        codec_key="json.v1",
        checksum=checksum,
        metadata={
            EXTERNAL_ARTIFACT_METADATA_KEY: thaw_plain_data(declaration.to_summary()),
            UNSUPPORTED_MATERIALIZATION_METADATA_KEY: unsupported_materialization_summary(
                "remote materialization is deferred to Stage 16",
                location=location,
            ),
        },
    )
