"""Project-local fake backend used by the storage contract example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import (
    ArtifactStoreRef,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
)
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendHandler,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
)
from loom.serialization import PlainData


class ExampleBackendFactory:
    """Declare one local-only fake backend without selecting a provider."""

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return ArtifactStoreBackendDescriptor(
            kind="example-backend",
            display_name="Example backend fixture",
            supported_uri_schemes=("example",),
            details={"scope": "local example fixture"},
        )

    def validate_config(
        self, config: Mapping[str, PlainData] | None = None
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del config
        return ()

    def redact_config(
        self, config: Mapping[str, PlainData] | None = None
    ) -> Mapping[str, PlainData]:
        return dict(config or {})

    def capabilities(
        self, config: Mapping[str, PlainData] | None = None
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
                    ArtifactStoreBackendOperation.MATERIALIZE,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="the fake backend does not move provider payloads",
                ),
            ),
        )

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> "ExampleBackendHandler":
        del config, run_context
        return ExampleBackendHandler(
            descriptor=self.descriptor,
            store_ref=store_ref,
            capabilities=self.capabilities(),
        )


class ExampleBackendHandler:
    """Small handler that exposes only metadata and unsupported operations."""

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
        self, store_ref: ArtifactStoreRef
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del store_ref
        return ()

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return store_ref

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self, request: ImmutableArtifactLookupRequest
    ) -> ImmutableArtifactLookupResult | ArtifactStoreBackendOperationResult:
        del request
        return self.unsupported_operation(
            ArtifactStoreBackendOperation.LOOKUP,
            message="the fake backend does not resolve external artifacts",
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


def is_backend_handler(value: object) -> bool:
    """Keep the example's protocol assertion readable at its call site."""

    return isinstance(value, ArtifactStoreBackendHandler)
