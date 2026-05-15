"""Unit tests for local run bundle import helpers."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Mapping
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
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    ArtifactFactRecord,
    BackendRevision,
    CompletedRunBundleMetadata,
    LocalRunStore,
    MaterializedRef,
    MaterializedRefKind,
    StageLifecycleSnapshot,
    run_uri_to_path,
)
from loom.runs import (
    EXTERNAL_ARTIFACT_METADATA_KEY,
    RUN_BUNDLE_MANIFEST_MEMBER,
    RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY,
    UNSUPPORTED_MATERIALIZATION_METADATA_KEY,
    MigrationReadinessBlockerCode,
    RunBundleExportOptions,
    RunExchangeOperationStatus,
    RunImportResumeMode,
    build_portable_run_import_record,
    export_completed_run_bundle,
    import_run_bundle,
    unsupported_materialization_summary,
)
from loom.serialization import stable_json_bytes, thaw_plain_data


pytestmark = pytest.mark.unit


def test_build_import_record_from_local_bundle(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.tar"
    export_result = export_completed_run_bundle(
        _metadata(),
        bundle_path,
    )
    assert export_result.status is RunExchangeOperationStatus.SUCCEEDED

    record = build_portable_run_import_record(bundle_path)

    assert record.manifest.run_uri == "file:///runs/source/run-1"
    assert record.extensions["bundle_path"] == str(bundle_path)
    assert record.provenance["bundle_member"] == RUN_BUNDLE_MANIFEST_MEMBER
    assert record.diagnostics == ()


def test_import_bundle_writes_historical_target_run(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.tar"
    target_collection = tmp_path / "target-runs"
    export_completed_run_bundle(_metadata(), bundle_path)

    result = import_run_bundle(bundle_path, target_collection)

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.target_run_uri is not None
    assert result.target_run_uri.endswith("/target-runs/run-1")
    assert result.imported_entry_count == 0
    assert result.readiness.mode is RunImportResumeMode.HISTORICAL_ONLY
    assert [blocker.code for blocker in result.readiness.blockers] == [
        MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY
    ]
    store = LocalRunStore(target_collection)
    status = store.read_run_status(result.target_run_uri)
    assert status is not None
    assert status.status is RunStatus.SUCCEEDED
    runtime = store.read_runtime_metadata(result.target_run_uri)
    assert runtime is not None
    assert runtime["source_run_uri"] == "file:///runs/source/run-1"


def test_import_rejects_target_identity_collision_without_overwrite(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.tar"
    target_collection = tmp_path / "target-runs"
    export_completed_run_bundle(_metadata(), bundle_path)
    first = import_run_bundle(bundle_path, target_collection)
    assert first.status is RunExchangeOperationStatus.SUCCEEDED

    second = import_run_bundle(bundle_path, target_collection)

    assert second.status is RunExchangeOperationStatus.FAILED
    assert [diagnostic.code for diagnostic in second.diagnostics] == [
        "run_bundle_import.target_collision"
    ]
    assert second.target_run_uri == first.target_run_uri
    assert first.target_run_uri is not None
    assert run_uri_to_path(first.target_run_uri).exists()
    assert LocalRunStore(target_collection).read_run_status(first.target_run_uri) is not None


def test_import_rejects_checksum_mismatch_before_creating_target(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    bundle_path = tmp_path / "corrupt.tar"
    manifest = export_completed_run_bundle(
        _metadata(
            (
                MaterializedRef(
                    kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
                    uri=path_to_file_uri(payload),
                    exists=True,
                ),
            )
        ),
        tmp_path / "source.tar",
        options=RunBundleExportOptions(include_payloads=True, verify_checksums=True),
    ).manifest
    assert manifest is not None
    assert manifest.entries
    _write_corrupt_payload_bundle(bundle_path, manifest.to_dict(), manifest.entries[0].path)

    result = import_run_bundle(bundle_path, tmp_path / "target-runs")

    assert result.status is RunExchangeOperationStatus.FAILED
    assert "run_bundle_inspect.checksum_mismatch" in {
        diagnostic.code for diagnostic in result.diagnostics
    }
    assert result.target_run_uri is not None
    assert not run_uri_to_path(result.target_run_uri).exists()


def test_import_preserves_stage_15_summaries_without_payloads(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.tar"
    target_collection = tmp_path / "target-runs"
    export_completed_run_bundle(_metadata_with_external_stage_artifact(), bundle_path)

    record = build_portable_run_import_record(bundle_path)
    assert RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY in record.extensions

    result = import_run_bundle(bundle_path, target_collection)

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.imported_payload_count == 0
    summary = cast(
        dict[str, Any],
        result.import_provenance[RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY],
    )
    artifact = cast(list[dict[str, Any]], summary["artifacts"])[0]
    summaries = cast(dict[str, Any], artifact["summaries"])
    assert EXTERNAL_ARTIFACT_METADATA_KEY in summaries
    assert (
        summaries[UNSUPPORTED_MATERIALIZATION_METADATA_KEY]["code"]
        == "artifact_materialization.unsupported"
    )
    assert "run_exchange.artifact_materialization_unsupported" in {
        diagnostic.code for diagnostic in result.diagnostics
    }

    assert result.target_run_uri is not None
    artifact_index = LocalRunStore(target_collection).read_artifact_index(
        result.target_run_uri
    )
    imported_ref = artifact_index["build.model"]
    imported_summaries = cast(dict[str, Any], thaw_plain_data(imported_ref.metadata))
    assert EXTERNAL_ARTIFACT_METADATA_KEY in imported_summaries
    assert imported_ref.uri == "s3://bucket/private/model"


def _metadata(
    refs: tuple[MaterializedRef, ...] = (),
) -> CompletedRunBundleMetadata:
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        materialized_refs=refs,
    )


def _metadata_with_external_stage_artifact() -> CompletedRunBundleMetadata:
    artifact = _external_artifact_ref()
    revision = BackendRevision(sequence=1, token="rev-1")
    fact = ArtifactFactRecord(
        artifact_name="model",
        artifact=artifact,
        commit_id="commit-1",
        revision=revision,
    )
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=revision,
        stages=(
            StageLifecycleSnapshot(
                stage_name="build",
                status=StageStatus.SUCCEEDED,
                revision=revision,
                artifact_facts=(fact,),
            ),
        ),
        artifact_facts=(fact,),
    )


def _external_artifact_ref() -> ArtifactRef:
    checksum = "sha256:" + "4" * 64
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
        producer_stage="build",
        metadata={
            EXTERNAL_ARTIFACT_METADATA_KEY: thaw_plain_data(declaration.to_summary()),
            UNSUPPORTED_MATERIALIZATION_METADATA_KEY: unsupported_materialization_summary(
                "remote materialization is deferred to Stage 16",
                location=location,
            ),
        },
    )


def _write_corrupt_payload_bundle(
    bundle_path: Path,
    manifest_payload: Mapping[str, object],
    entry_path: str,
) -> None:
    manifest_bytes = stable_json_bytes(manifest_payload)
    corrupt_payload = b"corrupt"
    with tarfile.open(bundle_path, "w") as archive:
        manifest_info = tarfile.TarInfo(RUN_BUNDLE_MANIFEST_MEMBER)
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        payload_info = tarfile.TarInfo(entry_path)
        payload_info.size = len(corrupt_payload)
        archive.addfile(payload_info, io.BytesIO(corrupt_payload))
