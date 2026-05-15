"""Metadata-only immutable artifact semantics over backend contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.artifacts import (
    ArtifactRef,
    ArtifactStoreRef,
    ExternalArtifactDeclaration,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
    PublishedArtifactRecord,
)
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    thaw_plain_data,
)

from .artifact_backends import (
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendDiagnosticSeverity,
    ArtifactStoreBackendError,
    ArtifactStoreBackendHandler,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilitySupport,
    normalize_artifact_store_backend_kind,
)


class ImmutableArtifactSemanticsError(ValueError):
    """Raised when immutable artifact helper inputs are invalid."""


class ImmutableArtifactValidationTarget(StrEnum):
    """Validation target labels for immutable artifact helper results."""

    EXTERNAL_DECLARATION = "external_declaration"
    PUBLISHED_RECORD = "published_record"


@dataclass(frozen=True, slots=True)
class ImmutableArtifactValidationResult:
    """Plain validation result for metadata-only immutable artifact checks."""

    target: ImmutableArtifactValidationTarget
    accepted: bool
    diagnostics: tuple[ArtifactStoreBackendDiagnostic, ...] = ()
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _coerce_target(self.target, "target"))
        if not isinstance(self.accepted, bool):
            raise ImmutableArtifactSemanticsError("accepted must be a bool")
        diagnostics = tuple(self.diagnostics)
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, ArtifactStoreBackendDiagnostic):
                raise ImmutableArtifactSemanticsError(
                    "diagnostics must contain ArtifactStoreBackendDiagnostic values"
                )
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "target": self.target.value,
            "accepted": self.accepted,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ImmutableArtifactValidationResult:
        mapping = _mapping(data, "ImmutableArtifactValidationResult")
        _reject_unknown(
            mapping,
            {"target", "accepted", "diagnostics", "detail"},
            "ImmutableArtifactValidationResult",
        )
        diagnostics_data = _sequence(mapping.get("diagnostics", ()), "diagnostics")
        accepted = _required(mapping, "accepted")
        if not isinstance(accepted, bool):
            raise ImmutableArtifactSemanticsError("accepted must be a bool")
        return cls(
            target=_coerce_target(_required(mapping, "target"), "target"),
            accepted=accepted,
            diagnostics=tuple(
                ArtifactStoreBackendDiagnostic.from_dict(diagnostic)
                for diagnostic in diagnostics_data
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


def validate_external_artifact_declaration(
    declaration: ExternalArtifactDeclaration,
    *,
    handler: ArtifactStoreBackendHandler | None = None,
    required_operations: Iterable[ArtifactStoreBackendOperation | str] = (
        ArtifactStoreBackendOperation.READ,
    ),
) -> ImmutableArtifactValidationResult:
    """Validate an external immutable declaration without moving payloads."""

    if not isinstance(declaration, ExternalArtifactDeclaration):
        raise ImmutableArtifactSemanticsError(
            "declaration must be an ExternalArtifactDeclaration"
        )

    diagnostics: list[ArtifactStoreBackendDiagnostic] = []
    if handler is None:
        diagnostics.append(_metadata_only_diagnostic("external declaration"))
    else:
        diagnostics.extend(
            _store_ref_diagnostics(
                declaration.store,
                handler=handler,
                field="declaration.store",
            )
        )
        diagnostics.extend(
            _operation_diagnostics(
                admit_artifact_store_operations(handler, required_operations)
            )
        )

    return ImmutableArtifactValidationResult(
        target=ImmutableArtifactValidationTarget.EXTERNAL_DECLARATION,
        accepted=_accepted(diagnostics),
        diagnostics=tuple(diagnostics),
        detail={
            "artifact_id": declaration.artifact_id,
            "metadata_only": handler is None,
        },
    )


def validate_published_artifact_record(
    record: PublishedArtifactRecord,
    *,
    handler: ArtifactStoreBackendHandler | None = None,
    required_operations: Iterable[ArtifactStoreBackendOperation | str] = (),
) -> ImmutableArtifactValidationResult:
    """Validate a published immutable record without moving payloads."""

    if not isinstance(record, PublishedArtifactRecord):
        raise ImmutableArtifactSemanticsError(
            "record must be a PublishedArtifactRecord"
        )

    diagnostics: list[ArtifactStoreBackendDiagnostic] = []
    if handler is None:
        diagnostics.append(_metadata_only_diagnostic("published record"))
    else:
        diagnostics.extend(
            _store_ref_diagnostics(
                record.store,
                handler=handler,
                field="record.store",
            )
        )
        diagnostics.extend(
            _operation_diagnostics(
                admit_artifact_store_operations(handler, required_operations)
            )
        )

    return ImmutableArtifactValidationResult(
        target=ImmutableArtifactValidationTarget.PUBLISHED_RECORD,
        accepted=_accepted(diagnostics),
        diagnostics=tuple(diagnostics),
        detail={
            "artifact_id": record.artifact_id,
            "reuse_key": record.reuse_key,
            "metadata_only": handler is None,
        },
    )


def admit_artifact_store_operation(
    source: ArtifactStoreBackendHandler | ArtifactStoreCapabilities | None,
    operation: ArtifactStoreBackendOperation | str,
) -> ArtifactStoreBackendOperationResult | None:
    """Return fail-closed admission result for a selected backend operation."""

    wanted = _coerce_operation(operation)
    if source is None:
        message = (
            f"artifact-store operation {wanted.value!r} requires a configured "
            "backend handler"
        )
        return ArtifactStoreBackendOperationResult(
            operation=wanted,
            support=ArtifactStoreCapabilitySupport.UNKNOWN,
            message=message,
            diagnostics=(
                ArtifactStoreBackendDiagnostic(
                    code="missing_artifact_store_backend_handler",
                    message=message,
                    detail={"operation": wanted.value},
                ),
            ),
        )
    if isinstance(source, ArtifactStoreCapabilities):
        return source.require(wanted)
    if isinstance(source, ArtifactStoreBackendHandler):
        return source.capabilities.require(wanted)
    raise ImmutableArtifactSemanticsError(
        "source must be an ArtifactStoreBackendHandler, ArtifactStoreCapabilities, or None"
    )


def admit_artifact_store_operations(
    source: ArtifactStoreBackendHandler | ArtifactStoreCapabilities | None,
    operations: Iterable[ArtifactStoreBackendOperation | str],
) -> tuple[ArtifactStoreBackendOperationResult, ...]:
    """Return all fail-closed admission results for selected operations."""

    results: list[ArtifactStoreBackendOperationResult] = []
    for operation in operations:
        result = admit_artifact_store_operation(source, operation)
        if result is not None:
            results.append(result)
    return tuple(results)


def lookup_immutable_artifact(
    request: ImmutableArtifactLookupRequest,
    handler: ArtifactStoreBackendHandler | None,
) -> ImmutableArtifactLookupResult:
    """Run an explicit immutable lookup through a handler when supported."""

    if not isinstance(request, ImmutableArtifactLookupRequest):
        raise ImmutableArtifactSemanticsError(
            "request must be an ImmutableArtifactLookupRequest"
        )

    admission = admit_artifact_store_operation(
        handler,
        ArtifactStoreBackendOperation.LOOKUP,
    )
    if admission is not None:
        return _lookup_result_from_operation_result(request, admission)
    if handler is None:
        raise ImmutableArtifactSemanticsError("handler unexpectedly missing")

    result = handler.lookup(request)
    if isinstance(result, ImmutableArtifactLookupResult):
        return result
    if isinstance(result, ArtifactStoreBackendOperationResult):
        return _lookup_result_from_operation_result(request, result)
    raise ImmutableArtifactSemanticsError(
        "handler lookup must return ImmutableArtifactLookupResult or "
        "ArtifactStoreBackendOperationResult"
    )


def evaluate_immutable_artifact_lookup(
    request: ImmutableArtifactLookupRequest,
    *,
    published: PublishedArtifactRecord | None = None,
) -> ImmutableArtifactLookupResult:
    """Evaluate a lookup request against an optional published record."""

    if not isinstance(request, ImmutableArtifactLookupRequest):
        raise ImmutableArtifactSemanticsError(
            "request must be an ImmutableArtifactLookupRequest"
        )
    if published is None:
        return ImmutableArtifactLookupResult(
            status="missing",
            request=request,
            diagnostics={
                "code": "immutable_artifact_missing",
                "message": f"no published artifact for reuse key {request.reuse_key!r}",
            },
        )
    if not isinstance(published, PublishedArtifactRecord):
        raise ImmutableArtifactSemanticsError(
            "published must be a PublishedArtifactRecord or None"
        )

    mismatches = _published_request_mismatches(request, published)
    if mismatches:
        return ImmutableArtifactLookupResult(
            status="incompatible",
            request=request,
            published=published,
            location=published.location,
            diagnostics={
                "code": "immutable_artifact_incompatible",
                "message": "published artifact does not satisfy lookup request",
                "mismatches": mismatches,
            },
        )
    return ImmutableArtifactLookupResult(
        status="compatible",
        request=request,
        published=published,
        location=published.location,
    )


def artifact_ref_from_external_declaration(
    declaration: ExternalArtifactDeclaration,
) -> ArtifactRef:
    """Project an external declaration to a legacy-compatible artifact ref."""

    if not isinstance(declaration, ExternalArtifactDeclaration):
        raise ImmutableArtifactSemanticsError(
            "declaration must be an ExternalArtifactDeclaration"
        )
    metadata = _plain_dict(declaration.metadata, "metadata")
    metadata.setdefault(
        "external_artifact",
        _plain_value(declaration.to_summary(), "external_artifact"),
    )
    return ArtifactRef(
        artifact_id=declaration.artifact_id,
        uri=declaration.uri,
        artifact_type=declaration.artifact_type,
        codec_key=declaration.codec_key,
        schema_version=declaration.artifact_schema_version,
        checksum=declaration.checksum,
        fingerprint=declaration.fingerprint,
        metadata=metadata,
    )


def artifact_ref_from_published_record(record: PublishedArtifactRecord) -> ArtifactRef:
    """Project a published record to a legacy-compatible artifact ref."""

    if not isinstance(record, PublishedArtifactRecord):
        raise ImmutableArtifactSemanticsError(
            "record must be a PublishedArtifactRecord"
        )
    metadata = _plain_dict(record.metadata, "metadata")
    metadata.setdefault(
        "published_artifact",
        _plain_value(record.to_summary(), "published_artifact"),
    )
    return ArtifactRef(
        artifact_id=record.artifact_id,
        uri=record.uri,
        artifact_type=record.artifact_type,
        codec_key=record.codec_key,
        schema_version=record.artifact_schema_version,
        checksum=record.checksum,
        fingerprint=record.fingerprint,
        producer_stage=record.producer_stage,
        metadata=metadata,
    )


def _store_ref_diagnostics(
    store_ref: ArtifactStoreRef | None,
    *,
    handler: ArtifactStoreBackendHandler,
    field: str,
) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
    if store_ref is None:
        return ()
    diagnostics = list(handler.validate_store_ref(store_ref))
    try:
        actual_kind = normalize_artifact_store_backend_kind(store_ref.kind, field=field)
    except ArtifactStoreBackendError as exc:
        diagnostics.append(
            ArtifactStoreBackendDiagnostic(
                code="invalid_artifact_store_ref_kind",
                message=str(exc),
                detail={"field": field},
            )
        )
        return tuple(diagnostics)
    expected_kind = handler.descriptor.kind
    if actual_kind != expected_kind:
        diagnostics.append(
            ArtifactStoreBackendDiagnostic(
                code="artifact_store_ref_backend_mismatch",
                message=(
                    f"{field} uses backend kind {actual_kind!r}, but handler "
                    f"uses {expected_kind!r}"
                ),
                detail={
                    "field": field,
                    "expected_backend_kind": expected_kind,
                    "actual_backend_kind": actual_kind,
                },
            )
        )
    return tuple(diagnostics)


def _operation_diagnostics(
    results: Iterable[ArtifactStoreBackendOperationResult],
) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
    diagnostics: list[ArtifactStoreBackendDiagnostic] = []
    for result in results:
        diagnostics.extend(result.diagnostics)
    return tuple(diagnostics)


def _metadata_only_diagnostic(label: str) -> ArtifactStoreBackendDiagnostic:
    return ArtifactStoreBackendDiagnostic(
        code="metadata_only_immutable_artifact",
        message=f"{label} validated as metadata only; no backend handler consulted",
        severity=ArtifactStoreBackendDiagnosticSeverity.INFO,
        detail={"metadata_only": True},
    )


def _lookup_result_from_operation_result(
    request: ImmutableArtifactLookupRequest,
    result: ArtifactStoreBackendOperationResult,
) -> ImmutableArtifactLookupResult:
    return ImmutableArtifactLookupResult(
        status="unsupported",
        request=request,
        diagnostics={
            "operation_result": result.to_dict(),
        },
        details={
            "operation": result.operation.value,
            "support": result.support.value,
        },
    )


def _published_request_mismatches(
    request: ImmutableArtifactLookupRequest,
    published: PublishedArtifactRecord,
) -> list[PlainData]:
    mismatches: list[PlainData] = []
    _append_mismatch(
        mismatches,
        field="reuse_key",
        expected=request.reuse_key,
        actual=published.reuse_key,
    )
    _append_mismatch(
        mismatches,
        field="artifact_type",
        expected=request.artifact_type,
        actual=published.artifact_type,
    )
    _append_mismatch(
        mismatches,
        field="artifact_schema_version",
        expected=request.artifact_schema_version,
        actual=published.artifact_schema_version,
    )
    policy = request.validation_policy
    for policy_field, actual in (
        ("checksum", published.checksum),
        ("fingerprint", published.fingerprint),
        ("codec_key", published.codec_key),
    ):
        if policy_field in policy:
            _append_mismatch(
                mismatches,
                field=policy_field,
                expected=policy[policy_field],
                actual=actual,
            )
    return mismatches


def _append_mismatch(
    mismatches: list[PlainData],
    *,
    field: str,
    expected: PlainData,
    actual: PlainData,
) -> None:
    if expected == actual:
        return
    mismatches.append({"field": field, "expected": expected, "actual": actual})


def _accepted(diagnostics: Iterable[ArtifactStoreBackendDiagnostic]) -> bool:
    return all(
        diagnostic.severity is not ArtifactStoreBackendDiagnosticSeverity.ERROR
        for diagnostic in diagnostics
    )


def _coerce_operation(
    operation: ArtifactStoreBackendOperation | str,
) -> ArtifactStoreBackendOperation:
    if isinstance(operation, ArtifactStoreBackendOperation):
        return operation
    if isinstance(operation, str):
        try:
            return ArtifactStoreBackendOperation(operation)
        except ValueError as exc:
            raise ImmutableArtifactSemanticsError(
                f"operation must be one of: {', '.join(_operation_values())}"
            ) from exc
    raise ImmutableArtifactSemanticsError(
        f"operation must be one of: {', '.join(_operation_values())}"
    )


def _coerce_target(
    value: ImmutableArtifactValidationTarget | object,
    field: str,
) -> ImmutableArtifactValidationTarget:
    if isinstance(value, ImmutableArtifactValidationTarget):
        return value
    if isinstance(value, str):
        try:
            return ImmutableArtifactValidationTarget(value)
        except ValueError as exc:
            raise ImmutableArtifactSemanticsError(
                f"{field} must be one of: {', '.join(_target_values())}"
            ) from exc
    raise ImmutableArtifactSemanticsError(
        f"{field} must be one of: {', '.join(_target_values())}"
    )


def _operation_values() -> tuple[str, ...]:
    return tuple(operation.value for operation in ArtifactStoreBackendOperation)


def _target_values() -> tuple[str, ...]:
    return tuple(target.value for target in ImmutableArtifactValidationTarget)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise ImmutableArtifactSemanticsError(f"{field} must be a mapping")
    try:
        frozen = freeze_plain_data(value, path=field)
    except Exception as exc:
        raise ImmutableArtifactSemanticsError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise ImmutableArtifactSemanticsError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _plain_dict(value: object, field: str) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=field)
    if not isinstance(thawed, dict):
        raise ImmutableArtifactSemanticsError(f"{field} must be a mapping")
    return thawed


def _plain_value(value: object, field: str) -> PlainData:
    return ensure_plain_data(value, path=field)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImmutableArtifactSemanticsError(f"{field} must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ImmutableArtifactSemanticsError(f"{field} must be a sequence")
    return tuple(value)


def _required(mapping: Mapping[str, object], key: str) -> object:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ImmutableArtifactSemanticsError(f"{key} is required") from exc


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: set[str],
    field: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        unknown_text = ", ".join(sorted(unknown))
        raise ImmutableArtifactSemanticsError(
            f"{field} received unknown fields: {unknown_text}"
        )


__all__ = [
    "ImmutableArtifactSemanticsError",
    "ImmutableArtifactValidationTarget",
    "ImmutableArtifactValidationResult",
    "validate_external_artifact_declaration",
    "validate_published_artifact_record",
    "admit_artifact_store_operation",
    "admit_artifact_store_operations",
    "lookup_immutable_artifact",
    "evaluate_immutable_artifact_lookup",
    "artifact_ref_from_external_declaration",
    "artifact_ref_from_published_record",
]
