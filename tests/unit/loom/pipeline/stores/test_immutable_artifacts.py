"""Unit tests for immutable artifact semantics helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from loom.artifacts import (
    ArtifactStoreRef,
    ExternalArtifactDeclaration,
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
    ImmutableArtifactSemanticsError,
    ImmutableArtifactValidationResult,
    admit_artifact_store_operation,
    artifact_ref_from_external_declaration,
    artifact_ref_from_published_record,
    evaluate_immutable_artifact_lookup,
    lookup_immutable_artifact,
    validate_external_artifact_declaration,
    validate_published_artifact_record,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit

CHECKSUM = "sha256:" + "a" * 64
FINGERPRINT = "sha256:" + "b" * 64


class _FakeHandler:
    def __init__(
        self,
        *,
        kind: str = "object_store",
        capabilities: ArtifactStoreCapabilities | None = None,
        lookup_result: ImmutableArtifactLookupResult
        | ArtifactStoreBackendOperationResult
        | None = None,
    ) -> None:
        self._descriptor = ArtifactStoreBackendDescriptor(
            kind=kind,
            display_name="Fake handler",
            supported_uri_schemes=("s3",),
        )
        self._store_ref = ArtifactStoreRef(
            kind=self._descriptor.kind, uri="s3://bucket"
        )
        self._capabilities = capabilities or ArtifactStoreCapabilities(
            backend_kind=self._descriptor.kind,
            records=(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.READ,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.LOOKUP,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
            ),
        )
        self._lookup_result = lookup_result
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
        if store_ref.kind == self.descriptor.kind:
            return ()
        return (
            ArtifactStoreBackendDiagnostic(
                code="store_ref_kind_mismatch",
                message="store ref kind mismatch",
            ),
        )

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return store_ref

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ImmutableArtifactLookupResult | ArtifactStoreBackendOperationResult:
        self.lookup_calls += 1
        return self._lookup_result or evaluate_immutable_artifact_lookup(
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


def _store_ref(kind: str = "object-store") -> ArtifactStoreRef:
    return ArtifactStoreRef(
        kind=kind,
        key="primary",
        uri="s3://bucket/model",
        display_uri="s3://bucket/model",
    )


def _external_declaration(kind: str = "object-store") -> ExternalArtifactDeclaration:
    return ExternalArtifactDeclaration(
        artifact_id="external-model",
        uri="s3://bucket/model",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        store=_store_ref(kind),
        checksum=CHECKSUM,
        fingerprint=FINGERPRINT,
        metadata={"source": "fixture"},
    )


def _published_record(
    *,
    checksum: str = CHECKSUM,
    fingerprint: str = FINGERPRINT,
    codec_key: str = "json.v1",
) -> PublishedArtifactRecord:
    return PublishedArtifactRecord(
        artifact_id="published-model",
        uri="s3://bucket/published/model",
        artifact_type="model",
        codec_key=codec_key,
        artifact_schema_version=1,
        producer_run_uri="local://run-1",
        producer_stage="train",
        producer_artifact_id="model",
        reuse_key="model:abc",
        validation_policy={"checksum": checksum},
        store=_store_ref(),
        checksum=checksum,
        fingerprint=fingerprint,
        metadata={"published": True},
    )


def _lookup_request() -> ImmutableArtifactLookupRequest:
    return ImmutableArtifactLookupRequest(
        reuse_key="model:abc",
        artifact_type="model",
        artifact_schema_version=1,
        validation_policy={
            "checksum": CHECKSUM,
            "fingerprint": FINGERPRINT,
            "codec_key": "json.v1",
        },
        store=_store_ref(),
    )


def test_metadata_only_validation_and_artifact_ref_projection() -> None:
    declaration = _external_declaration()
    external_result = validate_external_artifact_declaration(declaration)

    assert external_result.accepted
    assert external_result.diagnostics[0].code == "metadata_only_immutable_artifact"
    assert ImmutableArtifactValidationResult.from_dict(external_result.to_dict()) == (
        external_result
    )

    external_ref = artifact_ref_from_external_declaration(declaration)
    assert external_ref.artifact_id == "external-model"
    assert external_ref.uri == "s3://bucket/model"
    assert external_ref.metadata["source"] == "fixture"
    assert isinstance(external_ref.metadata["external_artifact"], Mapping)

    published = _published_record()
    published_result = validate_published_artifact_record(published)
    assert published_result.accepted

    published_ref = artifact_ref_from_published_record(published)
    assert published_ref.producer_stage == "train"
    assert published_ref.metadata["published"] is True
    assert isinstance(published_ref.metadata["published_artifact"], Mapping)


def test_handler_validation_and_admission_fail_closed() -> None:
    handler = _FakeHandler()
    accepted = validate_external_artifact_declaration(
        _external_declaration(),
        handler=handler,
    )
    assert accepted.accepted
    assert handler.lookup_calls == 0

    mismatch = validate_external_artifact_declaration(
        _external_declaration(kind="tracking-system"),
        handler=handler,
    )
    assert not mismatch.accepted
    assert {diagnostic.code for diagnostic in mismatch.diagnostics} >= {
        "store_ref_kind_mismatch",
        "artifact_store_ref_backend_mismatch",
    }

    missing_handler = admit_artifact_store_operation(
        None,
        ArtifactStoreBackendOperation.WRITE,
    )
    assert missing_handler is not None
    assert missing_handler.support is ArtifactStoreCapabilitySupport.UNKNOWN
    assert (
        missing_handler.diagnostics[0].code == "missing_artifact_store_backend_handler"
    )

    publish_result = validate_published_artifact_record(
        _published_record(),
        handler=handler,
        required_operations=(ArtifactStoreBackendOperation.PUBLISH,),
    )
    assert not publish_result.accepted
    assert publish_result.diagnostics[0].code == (
        "unknown_artifact_store_operation_support"
    )


def test_lookup_helper_is_explicit_and_maps_outcomes() -> None:
    request = _lookup_request()
    compatible = evaluate_immutable_artifact_lookup(
        request,
        published=_published_record(),
    )
    assert compatible.status == "compatible"

    incompatible = evaluate_immutable_artifact_lookup(
        request,
        published=_published_record(checksum="sha256:" + "c" * 64),
    )
    assert incompatible.status == "incompatible"
    mismatches = incompatible.diagnostics["mismatches"]
    assert isinstance(mismatches, Sequence)
    assert {str(item["field"]) for item in mismatches if isinstance(item, Mapping)} == {
        "checksum"
    }

    missing = evaluate_immutable_artifact_lookup(request)
    assert missing.status == "missing"

    handler = _FakeHandler()
    explicit = lookup_immutable_artifact(request, handler)
    assert explicit.status == "compatible"
    assert handler.lookup_calls == 1

    unsupported_handler = _FakeHandler(
        capabilities=ArtifactStoreCapabilities(
            backend_kind="object-store",
            records=(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.LOOKUP,
                    ArtifactStoreCapabilitySupport.UNSUPPORTED,
                    message="lookup disabled",
                ),
            ),
        )
    )
    unsupported = lookup_immutable_artifact(request, unsupported_handler)
    assert unsupported.status == "unsupported"
    assert unsupported_handler.lookup_calls == 0
    assert unsupported.details["support"] == "unsupported"


def test_lookup_rejects_invalid_inputs() -> None:
    with pytest.raises(ImmutableArtifactSemanticsError):
        lookup_immutable_artifact(object(), None)  # type: ignore[arg-type]
