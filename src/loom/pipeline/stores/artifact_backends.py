"""Artifact-store backend extension contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from loom.artifacts import (
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ImmutableArtifactLookupRequest,
    ImmutableArtifactLookupResult,
)
from loom.operations import (
    OperationAdapterIdentity,
    OperationResult,
    OperationStatus,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data


ARTIFACT_STORE_BACKEND_CONTRACT_VERSION = 1

_BACKEND_KIND_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_URI_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")


class ArtifactStoreBackendError(ValueError):
    """Base error for artifact-store backend contracts."""


class ArtifactStoreBackendRegistryError(ArtifactStoreBackendError):
    """Raised when artifact-store backend registry operations fail."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: ArtifactStoreBackendDiagnostic | None = None,
    ) -> None:
        self.diagnostic = diagnostic
        super().__init__(message)


class ArtifactStoreBackendVersionError(ArtifactStoreBackendRegistryError):
    """Raised when an artifact-store backend uses an incompatible contract."""


class ArtifactStoreBackendOperation(StrEnum):
    """Artifact-store operations described by backend capability records."""

    READ = "read"
    WRITE = "write"
    LIST = "list"
    DELETE = "delete"
    VERIFY_CHECKSUM = "verify_checksum"
    COMMIT = "commit"
    CONSISTENCY = "consistency"
    LOOKUP = "lookup"
    PUBLISH = "publish"
    MATERIALIZE = "materialize"
    UPLOAD = "upload"
    DOWNLOAD = "download"


_PAYLOAD_BACKEND_OPERATIONS = frozenset(
    {
        ArtifactStoreBackendOperation.PUBLISH,
        ArtifactStoreBackendOperation.MATERIALIZE,
        ArtifactStoreBackendOperation.UPLOAD,
        ArtifactStoreBackendOperation.DOWNLOAD,
        ArtifactStoreBackendOperation.VERIFY_CHECKSUM,
    }
)


