"""Contract tests for artifact-store backend extension points."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ExternalArtifactDeclaration,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
    PublishedArtifactRecord,
)
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
    ArtifactFactRecord,
    BackendRevision,
    admit_artifact_store_operations,
    artifact_ref_from_external_declaration,
    lookup_immutable_artifact,
)
from loom.runs import (
    EXTERNAL_ARTIFACT_METADATA_KEY,
    RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY,
    UNSUPPORTED_MATERIALIZATION_METADATA_KEY,
    collect_run_exchange_artifact_summaries,
    unsupported_materialization_summary,
)
from loom.serialization import PlainData, thaw_plain_data


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
            uri=None,
            display_uri=store_ref.display_uri or "<redacted>",
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


class _TrackingSystemHandler(_BaseFakeHandler):
    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ImmutableArtifactLookupResult:
        checksum = cast(str | None, request.validation_policy.get("checksum"))
        location = ArtifactLocationSummary(
            kind=ArtifactLocationKind.PUBLISHED_IMMUTABLE,
            authority="authoritative",
            uri="runs:/registered/model/latest",
            display_uri="runs:/registered/model/latest",
            store=ArtifactStoreRef(
                kind=self.store_ref.kind,
                display_uri=self.store_ref.display_uri or "tracking://redacted",
            ),
            checksum=checksum,
            details={"source": "fake-tracking-system"},
        )
        published = PublishedArtifactRecord(
            artifact_id="published-model",
            uri="runs:/registered/model/latest",
            artifact_type=request.artifact_type,
            codec_key="json.v1",
            artifact_schema_version=request.artifact_schema_version,
            producer_run_uri="file:///runs/source/run-1",
            producer_stage="train",
            producer_artifact_id="model",
            reuse_key=request.reuse_key,
            validation_policy=request.validation_policy,
            store=location.store,
            location=location,
            checksum=checksum,
            metadata={"fixture": "tracking-system"},
        )
        return ImmutableArtifactLookupResult(
            status="compatible",
            request=request,
            published=published,
            location=location,
            details={"handler": "tracking-system-fixture"},
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
    ) -> _TrackingSystemHandler:
        del config, run_context
        return _TrackingSystemHandler(
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


def test_fake_backends_demonstrate_lookup_capability_and_run_exchange_metadata() -> (
    None
):
    registry = ArtifactStoreBackendRegistry(
        (_FakeTrackingFactory(), _FakeObjectStoreFactory())
    )
    tracking_ref = ArtifactStoreRef(
        kind="tracking-system",
        uri="tracking://private.example/runs/model",
        display_uri="tracking://redacted/runs/model",
    )
    object_ref = ArtifactStoreRef(
        kind="object-store",
        uri="s3://secret-bucket/models/champion.json",
        display_uri="s3://redacted/models/champion.json",
    )
    tracking_handler = registry.create_handler("tracking-system", tracking_ref)
    object_handler = registry.create_handler("object-store", object_ref)

    assert admit_artifact_store_operations(
        tracking_handler,
        (ArtifactStoreBackendOperation.READ, ArtifactStoreBackendOperation.LOOKUP),
    ) == ()

    publish_admission = admit_artifact_store_operations(
        tracking_handler,
        (ArtifactStoreBackendOperation.PUBLISH,),
    )
    assert publish_admission[0].support is ArtifactStoreCapabilitySupport.UNSUPPORTED

    materialize_result = object_handler.unsupported_operation(
        ArtifactStoreBackendOperation.MATERIALIZE,
        message="object-store fixture only preserves metadata in Stage 15",
    )
    assert materialize_result.to_dict()["support"] == "unsupported"

    request = ImmutableArtifactLookupRequest(
        reuse_key="model:champion",
        artifact_type="model",
        artifact_schema_version=1,
        validation_policy={"checksum": "sha256:" + "4" * 64},
        store=tracking_ref,
    )
    lookup = lookup_immutable_artifact(request, tracking_handler)
    assert lookup.status == "compatible"
    assert lookup.published is not None
    assert lookup.location is not None
    assert lookup.location.store is not None
    assert lookup.location.store.display_uri == "tracking://redacted/runs/model"

    declaration = ExternalArtifactDeclaration(
        artifact_id="external-model",
        uri="s3://secret-bucket/models/champion.json",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        store=object_handler.redact_store_ref(object_ref),
        location=ArtifactLocationSummary(
            kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
            authority="authoritative",
            display_uri="s3://redacted/models/champion.json",
            store=object_handler.redact_store_ref(object_ref),
            checksum="sha256:" + "5" * 64,
            details={"adapter_shape": "object-store"},
        ),
        checksum="sha256:" + "5" * 64,
        metadata={"fixture": "object-store"},
    )
    artifact = artifact_ref_from_external_declaration(declaration)
    artifact = ArtifactRef(
        **{
            **artifact.to_dict(),
            "metadata": {
                **cast(dict[str, PlainData], thaw_plain_data(artifact.metadata)),
                UNSUPPORTED_MATERIALIZATION_METADATA_KEY: unsupported_materialization_summary(
                    "object-store payload materialization is deferred to Stage 16",
                    location=declaration.location,
                ),
            },
        }
    )
    summary = collect_run_exchange_artifact_summaries(
        (
            ArtifactFactRecord(
                artifact_name="model",
                artifact=artifact,
                commit_id="commit-1",
                revision=BackendRevision(sequence=1, token="rev-1"),
            ),
        )
    )

    assert summary["schema_version"] == 1
    preserved = cast(list[dict[str, Any]], summary["artifacts"])[0]
    summaries = cast(dict[str, Any], preserved["summaries"])
    external = cast(dict[str, Any], summaries[EXTERNAL_ARTIFACT_METADATA_KEY])
    assert external["store"]["uri"] is None
    assert external["store"]["display_uri"] == "s3://redacted/models/champion.json"
    assert UNSUPPORTED_MATERIALIZATION_METADATA_KEY in summaries
    assert RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY == "stage_15_artifact_summaries"


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
