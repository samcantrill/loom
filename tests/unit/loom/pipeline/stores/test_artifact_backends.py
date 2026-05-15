"""Unit tests for artifact-store backend contracts."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ImmutableArtifactLookupRequest,
)
from loom.operations import OperationResult, OperationStatus
from loom.pipeline.stores import (
    ARTIFACT_STORE_BACKEND_CONTRACT_VERSION,
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendError,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreBackendRegistry,
    ArtifactStoreBackendRegistryError,
    ArtifactStoreBackendVersionError,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
    ArtifactStorePayloadOperationRequest,
    ArtifactStorePayloadOperationResult,
    artifact_store_backend_versions_compatible,
    normalize_artifact_store_backend_kind,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


class _FakeHandler:
    def __init__(
        self,
        descriptor: ArtifactStoreBackendDescriptor,
        store_ref: ArtifactStoreRef,
        capabilities: ArtifactStoreCapabilities,
    ) -> None:
        self._descriptor = descriptor
        self._store_ref = store_ref
        self._capabilities = capabilities

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
                code="backend_kind_mismatch",
                message="store ref kind does not match handler backend kind",
                detail={
                    "expected": self.descriptor.kind,
                    "actual": store_ref.kind,
                },
            ),
        )

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return ArtifactStoreRef(
            kind=store_ref.kind,
            key=store_ref.key,
            uri=store_ref.uri,
            display_uri=store_ref.display_uri or "<redacted>",
            details=store_ref.details,
        )

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ArtifactStoreBackendOperationResult:
        del request
        return ArtifactStoreBackendOperationResult.unknown(
            ArtifactStoreBackendOperation.LOOKUP,
            message="fake backend does not implement lookup in Phase 2",
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


class _FakeFactory:
    def __init__(
        self,
        *,
        kind: str = "Fake_Object_Store",
        contract_version: int = ARTIFACT_STORE_BACKEND_CONTRACT_VERSION,
    ) -> None:
        self._kind = kind
        self._contract_version = contract_version
        self.created_contexts: list[Mapping[str, PlainData] | None] = []

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return ArtifactStoreBackendDescriptor(
            kind=self._kind,
            display_name="Fake object store",
            contract_version=self._contract_version,
            supported_uri_schemes=("S3", "s3", "HTTPS"),
            details={"fixture": "object-store"},
        )

    def validate_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        if config is not None and config.get("endpoint") == "":
            return (
                ArtifactStoreBackendDiagnostic(
                    code="invalid_endpoint",
                    message="endpoint must not be empty",
                ),
            )
        return ()

    def redact_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> Mapping[str, PlainData]:
        redacted = dict(config or {})
        if "token" in redacted:
            redacted["token"] = "<redacted>"
        return redacted

    def capabilities(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreCapabilities:
        del config
        return ArtifactStoreCapabilities(
            backend_kind=self.descriptor.kind,
            records=(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.READ,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.WRITE,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="fake object store writes are out of scope",
                ),
            ),
        )

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> _FakeHandler:
        del config
        self.created_contexts.append(run_context)
        return _FakeHandler(
            descriptor=self.descriptor,
            store_ref=store_ref,
            capabilities=self.capabilities(),
        )


def test_descriptor_normalizes_and_serializes_without_factory() -> None:
    factory = _FakeFactory(kind="Fake_Object_Store")
    descriptor = ArtifactStoreBackendDescriptor(
        kind="Fake_Object_Store",
        display_name="Fake object store",
        supported_uri_schemes=("S3", "s3", "HTTPS"),
        details={"safe": ["metadata"]},
        factory=factory,
    )

    assert descriptor.kind == "fake-object-store"
    assert descriptor.backend_key == "fake-object-store"
    assert descriptor.supported_uri_schemes == ("https", "s3")
    assert descriptor.factory is factory

    summary = descriptor.to_dict()
    assert summary == {
        "kind": "fake-object-store",
        "display_name": "Fake object store",
        "contract_version": 1,
        "api_version": "1",
        "supported_uri_schemes": ["https", "s3"],
        "backend_key": "fake-object-store",
        "details": {"safe": ["metadata"]},
    }
    assert "factory" not in summary
    assert ArtifactStoreBackendDescriptor.from_dict(summary).factory is None


def test_capabilities_fail_closed_for_unsupported_and_unknown_operations() -> None:
    capabilities = ArtifactStoreCapabilities(
        backend_kind="tracking_system",
        records=(
            ArtifactStoreCapabilityRecord(
                operation=ArtifactStoreBackendOperation.READ,
                support=ArtifactStoreCapabilitySupport.SUPPORTED,
            ),
            ArtifactStoreCapabilityRecord(
                operation=ArtifactStoreBackendOperation.PUBLISH,
                support=ArtifactStoreCapabilitySupport.UNSUPPORTED,
                message="tracking fixture cannot publish payloads",
            ),
        ),
    )

    assert capabilities.backend_kind == "tracking-system"
    assert capabilities.supports("read")
    assert capabilities.require(ArtifactStoreBackendOperation.READ) is None

    unsupported = capabilities.require(ArtifactStoreBackendOperation.PUBLISH)
    assert unsupported is not None
    assert unsupported.support is ArtifactStoreCapabilitySupport.UNSUPPORTED
    assert unsupported.diagnostics[0].code == "unsupported_artifact_store_operation"

    unknown = capabilities.require(ArtifactStoreBackendOperation.MATERIALIZE)
    assert unknown is not None
    assert unknown.support is ArtifactStoreCapabilitySupport.UNKNOWN
    assert unknown.diagnostics[0].code == "unknown_artifact_store_operation_support"

    round_trip = ArtifactStoreCapabilities.from_dict(capabilities.to_dict())
    assert round_trip == capabilities


def test_payload_operation_request_is_strict_and_limited_to_payload_ops() -> None:
    artifact = ArtifactRef(
        artifact_id="model",
        uri="file:///tmp/source.bin",
        artifact_type="bytes",
        checksum="sha256:" + "1" * 64,
    )
    request = ArtifactStorePayloadOperationRequest(
        operation=ArtifactStoreBackendOperation.UPLOAD,
        artifact=artifact,
        source_uri="file:///tmp/source.bin",
        target_uri="object://bucket/model.bin",
        checksum="sha256:" + "1" * 64,
        detail={"caller": "unit"},
    )

    payload = request.to_dict()

    assert payload["operation"] == "upload"
    assert payload["artifact"] == artifact.to_dict()
    assert ArtifactStorePayloadOperationRequest.from_dict(payload) == request

    with pytest.raises(ArtifactStoreBackendError, match="payload"):
        ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.READ,
        )

    with pytest.raises(ArtifactStoreBackendError):
        ArtifactStorePayloadOperationRequest.from_dict({**payload, "extra": True})


def test_payload_operation_result_uses_shared_operation_result() -> None:
    request = ArtifactStorePayloadOperationRequest(
        operation=ArtifactStoreBackendOperation.DOWNLOAD,
        source_uri="object://bucket/model.bin",
        target_uri="file:///tmp/model.bin",
        checksum="sha256:" + "2" * 64,
    )
    location = ArtifactLocationSummary(
        kind=ArtifactLocationKind.MATERIALIZED,
        authority="derived",
        uri="file:///tmp/model.bin",
        display_uri="/tmp/model.bin",
        checksum="sha256:" + "2" * 64,
        size_bytes=7,
    )
    result = ArtifactStorePayloadOperationResult(
        request=request,
        result=OperationResult(
            operation="artifact_store.download",
            status=OperationStatus.SUCCEEDED,
        ),
        location=location,
        bytes_processed=7,
        detail={"fixture": "unit"},
    )

    payload = result.to_dict()

    assert result.succeeded
    assert payload["bytes_processed"] == 7
    assert payload["location"] == location.to_dict()
    assert ArtifactStorePayloadOperationResult.from_dict(payload) == result

    unsupported = ArtifactStorePayloadOperationResult.unsupported(
        request,
        backend_kind="Object_Store",
    )
    assert unsupported.result.status is OperationStatus.UNSUPPORTED
    assert unsupported.result.adapter is not None
    assert unsupported.result.adapter.name == "object-store"

    missing = ArtifactStorePayloadOperationResult.not_implemented(
        request,
        backend_kind="Object_Store",
    )
    assert missing.result.status is OperationStatus.NOT_IMPLEMENTED

    with pytest.raises(ArtifactStoreBackendError):
        ArtifactStorePayloadOperationResult.from_dict({**payload, "extra": True})


def test_registry_reports_duplicate_missing_and_version_diagnostics() -> None:
    registry = ArtifactStoreBackendRegistry()
    descriptor = registry.register(_FakeFactory())

    assert descriptor.kind == "fake-object-store"
    assert registry.registered_kinds == ("fake-object-store",)
    assert registry.get("Fake_Object_Store").descriptor.kind == "fake-object-store"

    with pytest.raises(ArtifactStoreBackendRegistryError) as duplicate:
        registry.register(_FakeFactory(kind="fake-object-store"))
    assert duplicate.value.diagnostic is not None
    assert duplicate.value.diagnostic.code == "duplicate_artifact_store_backend_kind"

    with pytest.raises(ArtifactStoreBackendRegistryError) as missing:
        registry.get("missing_backend")
    assert missing.value.diagnostic is not None
    assert missing.value.diagnostic.to_dict()["detail"] == {
        "backend_kind": "missing-backend"
    }

    with pytest.raises(ArtifactStoreBackendVersionError) as incompatible:
        registry.register(_FakeFactory(kind="future_backend", contract_version=99))
    assert incompatible.value.diagnostic is not None
    assert (
        incompatible.value.diagnostic.code
        == "incompatible_artifact_store_backend_contract_version"
    )


def test_registry_accepts_descriptor_with_factory_and_creates_handler() -> None:
    factory = _FakeFactory(kind="tracking_system")
    descriptor = ArtifactStoreBackendDescriptor(
        kind="tracking_system",
        display_name="Tracking fixture",
        supported_uri_schemes=("runs", "mlflow"),
        factory=factory,
    )
    registry = ArtifactStoreBackendRegistry((descriptor,))
    store_ref = ArtifactStoreRef(
        kind="tracking-system",
        key="primary",
        uri="runs:/model/1",
        display_uri="runs:/model/1",
    )

    handler = registry.create_handler(
        "tracking_system",
        store_ref,
        config={"token": "secret"},
        run_context={"run_uri": "local://run-1"},
    )

    assert handler.descriptor.kind == "tracking-system"
    assert handler.store_ref is store_ref
    assert factory.created_contexts == [{"run_uri": "local://run-1"}]
    assert handler.check() == ()
    assert handler.validate_store_ref(store_ref) == ()

    result = handler.unsupported_operation(
        ArtifactStoreBackendOperation.MATERIALIZE,
        message="payload movement is out of scope",
    )
    assert result.to_dict()["support"] == "unsupported"


def test_helpers_validate_backend_kind_and_contract_version() -> None:
    assert normalize_artifact_store_backend_kind("Object_Store") == "object-store"
    assert artifact_store_backend_versions_compatible(1)
    assert not artifact_store_backend_versions_compatible(2)
    with pytest.raises(ArtifactStoreBackendError, match="kind"):
        normalize_artifact_store_backend_kind("not allowed!")
