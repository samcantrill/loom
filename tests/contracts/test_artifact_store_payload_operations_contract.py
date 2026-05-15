"""Contract tests for explicit artifact-store payload operations."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path

import pytest

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
)
from loom.fingerprints import hash_bytes
from loom.io.uris import path_to_file_uri, uri_to_path
from loom.operations import (
    OperationAdapterIdentity,
    OperationDiagnostic,
    OperationDiagnosticSeverity,
    OperationEvidenceCheck,
    OperationEvidenceRecord,
    OperationEvidenceStatus,
    OperationResult,
    OperationStatus,
)
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendHandler,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreBackendPayloadHandler,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
    ArtifactStorePayloadOperationRequest,
    ArtifactStorePayloadOperationResult,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.contract


class _PayloadFakeHandler:
    def __init__(
        self,
        *,
        descriptor: ArtifactStoreBackendDescriptor,
        store_ref: ArtifactStoreRef,
        storage: MutableMapping[str, bytes],
        tracking_index: Mapping[str, str] | None = None,
        read_only: bool = False,
        credentials_available: bool = True,
    ) -> None:
        self._descriptor = descriptor
        self._store_ref = store_ref
        self._storage = storage
        self._tracking_index = dict(tracking_index or {})
        self._capabilities = _capabilities(
            descriptor.kind,
            tracking=bool(tracking_index),
            read_only=read_only,
        )
        self._credentials_available = credentials_available

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return self._descriptor

    @property
    def store_ref(self) -> ArtifactStoreRef:
        return self._store_ref

    @property
    def capabilities(self) -> ArtifactStoreCapabilities:
        return self._capabilities

    def validate_store_ref(
        self,
        store_ref: ArtifactStoreRef,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        if store_ref.kind == self.descriptor.kind:
            return ()
        return (
            ArtifactStoreBackendDiagnostic(
                code="store_ref_kind_mismatch",
                message="store ref kind does not match fake payload handler",
            ),
        )

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return ArtifactStoreRef(
            kind=store_ref.kind,
            key=store_ref.key,
            uri=None,
            display_uri=store_ref.display_uri or f"{store_ref.kind}://redacted",
            details=store_ref.details,
        )

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ImmutableArtifactLookupResult | ArtifactStoreBackendOperationResult:
        del request
        return ArtifactStoreBackendOperationResult.unknown(
            ArtifactStoreBackendOperation.LOOKUP,
            message="payload fake handler does not implement lookup",
        )

    def unsupported_operation(
        self,
        operation: ArtifactStoreBackendOperation | str,
        *,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendOperationResult:
        return ArtifactStoreBackendOperationResult.unsupported(
            operation,
            message=message,
            detail=detail,
        )

    def payload_operation(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult | ArtifactStoreBackendOperationResult:
        admission = self.capabilities.require(request.operation)
        if admission is not None:
            if admission.support is ArtifactStoreCapabilitySupport.UNKNOWN:
                return ArtifactStoreBackendOperationResult.unknown(
                    request.operation,
                    message=admission.message,
                    detail=admission.detail,
                )
            return ArtifactStorePayloadOperationResult.unsupported(
                request,
                backend_kind=self.descriptor.kind,
                message=admission.message,
                detail=admission.detail,
            )
        if not self._credentials_available:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.BLOCKED,
                code="artifact_store_payload.missing_credentials",
                message="fake backend credentials are unavailable",
                details={
                    "credential": "super-secret-token",
                    "uri": "object://bucket/model.bin?token=super-secret-token",
                },
            )
        if request.operation in {
            ArtifactStoreBackendOperation.PUBLISH,
            ArtifactStoreBackendOperation.UPLOAD,
        }:
            return self._upload(request)
        if request.operation in {
            ArtifactStoreBackendOperation.MATERIALIZE,
            ArtifactStoreBackendOperation.DOWNLOAD,
        }:
            return self._download(request)
        if request.operation is ArtifactStoreBackendOperation.VERIFY_CHECKSUM:
            return self._verify_checksum(request)
        return ArtifactStoreBackendOperationResult.unknown(request.operation)

    def _upload(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult:
        if request.source_uri is None or request.target_uri is None:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.BLOCKED,
                code="artifact_store_payload.missing_upload_uri",
                message="upload requires source_uri and target_uri",
            )
        data = Path(uri_to_path(request.source_uri)).read_bytes()
        checksum = hash_bytes(data)
        if request.checksum is not None and request.checksum != checksum:
            return _checksum_mismatch(self, request, actual_checksum=checksum)
        self._storage[request.target_uri] = data
        return _success_payload_result(
            self,
            request,
            checksum=checksum,
            bytes_processed=len(data),
            location=_external_location(
                self,
                uri=request.target_uri,
                checksum=checksum,
                size_bytes=len(data),
            ),
        )

    def _download(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult:
        if request.source_uri is None or request.target_uri is None:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.BLOCKED,
                code="artifact_store_payload.missing_download_uri",
                message="download requires source_uri and target_uri",
            )
        resolved_uri = self._tracking_index.get(request.source_uri, request.source_uri)
        data = self._storage.get(resolved_uri)
        if data is None:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.FAILED,
                code="artifact_store_payload.payload_missing",
                message="fake payload storage does not contain the source URI",
                details={"resolved_uri": resolved_uri},
            )
        checksum = hash_bytes(data)
        if request.checksum is not None and request.checksum != checksum:
            return _checksum_mismatch(
                self,
                request,
                actual_checksum=checksum,
                details={"resolved_uri": resolved_uri},
            )
        target = uri_to_path(request.target_uri).resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return _success_payload_result(
            self,
            request,
            checksum=checksum,
            bytes_processed=len(data),
            location=_materialized_location(
                self,
                uri=path_to_file_uri(target),
                checksum=checksum,
                size_bytes=len(data),
            ),
            details={"resolved_uri": resolved_uri},
        )

    def _verify_checksum(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult:
        if request.source_uri is None or request.checksum is None:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.BLOCKED,
                code="artifact_store_payload.missing_checksum_input",
                message="checksum verification requires source_uri and checksum",
            )
        resolved_uri = self._tracking_index.get(request.source_uri, request.source_uri)
        data = self._storage.get(resolved_uri)
        if data is None:
            return _failed_payload_result(
                self,
                request,
                status=OperationStatus.FAILED,
                code="artifact_store_payload.payload_missing",
                message="fake payload storage does not contain the source URI",
                details={"resolved_uri": resolved_uri},
            )
        checksum = hash_bytes(data)
        if request.checksum != checksum:
            return _checksum_mismatch(
                self,
                request,
                actual_checksum=checksum,
                details={"resolved_uri": resolved_uri},
            )
        return _success_payload_result(
            self,
            request,
            checksum=checksum,
            bytes_processed=len(data),
            location=_external_location(
                self,
                uri=resolved_uri,
                checksum=checksum,
                size_bytes=len(data),
            ),
            details={"resolved_uri": resolved_uri},
        )


def test_object_store_fake_uploads_downloads_and_verifies_checksum(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    checksum = hash_bytes(source.read_bytes())
    storage: dict[str, bytes] = {}
    handler = _object_store_handler(storage=storage)

    assert isinstance(handler, ArtifactStoreBackendHandler)
    assert isinstance(handler, ArtifactStoreBackendPayloadHandler)
    assert handler.capabilities.supports(ArtifactStoreBackendOperation.UPLOAD)

    upload = handler.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.UPLOAD,
            artifact=_artifact(source),
            source_uri=path_to_file_uri(source.resolve(strict=False)),
            target_uri="object://bucket/model.bin",
            checksum=checksum,
        )
    )

    assert isinstance(upload, ArtifactStorePayloadOperationResult)
    assert upload.succeeded
    assert upload.bytes_processed == len(b"payload")
    assert upload.location is not None
    assert upload.location.kind is ArtifactLocationKind.EXTERNAL_IMMUTABLE
    assert storage["object://bucket/model.bin"] == b"payload"

    target = tmp_path / "target.bin"
    download = handler.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.DOWNLOAD,
            source_uri="object://bucket/model.bin",
            target_uri=path_to_file_uri(target.resolve(strict=False)),
            checksum=checksum,
        )
    )

    assert isinstance(download, ArtifactStorePayloadOperationResult)
    assert download.succeeded
    assert target.read_bytes() == b"payload"
    assert download.location is not None
    assert download.location.kind is ArtifactLocationKind.MATERIALIZED

    verified = handler.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.VERIFY_CHECKSUM,
            source_uri="object://bucket/model.bin",
            checksum=checksum,
        )
    )

    assert isinstance(verified, ArtifactStorePayloadOperationResult)
    assert verified.succeeded
    assert verified.result.evidence is not None
    assert verified.result.evidence.checks[0].name == "checksum_match"


def test_read_only_and_checksum_mismatch_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    storage: dict[str, bytes] = {}
    read_only = _object_store_handler(storage=storage, read_only=True)

    unsupported = read_only.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.UPLOAD,
            artifact=_artifact(source),
            source_uri=path_to_file_uri(source.resolve(strict=False)),
            target_uri="object://bucket/model.bin",
        )
    )

    assert isinstance(unsupported, ArtifactStorePayloadOperationResult)
    assert unsupported.result.status is OperationStatus.UNSUPPORTED
    assert storage == {}

    writable = _object_store_handler(storage=storage)
    mismatch = writable.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.UPLOAD,
            artifact=_artifact(source),
            source_uri=path_to_file_uri(source.resolve(strict=False)),
            target_uri="object://bucket/model.bin",
            checksum="sha256:" + "0" * 64,
        )
    )

    assert isinstance(mismatch, ArtifactStorePayloadOperationResult)
    assert mismatch.result.status is OperationStatus.FAILED
    assert mismatch.result.diagnostics[0].code == "artifact_store_payload.checksum_mismatch"
    assert storage == {}

    unknown = ArtifactStoreCapabilities(backend_kind="object-store", records=()).require(
        ArtifactStoreBackendOperation.DOWNLOAD
    )
    assert unknown is not None
    assert unknown.support is ArtifactStoreCapabilitySupport.UNKNOWN


def test_tracking_system_indirection_uses_the_same_payload_result_shape(
    tmp_path: Path,
) -> None:
    storage = {"object://bucket/model.bin": b"payload"}
    checksum = hash_bytes(b"payload")
    handler = _tracking_handler(
        storage=storage,
        tracking_index={"tracking://runs/model/latest": "object://bucket/model.bin"},
    )
    target = tmp_path / "model.bin"

    result = handler.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.MATERIALIZE,
            source_uri="tracking://runs/model/latest",
            target_uri=path_to_file_uri(target.resolve(strict=False)),
            checksum=checksum,
        )
    )

    assert isinstance(result, ArtifactStorePayloadOperationResult)
    assert result.succeeded
    assert target.read_bytes() == b"payload"
    assert result.detail["resolved_uri"] == "object://bucket/model.bin"
    assert result.location is not None
    assert result.location.authority == "derived"


def test_missing_credential_diagnostics_are_redacted(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    handler = _object_store_handler(
        storage={"object://bucket/model.bin": b"payload"},
        credentials_available=False,
    )

    result = handler.payload_operation(
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.DOWNLOAD,
            source_uri="object://bucket/model.bin",
            target_uri=path_to_file_uri(target.resolve(strict=False)),
            checksum=hash_bytes(b"payload"),
        )
    )

    assert isinstance(result, ArtifactStorePayloadOperationResult)
    assert result.result.status is OperationStatus.BLOCKED
    assert result.result.diagnostics[0].code == "artifact_store_payload.missing_credentials"
    payload = result.to_dict()
    rendered = str(payload)
    assert "super-secret-token" not in rendered
    assert "<redacted>" in rendered
    assert not target.exists()


def _object_store_handler(
    *,
    storage: MutableMapping[str, bytes],
    read_only: bool = False,
    credentials_available: bool = True,
) -> _PayloadFakeHandler:
    return _PayloadFakeHandler(
        descriptor=ArtifactStoreBackendDescriptor(
            kind="object_store",
            display_name="Object-store payload fixture",
            supported_uri_schemes=("object",),
        ),
        store_ref=ArtifactStoreRef(
            kind="object-store",
            uri="object://bucket",
            display_uri="object://redacted",
        ),
        storage=storage,
        read_only=read_only,
        credentials_available=credentials_available,
    )


def _tracking_handler(
    *,
    storage: MutableMapping[str, bytes],
    tracking_index: Mapping[str, str],
) -> _PayloadFakeHandler:
    return _PayloadFakeHandler(
        descriptor=ArtifactStoreBackendDescriptor(
            kind="tracking_system",
            display_name="Tracking-system payload fixture",
            supported_uri_schemes=("tracking",),
        ),
        store_ref=ArtifactStoreRef(
            kind="tracking-system",
            uri="tracking://runs",
            display_uri="tracking://redacted",
        ),
        storage=storage,
        tracking_index=tracking_index,
    )


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="model",
        uri=path_to_file_uri(path.resolve(strict=False)),
        artifact_type="bytes",
        checksum=hash_bytes(path.read_bytes()),
        producer_stage="stage",
    )


def _capabilities(
    backend_kind: str,
    *,
    tracking: bool,
    read_only: bool,
) -> ArtifactStoreCapabilities:
    records = [
        ArtifactStoreCapabilityRecord(
            ArtifactStoreBackendOperation.READ,
            ArtifactStoreCapabilitySupport.SUPPORTED,
        ),
        ArtifactStoreCapabilityRecord(
            ArtifactStoreBackendOperation.MATERIALIZE,
            ArtifactStoreCapabilitySupport.SUPPORTED,
        ),
        ArtifactStoreCapabilityRecord(
            ArtifactStoreBackendOperation.DOWNLOAD,
            ArtifactStoreCapabilitySupport.SUPPORTED,
        ),
        ArtifactStoreCapabilityRecord(
            ArtifactStoreBackendOperation.VERIFY_CHECKSUM,
            ArtifactStoreCapabilitySupport.SUPPORTED,
        ),
    ]
    if tracking or read_only:
        records.extend(
            (
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.PUBLISH,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="fake backend is read-only for payload publish",
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.UPLOAD,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="fake backend is read-only for payload upload",
                ),
            )
        )
    else:
        records.extend(
            (
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.PUBLISH,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.UPLOAD,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
            )
        )
    return ArtifactStoreCapabilities(backend_kind=backend_kind, records=tuple(records))


def _success_payload_result(
    handler: _PayloadFakeHandler,
    request: ArtifactStorePayloadOperationRequest,
    *,
    checksum: str,
    bytes_processed: int,
    location: ArtifactLocationSummary,
    details: Mapping[str, PlainData] | None = None,
) -> ArtifactStorePayloadOperationResult:
    return ArtifactStorePayloadOperationResult(
        request=request,
        result=OperationResult(
            operation=_operation_name(request),
            status=OperationStatus.SUCCEEDED,
            adapter=_adapter(handler),
            evidence=OperationEvidenceRecord(
                status=OperationEvidenceStatus.PROVEN,
                checks=(
                    OperationEvidenceCheck(
                        name="checksum_match",
                        status=OperationEvidenceStatus.PROVEN,
                        message="payload checksum matched expected bytes",
                        details={"checksum": checksum},
                    ),
                ),
                adapter=_adapter(handler),
                details={"bytes_processed": bytes_processed, **dict(details or {})},
            ),
            details={
                "backend_kind": handler.descriptor.kind,
                "bytes_processed": bytes_processed,
                **dict(details or {}),
            },
        ),
        location=location,
        bytes_processed=bytes_processed,
        detail={} if details is None else details,
    )


def _failed_payload_result(
    handler: _PayloadFakeHandler,
    request: ArtifactStorePayloadOperationRequest,
    *,
    status: OperationStatus,
    code: str,
    message: str,
    details: Mapping[str, PlainData] | None = None,
) -> ArtifactStorePayloadOperationResult:
    return ArtifactStorePayloadOperationResult(
        request=request,
        result=OperationResult(
            operation=_operation_name(request),
            status=status,
            adapter=_adapter(handler),
            diagnostics=(
                OperationDiagnostic(
                    code=code,
                    message=message,
                    severity=OperationDiagnosticSeverity.ERROR,
                    details={} if details is None else details,
                ),
            ),
            evidence=OperationEvidenceRecord(
                status=OperationEvidenceStatus.FAILED,
                checks=(
                    OperationEvidenceCheck(
                        name="operation_completed",
                        status=OperationEvidenceStatus.FAILED,
                        message=message,
                        details={} if details is None else details,
                    ),
                ),
                adapter=_adapter(handler),
                details={} if details is None else details,
            ),
            details={
                "backend_kind": handler.descriptor.kind,
                **dict(details or {}),
            },
        ),
    )


def _checksum_mismatch(
    handler: _PayloadFakeHandler,
    request: ArtifactStorePayloadOperationRequest,
    *,
    actual_checksum: str,
    details: Mapping[str, PlainData] | None = None,
) -> ArtifactStorePayloadOperationResult:
    return _failed_payload_result(
        handler,
        request,
        status=OperationStatus.FAILED,
        code="artifact_store_payload.checksum_mismatch",
        message="payload checksum did not match the requested checksum",
        details={
            "expected_checksum": request.checksum,
            "actual_checksum": actual_checksum,
            **dict(details or {}),
        },
    )


def _external_location(
    handler: _PayloadFakeHandler,
    *,
    uri: str,
    checksum: str,
    size_bytes: int,
) -> ArtifactLocationSummary:
    return ArtifactLocationSummary(
        kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
        authority="authoritative",
        uri=uri,
        display_uri=uri.replace("object://bucket", "object://redacted"),
        store=handler.redact_store_ref(handler.store_ref),
        checksum=checksum,
        size_bytes=size_bytes,
    )


def _materialized_location(
    handler: _PayloadFakeHandler,
    *,
    uri: str,
    checksum: str,
    size_bytes: int,
) -> ArtifactLocationSummary:
    return ArtifactLocationSummary(
        kind=ArtifactLocationKind.MATERIALIZED,
        authority="derived",
        uri=uri,
        display_uri=str(uri_to_path(uri)),
        store=handler.redact_store_ref(handler.store_ref),
        checksum=checksum,
        size_bytes=size_bytes,
    )


def _adapter(handler: _PayloadFakeHandler) -> OperationAdapterIdentity:
    return OperationAdapterIdentity(
        name=handler.descriptor.kind,
        kind="artifact-store-backend",
        version="1",
    )


def _operation_name(request: ArtifactStorePayloadOperationRequest) -> str:
    return f"artifact_store.{request.operation.value}"
