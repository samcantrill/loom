"""Unit tests for Stage 15 artifact-backend preflight checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

import loom.diagnostics.preflight as preflight
from loom.artifacts import ArtifactStoreRef, ImmutableArtifactLookupRequest
from loom.diagnostics import (
    ArtifactBackendPreflightTarget,
    PreflightCheckStatus,
    PreflightRequest,
    run_preflight,
)
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
    ArtifactStorePayloadOperationRequest,
    ArtifactStorePayloadOperationResult,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


class _FakeHandler:
    def __init__(
        self,
        *,
        write_support: ArtifactStoreCapabilitySupport = ArtifactStoreCapabilitySupport.SUPPORTED,
        materialize_support: ArtifactStoreCapabilitySupport | None = None,
    ) -> None:
        self._descriptor = ArtifactStoreBackendDescriptor(
            kind="object_store",
            display_name="Object store fixture",
            supported_uri_schemes=("s3",),
        )
        self._store_ref = ArtifactStoreRef(kind="object-store", uri="s3://secret")
        records = [
            ArtifactStoreCapabilityRecord(
                ArtifactStoreBackendOperation.READ,
                ArtifactStoreCapabilitySupport.SUPPORTED,
            ),
            ArtifactStoreCapabilityRecord(
                ArtifactStoreBackendOperation.WRITE,
                write_support,
                message="write is unavailable"
                if write_support
                is not ArtifactStoreCapabilitySupport.SUPPORTED
                else None,
            ),
        ]
        if materialize_support is not None:
            records.append(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.MATERIALIZE,
                    materialize_support,
                    message="materialization is unavailable"
                    if materialize_support
                    is not ArtifactStoreCapabilitySupport.SUPPORTED
                    else None,
                )
            )
        self._capabilities = ArtifactStoreCapabilities(
            backend_kind="object-store",
            records=tuple(records),
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

    def validate_store_ref(
        self, store_ref: ArtifactStoreRef
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del store_ref
        return ()

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return ArtifactStoreRef(
            kind=store_ref.kind,
            key=store_ref.key,
            display_uri="s3://redacted/model",
        )

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        raise AssertionError("default artifact backend preflight must not call check()")

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ArtifactStoreBackendOperationResult:
        del request
        raise AssertionError("default artifact backend preflight must not call lookup()")

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


class _PayloadFakeHandler(_FakeHandler):
    def __init__(self) -> None:
        super().__init__(
            materialize_support=ArtifactStoreCapabilitySupport.SUPPORTED,
        )

    def payload_operation(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult | ArtifactStoreBackendOperationResult:
        del request
        raise AssertionError("cheap preflight must not call payload_operation()")


def _target(
    *operations: ArtifactStoreBackendOperation,
) -> ArtifactBackendPreflightTarget:
    return ArtifactBackendPreflightTarget(
        target_id="model-output",
        store=ArtifactStoreRef(
            kind="object-store",
            uri="s3://secret-bucket/model",
            display_uri="s3://display/model",
        ),
        required_operations=tuple(operation.value for operation in operations),
    )


def test_artifact_backend_preflight_skips_without_targets_and_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider() -> tuple[object, ...]:
        raise AssertionError("artifact backend checks must not discover plugins")

    monkeypatch.setattr(preflight, "_plugin_entry_point_provider", fail_provider)

    result = run_preflight(
        PreflightRequest(config_path="missing.yaml", groups=("artifacts",))
    )

    by_id = {check.check_id: check for check in result.checks}
    assert list(by_id) == [
        "artifact_store.available",
        "artifact_backends.registry",
        "artifact_backends.handlers",
        "artifact_backends.capabilities",
        "artifact_backends.materialization",
    ]
    assert by_id["artifact_backends.registry"].status is PreflightCheckStatus.SKIP
    assert by_id["artifact_backends.handlers"].details["reason"] == (
        "no_artifact_backend_targets"
    )


def test_supplied_handler_passes_and_redacts_store_summary() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("artifacts",),
            artifact_backend_targets=(_target(ArtifactStoreBackendOperation.READ),),
            artifact_backend_handlers={"object_store": _FakeHandler()},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert by_id["artifact_backends.registry"].status is PreflightCheckStatus.PASS
    assert by_id["artifact_backends.handlers"].status is PreflightCheckStatus.PASS
    assert by_id["artifact_backends.capabilities"].status is PreflightCheckStatus.PASS

    targets = cast(list[dict[str, Any]], by_id["artifact_backends.handlers"].details["targets"])
    store = cast(dict[str, Any], targets[0]["store"])
    assert store["uri"] is None
    assert store["display_uri"] == "s3://redacted/model"


def test_required_unsupported_write_fails_closed() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("artifacts",),
            artifact_backend_targets=(_target(ArtifactStoreBackendOperation.WRITE),),
            artifact_backend_handlers={
                "object_store": _FakeHandler(
                    write_support=ArtifactStoreCapabilitySupport.UNSUPPORTED
                )
            },
        )
    )

    capability = {
        check.check_id: check for check in result.checks
    }["artifact_backends.capabilities"]
    assert capability.status is PreflightCheckStatus.FAIL
    operation_results = cast(list[dict[str, Any]], capability.details["operation_results"])
    assert operation_results[0]["support"] == "unsupported"


def test_required_materialization_needs_payload_handler_protocol() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("artifacts",),
            artifact_backend_targets=(
                _target(ArtifactStoreBackendOperation.MATERIALIZE),
            ),
            artifact_backend_handlers={
                "object_store": _FakeHandler(
                    materialize_support=ArtifactStoreCapabilitySupport.SUPPORTED
                )
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert by_id["artifact_backends.capabilities"].status is PreflightCheckStatus.PASS
    materialization = by_id["artifact_backends.materialization"]
    assert materialization.status is PreflightCheckStatus.FAIL
    diagnostics = cast(list[dict[str, Any]], materialization.details["diagnostics"])
    assert diagnostics[0]["code"] == "artifact_store_backend_payload_handler_missing"


def test_payload_materialization_readiness_is_cheap_and_passes() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("artifacts",),
            artifact_backend_targets=(
                _target(ArtifactStoreBackendOperation.MATERIALIZE),
            ),
            artifact_backend_handlers={"object_store": _PayloadFakeHandler()},
        )
    )

    materialization = {
        check.check_id: check for check in result.checks
    }["artifact_backends.materialization"]
    assert materialization.status is PreflightCheckStatus.PASS
    targets = cast(
        list[dict[str, Any]],
        materialization.details["materialization_targets"],
    )
    assert targets[0]["payload_handler_configured"] is True
    assert targets[0]["expensive_probe"] is False


def test_plugin_metadata_does_not_satisfy_backend_readiness() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("artifacts",),
            plugin_groups=("loom.artifact_store_backends",),
            artifact_backend_targets=(_target(ArtifactStoreBackendOperation.READ),),
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert by_id["artifact_backends.registry"].status is PreflightCheckStatus.FAIL
    diagnostics = cast(
        list[dict[str, Any]],
        by_id["artifact_backends.registry"].details["diagnostics"],
    )
    assert diagnostics[0]["code"] == "missing_artifact_store_backend_registry"