class ArtifactStoreCapabilitySupport(StrEnum):
    """Support states for artifact-store backend operations."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ArtifactStoreBackendDiagnosticSeverity(StrEnum):
    """Severity values for artifact-store backend diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ArtifactStoreBackendDiagnostic:
    """Plain structured diagnostic for backend registry and handler checks."""

    code: str
    message: str
    severity: ArtifactStoreBackendDiagnosticSeverity = (
        ArtifactStoreBackendDiagnosticSeverity.ERROR
    )
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_non_empty_string(self.code, "code"))
        object.__setattr__(
            self,
            "message",
            _require_non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_diagnostic_severity(self.severity, "severity"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStoreBackendDiagnostic:
        mapping = _mapping(data, "ArtifactStoreBackendDiagnostic")
        _reject_unknown(
            mapping,
            {"code", "message", "severity", "detail"},
            "ArtifactStoreBackendDiagnostic",
        )
        return cls(
            code=_require_non_empty_string(_required(mapping, "code"), "code"),
            message=_require_non_empty_string(
                _required(mapping, "message"),
                "message",
            ),
            severity=_coerce_diagnostic_severity(
                mapping.get(
                    "severity",
                    ArtifactStoreBackendDiagnosticSeverity.ERROR.value,
                ),
                "severity",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStoreCapabilityRecord:
    """Operation-specific artifact-store capability support."""

    operation: ArtifactStoreBackendOperation
    support: ArtifactStoreCapabilitySupport
    message: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation",
            _coerce_operation(self.operation, "operation"),
        )
        object.__setattr__(
            self,
            "support",
            _coerce_support(self.support, "support"),
        )
        if self.message is not None:
            object.__setattr__(
                self,
                "message",
                _require_non_empty_string(self.message, "message"),
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def supported(self) -> bool:
        return self.support is ArtifactStoreCapabilitySupport.SUPPORTED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation": self.operation.value,
            "support": self.support.value,
            "message": self.message,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStoreCapabilityRecord:
        mapping = _mapping(data, "ArtifactStoreCapabilityRecord")
        _reject_unknown(
            mapping,
            {"operation", "support", "message", "detail"},
            "ArtifactStoreCapabilityRecord",
        )
        return cls(
            operation=_coerce_operation(
                _required(mapping, "operation"),
                "operation",
            ),
            support=_coerce_support(_required(mapping, "support"), "support"),
            message=_optional_non_empty_string(mapping.get("message"), "message"),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStoreCapabilities:
    """Capability set for one artifact-store backend kind."""

    backend_kind: str
    records: tuple[ArtifactStoreCapabilityRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backend_kind",
            normalize_artifact_store_backend_kind(
                self.backend_kind,
                field="backend_kind",
            ),
        )
        records = tuple(self.records)
        seen: set[ArtifactStoreBackendOperation] = set()
        for record in records:
            if not isinstance(record, ArtifactStoreCapabilityRecord):
                raise ArtifactStoreBackendError(
                    "records must contain ArtifactStoreCapabilityRecord values"
                )
            if record.operation in seen:
                raise ArtifactStoreBackendError(
                    f"duplicate capability record for operation {record.operation.value!r}"
                )
            seen.add(record.operation)
        object.__setattr__(self, "records", records)

    def support_for(
        self,
        operation: ArtifactStoreBackendOperation | str,
    ) -> ArtifactStoreCapabilityRecord:
        wanted = _coerce_operation(operation, "operation")
        for record in self.records:
            if record.operation is wanted:
                return record
        return ArtifactStoreCapabilityRecord(
            operation=wanted,
            support=ArtifactStoreCapabilitySupport.UNKNOWN,
            message=(
                f"backend {self.backend_kind!r} has unknown support for "
                f"artifact-store operation {wanted.value!r}"
            ),
        )

    def supports(self, operation: ArtifactStoreBackendOperation | str) -> bool:
        return self.support_for(operation).supported

    def require(
        self,
        operation: ArtifactStoreBackendOperation | str,
    ) -> ArtifactStoreBackendOperationResult | None:
        record = self.support_for(operation)
        if record.supported:
            return None
        return ArtifactStoreBackendOperationResult(
            operation=record.operation,
            support=record.support,
            message=record.message
            or (
                f"backend {self.backend_kind!r} does not support "
                f"artifact-store operation {record.operation.value!r}"
            ),
            diagnostics=(self.diagnostic_for(record.operation),),
            detail=record.detail,
        )

    def diagnostic_for(
        self,
        operation: ArtifactStoreBackendOperation | str,
    ) -> ArtifactStoreBackendDiagnostic:
        record = self.support_for(operation)
        code = (
            "unknown_artifact_store_operation_support"
            if record.support is ArtifactStoreCapabilitySupport.UNKNOWN
            else "unsupported_artifact_store_operation"
        )
        return ArtifactStoreBackendDiagnostic(
            code=code,
            message=record.message
            or (
                f"backend {self.backend_kind!r} does not report supported "
                f"artifact-store operation {record.operation.value!r}"
            ),
            severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
            detail={
                "backend_kind": self.backend_kind,
                "operation": record.operation.value,
                "support": record.support.value,
                **dict(record.detail),
            },
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "backend_kind": self.backend_kind,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStoreCapabilities:
        mapping = _mapping(data, "ArtifactStoreCapabilities")
        _reject_unknown(
            mapping, {"backend_kind", "records"}, "ArtifactStoreCapabilities"
        )
        records_data = _sequence(_required(mapping, "records"), "records")
        return cls(
            backend_kind=normalize_artifact_store_backend_kind(
                _required(mapping, "backend_kind"),
                field="backend_kind",
            ),
            records=tuple(
                ArtifactStoreCapabilityRecord.from_dict(record)
                for record in records_data
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStoreBackendOperationResult:
    """Structured result for unsupported or unknown backend operations."""

    operation: ArtifactStoreBackendOperation
    support: ArtifactStoreCapabilitySupport
    message: str
    diagnostics: tuple[ArtifactStoreBackendDiagnostic, ...] = ()
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation",
            _coerce_operation(self.operation, "operation"),
        )
        object.__setattr__(
            self,
            "support",
            _coerce_support(self.support, "support"),
        )
        object.__setattr__(
            self,
            "message",
            _require_non_empty_string(self.message, "message"),
        )
        diagnostics = tuple(self.diagnostics)
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, ArtifactStoreBackendDiagnostic):
                raise ArtifactStoreBackendError(
                    "diagnostics must contain ArtifactStoreBackendDiagnostic values"
                )
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def supported(self) -> bool:
        return self.support is ArtifactStoreCapabilitySupport.SUPPORTED

    @classmethod
    def unsupported(
        cls,
        operation: ArtifactStoreBackendOperation | str,
        *,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendOperationResult:
        wanted = _coerce_operation(operation, "operation")
        result_message = (
            message
            if message is not None
            else f"artifact-store operation {wanted.value!r} is unsupported"
        )
        diagnostics = (
            ArtifactStoreBackendDiagnostic(
                code="unsupported_artifact_store_operation",
                message=result_message,
                detail={"operation": wanted.value},
            ),
        )
        return cls(
            operation=wanted,
            support=ArtifactStoreCapabilitySupport.UNSUPPORTED,
            message=result_message,
            diagnostics=diagnostics,
            detail={} if detail is None else detail,
        )

    @classmethod
    def unknown(
        cls,
        operation: ArtifactStoreBackendOperation | str,
        *,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendOperationResult:
        wanted = _coerce_operation(operation, "operation")
        result_message = (
            message
            if message is not None
            else f"artifact-store operation {wanted.value!r} support is unknown"
        )
        diagnostics = (
            ArtifactStoreBackendDiagnostic(
                code="unknown_artifact_store_operation_support",
                message=result_message,
                detail={"operation": wanted.value},
            ),
        )
        return cls(
            operation=wanted,
            support=ArtifactStoreCapabilitySupport.UNKNOWN,
            message=result_message,
            diagnostics=diagnostics,
            detail={} if detail is None else detail,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation": self.operation.value,
            "support": self.support.value,
            "message": self.message,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStoreBackendOperationResult:
        mapping = _mapping(data, "ArtifactStoreBackendOperationResult")
        _reject_unknown(
            mapping,
            {"operation", "support", "message", "diagnostics", "detail"},
            "ArtifactStoreBackendOperationResult",
        )
        diagnostics_data = _sequence(mapping.get("diagnostics", ()), "diagnostics")
        return cls(
            operation=_coerce_operation(
                _required(mapping, "operation"),
                "operation",
            ),
            support=_coerce_support(_required(mapping, "support"), "support"),
            message=_require_non_empty_string(_required(mapping, "message"), "message"),
            diagnostics=tuple(
                ArtifactStoreBackendDiagnostic.from_dict(diagnostic)
                for diagnostic in diagnostics_data
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStorePayloadOperationRequest:
    """Request for one explicit artifact-store payload operation."""

    operation: ArtifactStoreBackendOperation
    artifact: ArtifactRef | None = None
    source_uri: str | None = None
    target_uri: str | None = None
    checksum: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operation = _coerce_operation(self.operation, "operation")
        if operation not in _PAYLOAD_BACKEND_OPERATIONS:
            raise ArtifactStoreBackendError(
                "operation must be a payload artifact-store operation"
            )
        object.__setattr__(self, "operation", operation)
        if self.artifact is not None and not isinstance(self.artifact, ArtifactRef):
            raise ArtifactStoreBackendError("artifact must be an ArtifactRef or None")
        if self.source_uri is not None:
            object.__setattr__(
                self,
                "source_uri",
                _require_non_empty_string(self.source_uri, "source_uri"),
            )
        if self.target_uri is not None:
            object.__setattr__(
                self,
                "target_uri",
                _require_non_empty_string(self.target_uri, "target_uri"),
            )
        if self.checksum is not None:
            object.__setattr__(
                self,
                "checksum",
                _require_non_empty_string(self.checksum, "checksum"),
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation": self.operation.value,
            "artifact": None if self.artifact is None else self.artifact.to_dict(),
            "source_uri": self.source_uri,
            "target_uri": self.target_uri,
            "checksum": self.checksum,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStorePayloadOperationRequest:
        mapping = _mapping(data, "ArtifactStorePayloadOperationRequest")
        _reject_unknown(
            mapping,
            {"operation", "artifact", "source_uri", "target_uri", "checksum", "detail"},
            "ArtifactStorePayloadOperationRequest",
        )
        artifact_data = mapping.get("artifact")
        return cls(
            operation=_coerce_operation(_required(mapping, "operation"), "operation"),
            artifact=None if artifact_data is None else ArtifactRef.from_dict(artifact_data),
            source_uri=_optional_non_empty_string(mapping.get("source_uri"), "source_uri"),
            target_uri=_optional_non_empty_string(mapping.get("target_uri"), "target_uri"),
            checksum=_optional_non_empty_string(mapping.get("checksum"), "checksum"),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStorePayloadOperationResult:
    """Result of one explicit artifact-store payload operation."""

    request: ArtifactStorePayloadOperationRequest
    result: OperationResult
    location: ArtifactLocationSummary | None = None
    bytes_processed: int | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ArtifactStorePayloadOperationRequest):
            raise ArtifactStoreBackendError(
                "request must be an ArtifactStorePayloadOperationRequest"
            )
        if not isinstance(self.result, OperationResult):
            raise ArtifactStoreBackendError("result must be an OperationResult")
        if self.location is not None and not isinstance(
            self.location,
            ArtifactLocationSummary,
        ):
            raise ArtifactStoreBackendError(
                "location must be an ArtifactLocationSummary or None"
            )
        if self.bytes_processed is not None and (
            not isinstance(self.bytes_processed, int)
            or isinstance(self.bytes_processed, bool)
            or self.bytes_processed < 0
        ):
            raise ArtifactStoreBackendError(
                "bytes_processed must be a non-negative int or None"
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def succeeded(self) -> bool:
        return self.result.status is OperationStatus.SUCCEEDED

    @classmethod
    def unsupported(
        cls,
        request: ArtifactStorePayloadOperationRequest,
        *,
        backend_kind: str,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStorePayloadOperationResult:
        result_message = (
            message
            if message is not None
            else (
                f"backend {backend_kind!r} does not support payload operation "
                f"{request.operation.value!r}"
            )
        )
        return cls(
            request=request,
            result=OperationResult.unsupported(
                f"artifact_store.{request.operation.value}",
                reason=result_message,
                adapter=_operation_adapter(backend_kind),
                details={
                    "backend_kind": backend_kind,
                    "operation": request.operation.value,
                    **dict(detail or {}),
                },
            ),
            detail={} if detail is None else detail,
        )

    @classmethod
    def not_implemented(
        cls,
        request: ArtifactStorePayloadOperationRequest,
        *,
        backend_kind: str,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStorePayloadOperationResult:
        result_message = (
            message
            if message is not None
            else (
                f"backend {backend_kind!r} has not implemented payload operation "
                f"{request.operation.value!r}"
            )
        )
        return cls(
            request=request,
            result=OperationResult.not_implemented(
                f"artifact_store.{request.operation.value}",
                reason=result_message,
                adapter=_operation_adapter(backend_kind),
                details={
                    "backend_kind": backend_kind,
                    "operation": request.operation.value,
                    **dict(detail or {}),
                },
            ),
            detail={} if detail is None else detail,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "request": self.request.to_dict(),
            "result": self.result.to_dict(),
            "location": None if self.location is None else self.location.to_summary(),
            "bytes_processed": self.bytes_processed,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStorePayloadOperationResult:
        mapping = _mapping(data, "ArtifactStorePayloadOperationResult")
        _reject_unknown(
            mapping,
            {"request", "result", "location", "bytes_processed", "detail"},
            "ArtifactStorePayloadOperationResult",
        )
        location_data = mapping.get("location")
        return cls(
            request=ArtifactStorePayloadOperationRequest.from_dict(
                _required(mapping, "request")
            ),
            result=OperationResult.from_dict(_required(mapping, "result")),
            location=None
            if location_data is None
            else ArtifactLocationSummary.from_dict(location_data),
            bytes_processed=_optional_non_negative_int(
                mapping.get("bytes_processed"),
                "bytes_processed",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStoreBackendDescriptor:
    """Serializable descriptor for an artifact-store backend factory."""

    kind: str
    display_name: str
    contract_version: int = ARTIFACT_STORE_BACKEND_CONTRACT_VERSION
    api_version: str = "1"
    supported_uri_schemes: tuple[str, ...] = ()
    backend_key: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)
    factory: ArtifactStoreBackendFactory | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        kind = normalize_artifact_store_backend_kind(self.kind, field="kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "display_name",
            _require_non_empty_string(self.display_name, "display_name"),
        )
        object.__setattr__(
            self,
            "contract_version",
            _require_positive_int(self.contract_version, "contract_version"),
        )
        object.__setattr__(
            self,
            "api_version",
            _require_non_empty_string(self.api_version, "api_version"),
        )
        object.__setattr__(
            self,
            "supported_uri_schemes",
            _normalize_uri_schemes(self.supported_uri_schemes),
        )
        backend_key = (
            kind
            if self.backend_key is None
            else normalize_artifact_store_backend_kind(
                self.backend_key,
                field="backend_key",
            )
        )
        object.__setattr__(self, "backend_key", backend_key)
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "display_name": self.display_name,
            "contract_version": self.contract_version,
            "api_version": self.api_version,
            "supported_uri_schemes": list(self.supported_uri_schemes),
            "backend_key": self.backend_key,
            "details": thaw_plain_data(self.details, path="details"),
        }

    def to_summary(self) -> dict[str, PlainData]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: object) -> ArtifactStoreBackendDescriptor:
        mapping = _mapping(data, "ArtifactStoreBackendDescriptor")
        _reject_unknown(
            mapping,
            {
                "kind",
                "display_name",
                "contract_version",
                "api_version",
                "supported_uri_schemes",
                "backend_key",
                "details",
            },
            "ArtifactStoreBackendDescriptor",
        )
        return cls(
            kind=normalize_artifact_store_backend_kind(
                _required(mapping, "kind"),
                field="kind",
            ),
            display_name=_require_non_empty_string(
                _required(mapping, "display_name"),
                "display_name",
            ),
            contract_version=_require_positive_int(
                mapping.get(
                    "contract_version",
                    ARTIFACT_STORE_BACKEND_CONTRACT_VERSION,
                ),
                "contract_version",
            ),
            api_version=_require_non_empty_string(
                mapping.get("api_version", "1"),
                "api_version",
            ),
            supported_uri_schemes=_normalize_uri_schemes(
                _sequence(
                    mapping.get("supported_uri_schemes", ()), "supported_uri_schemes"
                )
            ),
            backend_key=_optional_non_empty_string(
                mapping.get("backend_key"),
                "backend_key",
            ),
            details=_plain_mapping(mapping.get("details", {}), "details"),
        )


@runtime_checkable
class ArtifactStoreBackendFactory(Protocol):
    """Factory surface implemented by artifact-store backend adapters."""

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor: ...

    def validate_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]: ...

    def redact_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> Mapping[str, PlainData]: ...

    def capabilities(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreCapabilities: ...

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendHandler: ...


@runtime_checkable
class ArtifactStoreBackendHandler(Protocol):
    """Handler surface for metadata checks and explicit lookup operations."""

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor: ...

    @property
    def store_ref(self) -> ArtifactStoreRef: ...

    @property
    def capabilities(self) -> ArtifactStoreCapabilities: ...

    def validate_store_ref(
        self,
        store_ref: ArtifactStoreRef,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]: ...

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef: ...

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]: ...

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ImmutableArtifactLookupResult | ArtifactStoreBackendOperationResult: ...

    def unsupported_operation(
        self,
        operation: ArtifactStoreBackendOperation | str,
        *,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendOperationResult: ...


@runtime_checkable
class ArtifactStoreBackendPayloadHandler(Protocol):
    """Companion handler surface for explicit payload operations."""

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor: ...

    @property
    def store_ref(self) -> ArtifactStoreRef: ...

    @property
    def capabilities(self) -> ArtifactStoreCapabilities: ...

    def payload_operation(
        self,
        request: ArtifactStorePayloadOperationRequest,
    ) -> ArtifactStorePayloadOperationResult | ArtifactStoreBackendOperationResult: ...


class ArtifactStoreBackendRegistry:
    """Programmatic registry keyed by normalized artifact-store backend kind."""

    def __init__(
        self,
        factories: Iterable[
            ArtifactStoreBackendFactory | ArtifactStoreBackendDescriptor
        ] = (),
    ) -> None:
        self._factories: dict[str, ArtifactStoreBackendFactory] = {}
        for factory in factories:
            self.register(factory)

    @property
    def registered_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def __contains__(self, kind: object) -> bool:
        if not isinstance(kind, str):
            return False
        try:
            normalized = normalize_artifact_store_backend_kind(kind, field="kind")
        except ArtifactStoreBackendError:
            return False
        return normalized in self._factories

    def register(
        self,
        factory: ArtifactStoreBackendFactory | ArtifactStoreBackendDescriptor,
        *,
        replace: bool = False,
    ) -> ArtifactStoreBackendDescriptor:
        normalized_factory = _coerce_factory(factory)
        descriptor = _descriptor_for_factory(normalized_factory)
        _require_compatible_descriptor(descriptor)
        if descriptor.kind in self._factories and not replace:
            diagnostic = ArtifactStoreBackendDiagnostic(
                code="duplicate_artifact_store_backend_kind",
                message=(
                    f"artifact-store backend kind {descriptor.kind!r} is already registered"
                ),
                detail={"backend_kind": descriptor.kind},
            )
            raise ArtifactStoreBackendRegistryError(
                diagnostic.message,
                diagnostic=diagnostic,
            )
        self._factories[descriptor.kind] = normalized_factory
        return descriptor

    def get(self, kind: str) -> ArtifactStoreBackendFactory:
        normalized = normalize_artifact_store_backend_kind(kind, field="kind")
        try:
            return self._factories[normalized]
        except KeyError as exc:
            diagnostic = ArtifactStoreBackendDiagnostic(
                code="missing_artifact_store_backend_kind",
                message=f"artifact-store backend kind {normalized!r} is not registered",
                detail={"backend_kind": normalized},
            )
            raise ArtifactStoreBackendRegistryError(
                diagnostic.message,
                diagnostic=diagnostic,
            ) from exc

    def descriptor(self, kind: str) -> ArtifactStoreBackendDescriptor:
        return _descriptor_for_factory(self.get(kind))

    def descriptors(self) -> tuple[ArtifactStoreBackendDescriptor, ...]:
        return tuple(
            _descriptor_for_factory(self._factories[kind])
            for kind in self.registered_kinds
        )

    def create_handler(
        self,
        kind: str,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendHandler:
        return self.get(kind).create_handler(
            store_ref,
            config=config,
            run_context=run_context,
        )


def artifact_store_backend_versions_compatible(version: object) -> bool:
    """Return whether a backend contract version is supported by this runtime."""

    return (
        isinstance(version, int)
        and not isinstance(version, bool)
        and version == ARTIFACT_STORE_BACKEND_CONTRACT_VERSION
    )


def normalize_artifact_store_backend_kind(value: object, *, field: str = "kind") -> str:
    """Normalize and validate an artifact-store backend kind/key."""

    if not isinstance(value, str):
        raise ArtifactStoreBackendError(f"{field} must be a non-empty string")
    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        raise ArtifactStoreBackendError(f"{field} must be a non-empty string")
    if not normalized.isascii() or not _BACKEND_KIND_RE.match(normalized):
        raise ArtifactStoreBackendError(
            f"{field} must contain lowercase ASCII letters, digits, '.', or '-'"
        )
    return normalized


def _coerce_factory(
    value: ArtifactStoreBackendFactory | ArtifactStoreBackendDescriptor,
) -> ArtifactStoreBackendFactory:
    if isinstance(value, ArtifactStoreBackendDescriptor):
        if value.factory is None:
            raise ArtifactStoreBackendRegistryError(
                "artifact-store backend descriptor does not include a factory"
            )
        return value.factory
    if isinstance(value, ArtifactStoreBackendFactory):
        return value
    raise ArtifactStoreBackendRegistryError(
        "artifact-store backend registration requires a descriptor or factory"
    )


def _descriptor_for_factory(
    factory: ArtifactStoreBackendFactory,
) -> ArtifactStoreBackendDescriptor:
    descriptor = factory.descriptor
    if not isinstance(descriptor, ArtifactStoreBackendDescriptor):
        raise ArtifactStoreBackendRegistryError(
            "artifact-store backend factory descriptor must be an "
            "ArtifactStoreBackendDescriptor"
        )
    return descriptor


def _require_compatible_descriptor(descriptor: ArtifactStoreBackendDescriptor) -> None:
    if artifact_store_backend_versions_compatible(descriptor.contract_version):
        return
    diagnostic = ArtifactStoreBackendDiagnostic(
        code="incompatible_artifact_store_backend_contract_version",
        message=(
            f"artifact-store backend {descriptor.kind!r} uses contract version "
            f"{descriptor.contract_version}, but this runtime supports "
            f"{ARTIFACT_STORE_BACKEND_CONTRACT_VERSION}"
        ),
        detail={
            "backend_kind": descriptor.kind,
            "contract_version": descriptor.contract_version,
            "supported_contract_version": ARTIFACT_STORE_BACKEND_CONTRACT_VERSION,
        },
    )
    raise ArtifactStoreBackendVersionError(diagnostic.message, diagnostic=diagnostic)


def _coerce_operation(
    value: ArtifactStoreBackendOperation | object,
    field: str,
) -> ArtifactStoreBackendOperation:
    if isinstance(value, ArtifactStoreBackendOperation):
        return value
    if isinstance(value, str):
        try:
            return ArtifactStoreBackendOperation(value)
        except ValueError as exc:
            raise ArtifactStoreBackendError(
                f"{field} must be one of: {', '.join(_operation_values())}"
            ) from exc
    raise ArtifactStoreBackendError(
        f"{field} must be one of: {', '.join(_operation_values())}"
    )


def _coerce_support(
    value: ArtifactStoreCapabilitySupport | object,
    field: str,
) -> ArtifactStoreCapabilitySupport:
    if isinstance(value, ArtifactStoreCapabilitySupport):
        return value
    if isinstance(value, str):
        try:
            return ArtifactStoreCapabilitySupport(value)
        except ValueError as exc:
            raise ArtifactStoreBackendError(
                f"{field} must be one of: {', '.join(_support_values())}"
            ) from exc
    raise ArtifactStoreBackendError(
        f"{field} must be one of: {', '.join(_support_values())}"
    )


def _coerce_diagnostic_severity(
    value: ArtifactStoreBackendDiagnosticSeverity | object,
    field: str,
) -> ArtifactStoreBackendDiagnosticSeverity:
    if isinstance(value, ArtifactStoreBackendDiagnosticSeverity):
        return value
    if isinstance(value, str):
        try:
            return ArtifactStoreBackendDiagnosticSeverity(value)
        except ValueError as exc:
            raise ArtifactStoreBackendError(
                f"{field} must be one of: {', '.join(_diagnostic_severity_values())}"
            ) from exc
    raise ArtifactStoreBackendError(
        f"{field} must be one of: {', '.join(_diagnostic_severity_values())}"
    )


def _operation_values() -> tuple[str, ...]:
    return tuple(operation.value for operation in ArtifactStoreBackendOperation)


def _support_values() -> tuple[str, ...]:
    return tuple(support.value for support in ArtifactStoreCapabilitySupport)


def _diagnostic_severity_values() -> tuple[str, ...]:
    return tuple(severity.value for severity in ArtifactStoreBackendDiagnosticSeverity)


def _operation_adapter(backend_kind: str) -> OperationAdapterIdentity:
    return OperationAdapterIdentity(
        name=normalize_artifact_store_backend_kind(backend_kind, field="backend_kind"),
        kind="artifact-store-backend",
        version="1",
    )


def _normalize_uri_schemes(values: Iterable[object]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ArtifactStoreBackendError(
                "supported_uri_schemes must contain URI scheme strings"
            )
        scheme = value.strip().lower()
        if not scheme or not scheme.isascii() or not _URI_SCHEME_RE.match(scheme):
            raise ArtifactStoreBackendError(
                "supported_uri_schemes must contain valid URI schemes"
            )
        normalized.add(scheme)
    return tuple(sorted(normalized))


def _require_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactStoreBackendError(f"{field} must be a positive integer")
    return value


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactStoreBackendError(f"{field} must be a non-empty string")
    return value


def _optional_non_empty_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field)


def _optional_non_negative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactStoreBackendError(f"{field} must be a non-negative integer")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise ArtifactStoreBackendError(f"{field} must be a mapping")
    try:
        frozen = freeze_plain_data(value, path=field)
    except Exception as exc:
        raise ArtifactStoreBackendError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise ArtifactStoreBackendError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactStoreBackendError(f"{field} must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ArtifactStoreBackendError(f"{field} must be a sequence")
    return tuple(value)


def _required(mapping: Mapping[str, object], key: str) -> object:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ArtifactStoreBackendError(f"{key} is required") from exc


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: set[str],
    field: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        unknown_text = ", ".join(sorted(unknown))
        raise ArtifactStoreBackendError(
            f"{field} received unknown fields: {unknown_text}"
        )


__all__ = [
    "ARTIFACT_STORE_BACKEND_CONTRACT_VERSION",
    "ArtifactStoreBackendError",
    "ArtifactStoreBackendVersionError",
    "ArtifactStoreBackendRegistryError",
    "ArtifactStoreBackendOperation",
    "ArtifactStoreCapabilitySupport",
    "ArtifactStoreBackendDiagnosticSeverity",
    "ArtifactStoreBackendDiagnostic",
    "ArtifactStoreCapabilityRecord",
    "ArtifactStoreCapabilities",
    "ArtifactStoreBackendOperationResult",
    "ArtifactStorePayloadOperationRequest",
    "ArtifactStorePayloadOperationResult",
    "ArtifactStoreBackendDescriptor",
    "ArtifactStoreBackendFactory",
    "ArtifactStoreBackendHandler",
    "ArtifactStoreBackendPayloadHandler",
    "ArtifactStoreBackendRegistry",
    "artifact_store_backend_versions_compatible",
    "normalize_artifact_store_backend_kind",
]
