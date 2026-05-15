"""Contract coverage for local bundle export and inspect behavior."""

from __future__ import annotations

import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from loom.artifacts import ArtifactLocationKind, ArtifactLocationSummary, ArtifactStoreRef
from loom.fingerprints import hash_bytes
from loom.io.uris import path_to_file_uri, uri_to_path
from loom.operations import OperationResult, OperationStatus
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreCapabilities,
    ArtifactStorePayloadOperationRequest,
    ArtifactStorePayloadOperationResult,
    BackendRevision,
    CompletedRunBundleMetadata,
    MaterializedRef,
    MaterializedRefKind,
)
from loom.runs.bundles import RUN_BUNDLE_MATERIALIZATION_OPERATIONS_KEY
from loom.runs import (
    LocalRunBundleExporter,
    RunBundleExportOptions,
    RunExchangeOperationStatus,
    RunExporter,
    build_portable_run_export_record,
    export_completed_run_bundle,
    inspect_run_bundle,
)


class _FakePayloadHandler:
    def __init__(self, payload: bytes, *, unsupported: bool = False) -> None:
        self.payload = payload
        self.unsupported = unsupported
        self._descriptor = ArtifactStoreBackendDescriptor(
            kind="object_store",
            display_name="Object-store fixture",
            supported_uri_schemes=("object",),
        )
        self._store_ref = ArtifactStoreRef(
            kind="object-store",
            uri="object://bucket",
            display_uri="object://redacted",
        )
        self._capabilities = ArtifactStoreCapabilities(
            backend_kind="object-store",
            records=(),
        )

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return self._descriptor

    @property
    def store_ref(self) -> ArtifactStoreRef:
        return self._store_ref

    @property
    def capabilities(self) -> ArtifactStoreCapabilities:
        return self._capabilities

    def payload_operation(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult | ArtifactStoreBackendOperationResult:
        if self.unsupported:
            return ArtifactStorePayloadOperationResult.unsupported(
                request,
                backend_kind=self.descriptor.kind,
            )
        target_uri = request.target_uri
        assert target_uri is not None
        target = uri_to_path(target_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payload)
        checksum = hash_bytes(self.payload)
        return ArtifactStorePayloadOperationResult(
            request=request,
            result=OperationResult(
                operation=f"artifact_store.{ArtifactStoreBackendOperation.MATERIALIZE.value}",
                status=OperationStatus.SUCCEEDED,
            ),
            location=ArtifactLocationSummary(
                kind=ArtifactLocationKind.MATERIALIZED,
                authority="derived",
                uri=target_uri,
                display_uri=str(target),
                store=ArtifactStoreRef(kind="local", display_uri=str(target.parent)),
                checksum=checksum,
                size_bytes=len(self.payload),
            ),
            bytes_processed=len(self.payload),
            detail={"fixture": "object-store"},
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


def _remote_metadata(*, checksum: str | None = None) -> CompletedRunBundleMetadata:
    return CompletedRunBundleMetadata(
        run_uri="file:///runs/source/run-1",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        materialized_refs=(
            MaterializedRef(
                kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
                uri="object://bucket/model.bin",
                exists=None,
                checksum=checksum,
                metadata={"artifact_id": "remote-model"},
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


def test_explicit_backend_materialization_exports_remote_payload(
    tmp_path: Path,
) -> None:
    payload = b"remote-payload"
    result = export_completed_run_bundle(
        _remote_metadata(checksum=hash_bytes(payload)),
        tmp_path / "bundle.tar",
        options=RunBundleExportOptions(
            include_payloads=True,
            materialize_payloads=True,
            verify_checksums=True,
        ),
        payload_handler=_FakePayloadHandler(payload),
    )

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.exported_payload_count == 1
    inspection = inspect_run_bundle(tmp_path / "bundle.tar", verify_checksums=True)
    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
    operations = inspection.manifest.extensions[RUN_BUNDLE_MATERIALIZATION_OPERATIONS_KEY]
    assert isinstance(operations, Sequence)
    assert not isinstance(operations, str)
    operation = operations[0]
    assert isinstance(operation, Mapping)
    result_payload = operation["result"]
    assert isinstance(result_payload, Mapping)
    assert result_payload["status"] == "succeeded"

    with tarfile.open(tmp_path / "bundle.tar", "r") as archive:
        payload_members = [
            member for member in archive.getmembers() if member.name != "manifest.json"
        ]
        assert len(payload_members) == 1
        extracted = archive.extractfile(payload_members[0])
        assert extracted is not None
        assert extracted.read() == payload


def test_explicit_backend_materialization_fails_closed_when_unsupported(
    tmp_path: Path,
) -> None:
    result = export_completed_run_bundle(
        _remote_metadata(),
        tmp_path / "bundle.tar",
        options=RunBundleExportOptions(
            include_payloads=True,
            materialize_payloads=True,
        ),
        payload_handler=_FakePayloadHandler(b"payload", unsupported=True),
    )

    assert result.status is RunExchangeOperationStatus.FAILED
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "run_bundle_export.materialization_failed"
    ]
    assert not (tmp_path / "bundle.tar").exists()


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
