"""Contract tests for artifact-store backend extension points."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.artifacts import ArtifactStoreRef, ImmutableArtifactLookupRequest
from loom.pipeline.stores import (
    ArtifactStore,
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendFactory,
    ArtifactStoreBackendHandler,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreBackendRegistry,
    ArtifactStoreBackendRegistryError,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.contract


class _BaseFakeHandler:
    def __init__(
        self,
        *,
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
                code="store_ref_kind_mismatch",
                message="store ref kind does not match backend descriptor",
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
            message="fake contract handler does not implement lookup in Phase 2",
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


class _FakeTrackingFactory:
    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return ArtifactStoreBackendDescriptor(
            kind="tracking_system",
            display_name="Tracking-system fixture",
            supported_uri_schemes=("runs", "tracking"),
            details={"fixture": "tracking-indirection"},
        )

    def validate_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        if config is not None and not config.get("tracking_uri"):
            return (
                ArtifactStoreBackendDiagnostic(
                    code="missing_tracking_uri",
                    message="tracking_uri is required for the fake tracking fixture",
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
                    ArtifactStoreBackendOperation.LOOKUP,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.PUBLISH,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="tracking fixture cannot publish payloads",
                ),
            ),
        )

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> _BaseFakeHandler:
        del config, run_context
        return _BaseFakeHandler(
            descriptor=self.descriptor,
            store_ref=store_ref,
            capabilities=self.capabilities(),
        )


class _FakeObjectStoreFactory:
    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return ArtifactStoreBackendDescriptor(
            kind="object_store",
            display_name="Object-store fixture",
            supported_uri_schemes=("s3", "gs"),
            details={"fixture": "object-addressed"},
        )

    def validate_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del config
        return ()

    def redact_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> Mapping[str, PlainData]:
        redacted = dict(config or {})
        if "secret_key" in redacted:
            redacted["secret_key"] = "<redacted>"
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
                    ArtifactStoreCapabilitySupport.UNKNOWN,
                    message="writes require a configured later-stage publisher",
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.MATERIALIZE,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="payload materialization is out of scope for Stage 15",
                ),
            ),
        )

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> _BaseFakeHandler:
        del config, run_context
        return _BaseFakeHandler(
            descriptor=self.descriptor,
            store_ref=store_ref,
            capabilities=self.capabilities(),
        )


def test_fake_tracking_and_object_store_factories_share_contract_shape() -> None:
    tracking = _FakeTrackingFactory()
    object_store = _FakeObjectStoreFactory()

    assert isinstance(tracking, ArtifactStoreBackendFactory)
    assert isinstance(object_store, ArtifactStoreBackendFactory)

    registry = ArtifactStoreBackendRegistry((tracking, object_store))
    assert registry.registered_kinds == ("object-store", "tracking-system")
    assert [descriptor.kind for descriptor in registry.descriptors()] == [
        "object-store",
        "tracking-system",
    ]

    tracking_ref = ArtifactStoreRef(kind="tracking-system", uri="runs:/model/1")
    object_ref = ArtifactStoreRef(kind="object-store", uri="s3://bucket/model")
    tracking_handler = registry.create_handler("tracking_system", tracking_ref)
    object_handler = registry.create_handler("object_store", object_ref)

    assert isinstance(tracking_handler, ArtifactStoreBackendHandler)
    assert isinstance(object_handler, ArtifactStoreBackendHandler)
    assert tracking_handler.capabilities.supports(ArtifactStoreBackendOperation.LOOKUP)
    assert not object_handler.capabilities.supports(
        ArtifactStoreBackendOperation.MATERIALIZE
    )


def test_contract_rejects_raw_store_instances_and_descriptor_without_factory() -> None:
    registry = ArtifactStoreBackendRegistry()

    assert not isinstance(ArtifactStore, ArtifactStoreBackendFactory)
    with pytest.raises(ArtifactStoreBackendRegistryError):
        registry.register(ArtifactStore)  # type: ignore[arg-type]

    descriptor = ArtifactStoreBackendDescriptor(
        kind="tracking_system",
        display_name="Descriptor without factory",
    )
    with pytest.raises(ArtifactStoreBackendRegistryError, match="does not include"):
        registry.register(descriptor)


def test_fake_backends_redact_config_and_return_structured_unsupported_results() -> (
    None
):
    tracking = _FakeTrackingFactory()
    object_store = _FakeObjectStoreFactory()

    assert tracking.redact_config(
        {"tracking_uri": "https://example.invalid", "token": "secret"}
    ) == {
        "tracking_uri": "https://example.invalid",
        "token": "<redacted>",
    }
    assert object_store.redact_config({"bucket": "models", "secret_key": "secret"}) == {
        "bucket": "models",
        "secret_key": "<redacted>",
    }

    publish_result = tracking.capabilities().require(
        ArtifactStoreBackendOperation.PUBLISH
    )
    assert publish_result is not None
    assert publish_result.to_dict()["support"] == "unsupported"

    write_result = object_store.capabilities().require(
        ArtifactStoreBackendOperation.WRITE
    )
    assert write_result is not None
    assert write_result.to_dict()["support"] == "unknown"

    materialize_result = ArtifactStoreBackendOperationResult.unsupported(
        ArtifactStoreBackendOperation.MATERIALIZE,
        message="payload materialization remains a future-stage operation",
    )
    assert (
        materialize_result.diagnostics[0].code == "unsupported_artifact_store_operation"
    )
