"""Contract tests for explicit immutable artifact semantics."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.artifacts import (
    ArtifactStoreRef,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
    PublishedArtifactRecord,
)
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
    admit_artifact_store_operation,
    evaluate_immutable_artifact_lookup,
    lookup_immutable_artifact,
    validate_published_artifact_record,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.contract

CHECKSUM = "sha256:" + "1" * 64
FINGERPRINT = "sha256:" + "2" * 64


class _LookupHandler:
    def __init__(self, support: ArtifactStoreCapabilitySupport) -> None:
        self._descriptor = ArtifactStoreBackendDescriptor(
            kind="tracking_system",
            display_name="Tracking lookup fixture",
            supported_uri_schemes=("runs",),
        )
        self._store_ref = ArtifactStoreRef(kind="tracking-system", uri="runs:/model/1")
        self._capabilities = ArtifactStoreCapabilities(
            backend_kind="tracking-system",
            records=(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.LOOKUP,
                    support,
                    message=None
                    if support is ArtifactStoreCapabilitySupport.SUPPORTED
                    else "lookup is not available",
                ),
            ),
        )
        self.lookup_calls = 0

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
        del store_ref
        return ()

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return store_ref

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ImmutableArtifactLookupResult:
        self.lookup_calls += 1
        return evaluate_immutable_artifact_lookup(
            request,
            published=_published_record(),
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


def _published_record() -> PublishedArtifactRecord:
    return PublishedArtifactRecord(
        artifact_id="published-model",
        uri="runs:/model/1",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        producer_run_uri="local://run-1",
        producer_stage="train",
        producer_artifact_id="model",
        reuse_key="model:abc",
        validation_policy={"checksum": CHECKSUM, "fingerprint": FINGERPRINT},
        store=ArtifactStoreRef(kind="tracking-system", uri="runs:/model/1"),
        checksum=CHECKSUM,
        fingerprint=FINGERPRINT,
    )


def _lookup_request(reuse_key: str = "model:abc") -> ImmutableArtifactLookupRequest:
    return ImmutableArtifactLookupRequest(
        reuse_key=reuse_key,
        artifact_type="model",
        artifact_schema_version=1,
        validation_policy={"checksum": CHECKSUM, "fingerprint": FINGERPRINT},
        store=ArtifactStoreRef(kind="tracking-system", uri="runs:/model/1"),
    )


def test_explicit_lookup_contract_covers_compatible_incompatible_and_missing() -> None:
    request = _lookup_request()

    compatible = evaluate_immutable_artifact_lookup(
        request,
        published=_published_record(),
    )
    assert compatible.status == "compatible"
    assert compatible.published is not None

    incompatible = evaluate_immutable_artifact_lookup(
        _lookup_request(reuse_key="different"),
        published=_published_record(),
    )
    assert incompatible.status == "incompatible"
    assert incompatible.diagnostics["code"] == "immutable_artifact_incompatible"

    missing = evaluate_immutable_artifact_lookup(request, published=None)
    assert missing.status == "missing"
    assert missing.published is None


def test_selected_operations_fail_closed_without_supported_capability() -> None:
    missing_backend = admit_artifact_store_operation(
        None,
        ArtifactStoreBackendOperation.PUBLISH,
    )
    assert missing_backend is not None
    assert missing_backend.support is ArtifactStoreCapabilitySupport.UNKNOWN

    capabilities = ArtifactStoreCapabilities(
        backend_kind="tracking-system",
        records=(
            ArtifactStoreCapabilityRecord(
                ArtifactStoreBackendOperation.PUBLISH,
                ArtifactStoreCapabilitySupport.UNSUPPORTED,
                message="publish is out of scope",
            ),
        ),
    )
    unsupported = admit_artifact_store_operation(
        capabilities,
        ArtifactStoreBackendOperation.PUBLISH,
    )
    assert unsupported is not None
    assert unsupported.support is ArtifactStoreCapabilitySupport.UNSUPPORTED


def test_validation_does_not_run_lookup_and_lookup_stays_explicit() -> None:
    handler = _LookupHandler(ArtifactStoreCapabilitySupport.SUPPORTED)
    validation = validate_published_artifact_record(
        _published_record(),
        handler=handler,
        required_operations=(ArtifactStoreBackendOperation.LOOKUP,),
    )

    assert validation.accepted
    assert handler.lookup_calls == 0

    lookup = lookup_immutable_artifact(_lookup_request(), handler)
    assert lookup.status == "compatible"
    assert handler.lookup_calls == 1


def test_unsupported_lookup_returns_lookup_result_without_calling_handler() -> None:
    handler = _LookupHandler(ArtifactStoreCapabilitySupport.UNSUPPORTED)

    lookup = lookup_immutable_artifact(_lookup_request(), handler)

    assert lookup.status == "unsupported"
    assert handler.lookup_calls == 0
    assert lookup.details["support"] == "unsupported"
