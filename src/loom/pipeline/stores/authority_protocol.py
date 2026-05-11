"""Transport-independent authority protocol value models."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.pipeline.submitted import SubmittedOperationRecord

from .authority_resolution import (
    AuthorityResolutionFailureKind,
    AuthorityResolverDiagnostic,
)
from .capabilities import BackendCapabilitySet, StoreDiagnostic
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    LeaseRecord,
    OutputCommitRecord,
    RecoveryRecord,
    StageAttempt,
)
from .schema_policy import (
    AUTHORITY_SCHEMA_VERSION,
    AuthoritySchemaCheck,
)


AUTHORITY_PROTOCOL_VERSION = 1


class AuthorityProtocolError(ValueError):
    """Raised when authority protocol records are invalid."""


class AuthorityProtocolOperationKind(StrEnum):
    """Representative authority protocol operation families."""

    READINESS = "readiness"
    CAPABILITIES = "capabilities"
    RUN_LIFECYCLE = "run_lifecycle"
    RUN_SNAPSHOT = "run_snapshot"
    STAGE_LIFECYCLE = "stage_lifecycle"
    STAGE_ATTEMPT = "stage_attempt"
    SUBMITTED_OPERATION = "submitted_operation"
    OUTPUT_COMMIT = "output_commit"
    ARTIFACT_FACTS = "artifact_facts"
    LEASE = "lease"
    RECOVERY_SCAN = "recovery_scan"
    CLEANUP_CANDIDATES = "cleanup_candidates"


class AuthorityProtocolErrorCategory(StrEnum):
    """Machine-readable protocol rejection categories."""

    RESOLVER = "resolver"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    STALE_GENERATION = "stale_generation"
    STALE_REVISION = "stale_revision"
    STALE_FENCING = "stale_fencing"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNAVAILABLE_SERVICE = "unavailable_service"
    INTERNAL_ERROR = "internal_error"


class AuthorityReadinessState(StrEnum):
    """Service readiness state carried by protocol readiness reports."""

    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class AuthorityProtocolVersion:
    """Protocol and schema compatibility facts."""

    protocol_version: int = AUTHORITY_PROTOCOL_VERSION
    min_supported_protocol_version: int = AUTHORITY_PROTOCOL_VERSION
    schema_version: int = AUTHORITY_SCHEMA_VERSION
    schema_check: AuthoritySchemaCheck = field(default_factory=AuthoritySchemaCheck)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "protocol_version",
            _positive_int(self.protocol_version, "protocol_version"),
        )
        object.__setattr__(
            self,
            "min_supported_protocol_version",
            _positive_int(
                self.min_supported_protocol_version,
                "min_supported_protocol_version",
            ),
        )
        if self.min_supported_protocol_version > self.protocol_version:
            raise AuthorityProtocolError(
                "min_supported_protocol_version must not exceed protocol_version"
            )
        object.__setattr__(
            self, "schema_version", _positive_int(self.schema_version, "schema_version")
        )
        if not isinstance(self.schema_check, AuthoritySchemaCheck):
            raise AuthorityProtocolError(
                "schema_check must be an AuthoritySchemaCheck"
            )

    @property
    def supported(self) -> bool:
        return (
            self.min_supported_protocol_version
            <= AUTHORITY_PROTOCOL_VERSION
            <= self.protocol_version
            and self.schema_check.supported
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "protocol_version": self.protocol_version,
            "min_supported_protocol_version": self.min_supported_protocol_version,
            "schema_version": self.schema_version,
            "schema_check": self.schema_check.to_dict(),
            "supported": self.supported,
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolVersion":
        mapping = _mapping(data, "AuthorityProtocolVersion")
        _reject_unknown(
            mapping,
            {
                "protocol_version",
                "min_supported_protocol_version",
                "schema_version",
                "schema_check",
                "supported",
            },
            "AuthorityProtocolVersion",
        )
        version = cls(
            protocol_version=_positive_int(
                mapping.get("protocol_version", AUTHORITY_PROTOCOL_VERSION),
                "protocol_version",
            ),
            min_supported_protocol_version=_positive_int(
                mapping.get(
                    "min_supported_protocol_version",
                    AUTHORITY_PROTOCOL_VERSION,
                ),
                "min_supported_protocol_version",
            ),
            schema_version=_positive_int(
                mapping.get("schema_version", AUTHORITY_SCHEMA_VERSION),
                "schema_version",
            ),
            schema_check=AuthoritySchemaCheck.from_dict(
                mapping.get("schema_check", AuthoritySchemaCheck().to_dict())
            ),
        )
        if "supported" in mapping and mapping["supported"] != version.supported:
            raise AuthorityProtocolError("supported does not match protocol facts")
        return version


@dataclass(frozen=True, slots=True)
class AuthorityProtocolMetadata:
    """Common protocol metadata carried by requests and responses."""

    request_id: str
    operation_kind: AuthorityProtocolOperationKind
    protocol_version: int = AUTHORITY_PROTOCOL_VERSION
    service_generation: str | None = None
    workspace_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _non_empty(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "operation_kind",
            _enum(self.operation_kind, AuthorityProtocolOperationKind, "operation_kind"),
        )
        object.__setattr__(
            self,
            "protocol_version",
            _positive_int(self.protocol_version, "protocol_version"),
        )
        if self.service_generation is not None:
            object.__setattr__(
                self,
                "service_generation",
                _non_empty(self.service_generation, "service_generation"),
            )
        if self.workspace_id is not None:
            object.__setattr__(
                self, "workspace_id", _non_empty(self.workspace_id, "workspace_id")
            )
        if self.idempotency_key is not None:
            object.__setattr__(
                self,
                "idempotency_key",
                _non_empty(self.idempotency_key, "idempotency_key"),
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "request_id": self.request_id,
            "operation_kind": self.operation_kind.value,
            "protocol_version": self.protocol_version,
            "service_generation": self.service_generation,
            "workspace_id": self.workspace_id,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolMetadata":
        mapping = _mapping(data, "AuthorityProtocolMetadata")
        _reject_unknown(
            mapping,
            {
                "request_id",
                "operation_kind",
                "protocol_version",
                "service_generation",
                "workspace_id",
                "idempotency_key",
            },
            "AuthorityProtocolMetadata",
        )
        return cls(
            request_id=_non_empty(_required(mapping, "request_id"), "request_id"),
            operation_kind=_enum(
                _required(mapping, "operation_kind"),
                AuthorityProtocolOperationKind,
                "operation_kind",
            ),
            protocol_version=_positive_int(
                mapping.get("protocol_version", AUTHORITY_PROTOCOL_VERSION),
                "protocol_version",
            ),
            service_generation=_optional_string(
                mapping.get("service_generation"), "service_generation"
            ),
            workspace_id=_optional_string(mapping.get("workspace_id"), "workspace_id"),
            idempotency_key=_optional_string(
                mapping.get("idempotency_key"), "idempotency_key"
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorityProtocolRequest:
    """Generic authority protocol request envelope."""

    metadata: AuthorityProtocolMetadata
    run_uri: str | None = None
    stage_name: str | None = None
    submission_id: str | None = None
    lease_id: str | None = None
    fencing_token: str | None = None
    owner_id: str | None = None
    expected_revision: BackendRevision | None = None
    body: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, AuthorityProtocolMetadata):
            raise AuthorityProtocolError(
                "metadata must be an AuthorityProtocolMetadata"
            )
        if self.run_uri is not None:
            object.__setattr__(self, "run_uri", _non_empty(self.run_uri, "run_uri"))
        if self.stage_name is not None:
            object.__setattr__(
                self, "stage_name", _non_empty(self.stage_name, "stage_name")
            )
        if self.submission_id is not None:
            object.__setattr__(
                self,
                "submission_id",
                _non_empty(self.submission_id, "submission_id"),
            )
        if self.lease_id is not None:
            object.__setattr__(self, "lease_id", _non_empty(self.lease_id, "lease_id"))
        if self.fencing_token is not None:
            object.__setattr__(
                self,
                "fencing_token",
                _non_empty(self.fencing_token, "fencing_token"),
            )
        if self.owner_id is not None:
            object.__setattr__(self, "owner_id", _non_empty(self.owner_id, "owner_id"))
        if self.expected_revision is not None and not isinstance(
            self.expected_revision, BackendRevision
        ):
            raise AuthorityProtocolError(
                "expected_revision must be a BackendRevision or None"
            )
        object.__setattr__(self, "body", _plain_mapping(self.body, "body"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "metadata": self.metadata.to_dict(),
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "submission_id": self.submission_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "owner_id": self.owner_id,
            "expected_revision": None
            if self.expected_revision is None
            else self.expected_revision.to_dict(),
            "body": dict(self.body),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolRequest":
        mapping = _mapping(data, "AuthorityProtocolRequest")
        _reject_unknown(
            mapping,
            {
                "metadata",
                "run_uri",
                "stage_name",
                "submission_id",
                "lease_id",
                "fencing_token",
                "owner_id",
                "expected_revision",
                "body",
            },
            "AuthorityProtocolRequest",
        )
        expected = mapping.get("expected_revision")
        return cls(
            metadata=AuthorityProtocolMetadata.from_dict(_required(mapping, "metadata")),
            run_uri=_optional_string(mapping.get("run_uri"), "run_uri"),
            stage_name=_optional_string(mapping.get("stage_name"), "stage_name"),
            submission_id=_optional_string(
                mapping.get("submission_id"), "submission_id"
            ),
            lease_id=_optional_string(mapping.get("lease_id"), "lease_id"),
            fencing_token=_optional_string(
                mapping.get("fencing_token"), "fencing_token"
            ),
            owner_id=_optional_string(mapping.get("owner_id"), "owner_id"),
            expected_revision=None
            if expected is None
            else BackendRevision.from_dict(expected),
            body=_plain_mapping(mapping.get("body", {}), "body"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityProtocolReadiness:
    """Readiness and compatibility payload for an authority service."""

    version: AuthorityProtocolVersion = field(default_factory=AuthorityProtocolVersion)
    readiness: AuthorityReadinessState = AuthorityReadinessState.READY
    capabilities: BackendCapabilitySet | None = None
    service_generation: str | None = None
    workspace_id: str | None = None
    diagnostics: tuple[StoreDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.version, AuthorityProtocolVersion):
            raise AuthorityProtocolError(
                "version must be an AuthorityProtocolVersion"
            )
        object.__setattr__(
            self,
            "readiness",
            _enum(self.readiness, AuthorityReadinessState, "readiness"),
        )
        if self.capabilities is not None and not isinstance(
            self.capabilities, BackendCapabilitySet
        ):
            raise AuthorityProtocolError(
                "capabilities must be a BackendCapabilitySet or None"
            )
        if self.service_generation is not None:
            object.__setattr__(
                self,
                "service_generation",
                _non_empty(self.service_generation, "service_generation"),
            )
        if self.workspace_id is not None:
            object.__setattr__(
                self, "workspace_id", _non_empty(self.workspace_id, "workspace_id")
            )
        object.__setattr__(
            self,
            "diagnostics",
            _tuple_of(self.diagnostics, StoreDiagnostic, "diagnostics"),
        )

    @property
    def ready(self) -> bool:
        return self.readiness is AuthorityReadinessState.READY and self.version.supported

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "protocol_version": self.version.protocol_version,
            "schema_version": self.version.schema_version,
            "service_generation": self.service_generation,
            "workspace_id": self.workspace_id,
            "readiness": self.readiness.value,
            "ready": self.ready,
            "version": self.version.to_dict(),
            "capabilities": None
            if self.capabilities is None
            else self.capabilities.to_dict(),
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolReadiness":
        mapping = _mapping(data, "AuthorityProtocolReadiness")
        _reject_unknown(
            mapping,
            {
                "protocol_version",
                "schema_version",
                "service_generation",
                "workspace_id",
                "readiness",
                "ready",
                "version",
                "capabilities",
                "diagnostics",
            },
            "AuthorityProtocolReadiness",
        )
        version_data = mapping.get("version")
        if version_data is None:
            version_data = {
                "protocol_version": mapping.get(
                    "protocol_version", AUTHORITY_PROTOCOL_VERSION
                ),
                "schema_version": mapping.get(
                    "schema_version", AUTHORITY_SCHEMA_VERSION
                ),
            }
        capabilities_data = mapping.get("capabilities")
        readiness = cls(
            version=AuthorityProtocolVersion.from_dict(version_data),
            readiness=_enum(
                mapping.get("readiness", AuthorityReadinessState.READY.value),
                AuthorityReadinessState,
                "readiness",
            ),
            capabilities=None
            if capabilities_data is None
            else BackendCapabilitySet.from_dict(capabilities_data),
            service_generation=_optional_string(
                mapping.get("service_generation"), "service_generation"
            ),
            workspace_id=_optional_string(mapping.get("workspace_id"), "workspace_id"),
            diagnostics=tuple(
                StoreDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
        )
        if "ready" in mapping and mapping["ready"] != readiness.ready:
            raise AuthorityProtocolError("ready does not match readiness facts")
        return readiness


@dataclass(frozen=True, slots=True)
class AuthorityProtocolResult:
    """Accepted result payload for a protocol response."""

    revision: BackendRevision | None = None
    service_generation: str | None = None
    lease_id: str | None = None
    fencing_token: str | None = None
    lease: LeaseRecord | None = None
    snapshot: AuthoritativeRunSnapshot | None = None
    stage_attempt: StageAttempt | None = None
    output_commit: OutputCommitRecord | None = None
    submitted_operation: SubmittedOperationRecord | None = None
    artifact_facts: tuple[ArtifactFactRecord, ...] = ()
    submitted_operations: tuple[SubmittedOperationRecord, ...] = ()
    cleanup_candidates: tuple[CleanupCandidate, ...] = ()
    recovery_records: tuple[RecoveryRecord, ...] = ()
    body: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _optional_instance(self.revision, BackendRevision, "revision")
        if self.service_generation is not None:
            object.__setattr__(
                self,
                "service_generation",
                _non_empty(self.service_generation, "service_generation"),
            )
        _optional_instance(self.lease, LeaseRecord, "lease")
        lease_id = self.lease_id
        fencing_token = self.fencing_token
        if self.lease is not None:
            if lease_id is None:
                lease_id = self.lease.lease_id
            elif lease_id != self.lease.lease_id:
                raise AuthorityProtocolError("lease_id must match lease.lease_id")
            if fencing_token is None:
                fencing_token = self.lease.fencing_token
            elif fencing_token != self.lease.fencing_token:
                raise AuthorityProtocolError(
                    "fencing_token must match lease.fencing_token"
                )
        object.__setattr__(self, "lease_id", _optional_string(lease_id, "lease_id"))
        object.__setattr__(
            self,
            "fencing_token",
            _optional_string(fencing_token, "fencing_token"),
        )
        _optional_instance(self.snapshot, AuthoritativeRunSnapshot, "snapshot")
        _optional_instance(self.stage_attempt, StageAttempt, "stage_attempt")
        _optional_instance(self.output_commit, OutputCommitRecord, "output_commit")
        _optional_instance(
            self.submitted_operation,
            SubmittedOperationRecord,
            "submitted_operation",
        )
        object.__setattr__(
            self,
            "artifact_facts",
            _tuple_of(self.artifact_facts, ArtifactFactRecord, "artifact_facts"),
        )
        object.__setattr__(
            self,
            "submitted_operations",
            _tuple_of(
                self.submitted_operations,
                SubmittedOperationRecord,
                "submitted_operations",
            ),
        )
        object.__setattr__(
            self,
            "cleanup_candidates",
            _tuple_of(
                self.cleanup_candidates,
                CleanupCandidate,
                "cleanup_candidates",
            ),
        )
        object.__setattr__(
            self,
            "recovery_records",
            _tuple_of(self.recovery_records, RecoveryRecord, "recovery_records"),
        )
        object.__setattr__(self, "body", _plain_mapping(self.body, "body"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "revision": None if self.revision is None else self.revision.to_dict(),
            "service_generation": self.service_generation,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "lease": None if self.lease is None else self.lease.to_dict(),
            "snapshot": None if self.snapshot is None else self.snapshot.to_dict(),
            "stage_attempt": None
            if self.stage_attempt is None
            else self.stage_attempt.to_dict(),
            "output_commit": None
            if self.output_commit is None
            else self.output_commit.to_dict(),
            "submitted_operation": None
            if self.submitted_operation is None
            else self.submitted_operation.to_dict(),
            "artifact_facts": [fact.to_dict() for fact in self.artifact_facts],
            "submitted_operations": [
                operation.to_dict() for operation in self.submitted_operations
            ],
            "cleanup_candidates": [
                candidate.to_dict() for candidate in self.cleanup_candidates
            ],
            "recovery_records": [
                record.to_dict() for record in self.recovery_records
            ],
            "body": dict(self.body),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolResult":
        mapping = _mapping(data, "AuthorityProtocolResult")
        _reject_unknown(
            mapping,
            {
                "revision",
                "service_generation",
                "lease_id",
                "fencing_token",
                "lease",
                "snapshot",
                "stage_attempt",
                "output_commit",
                "submitted_operation",
                "artifact_facts",
                "submitted_operations",
                "cleanup_candidates",
                "recovery_records",
                "body",
            },
            "AuthorityProtocolResult",
        )
        return cls(
            revision=_optional_record(
                mapping.get("revision"), BackendRevision.from_dict
            ),
            service_generation=_optional_string(
                mapping.get("service_generation"), "service_generation"
            ),
            lease_id=_optional_string(mapping.get("lease_id"), "lease_id"),
            fencing_token=_optional_string(
                mapping.get("fencing_token"), "fencing_token"
            ),
            lease=_optional_record(mapping.get("lease"), LeaseRecord.from_dict),
            snapshot=_optional_record(
                mapping.get("snapshot"), AuthoritativeRunSnapshot.from_dict
            ),
            stage_attempt=_optional_record(
                mapping.get("stage_attempt"), StageAttempt.from_dict
            ),
            output_commit=_optional_record(
                mapping.get("output_commit"), OutputCommitRecord.from_dict
            ),
            submitted_operation=_optional_record(
                mapping.get("submitted_operation"),
                SubmittedOperationRecord.from_dict,
            ),
            artifact_facts=tuple(
                ArtifactFactRecord.from_dict(item)
                for item in _sequence(
                    mapping.get("artifact_facts", ()), "artifact_facts"
                )
            ),
            submitted_operations=tuple(
                SubmittedOperationRecord.from_dict(item)
                for item in _sequence(
                    mapping.get("submitted_operations", ()), "submitted_operations"
                )
            ),
            cleanup_candidates=tuple(
                CleanupCandidate.from_dict(item)
                for item in _sequence(
                    mapping.get("cleanup_candidates", ()), "cleanup_candidates"
                )
            ),
            recovery_records=tuple(
                RecoveryRecord.from_dict(item)
                for item in _sequence(
                    mapping.get("recovery_records", ()), "recovery_records"
                )
            ),
            body=_plain_mapping(mapping.get("body", {}), "body"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityProtocolRejection:
    """Structured rejection or error payload for a protocol response."""

    category: AuthorityProtocolErrorCategory
    code: str
    message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)
    diagnostics: tuple[StoreDiagnostic, ...] = ()
    resolver_failure_kind: AuthorityResolutionFailureKind | None = None
    resolver_diagnostics: tuple[AuthorityResolverDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "category",
            _enum(self.category, AuthorityProtocolErrorCategory, "category"),
        )
        object.__setattr__(self, "code", _non_empty(self.code, "code"))
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))
        object.__setattr__(
            self,
            "diagnostics",
            _tuple_of(self.diagnostics, StoreDiagnostic, "diagnostics"),
        )
        if self.resolver_failure_kind is not None:
            object.__setattr__(
                self,
                "resolver_failure_kind",
                _enum(
                    self.resolver_failure_kind,
                    AuthorityResolutionFailureKind,
                    "resolver_failure_kind",
                ),
            )
        object.__setattr__(
            self,
            "resolver_diagnostics",
            _tuple_of(
                self.resolver_diagnostics,
                AuthorityResolverDiagnostic,
                "resolver_diagnostics",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "detail": dict(self.detail),
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
            "resolver_failure_kind": None
            if self.resolver_failure_kind is None
            else self.resolver_failure_kind.value,
            "resolver_diagnostics": [
                diagnostic.to_dict()
                for diagnostic in self.resolver_diagnostics
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolRejection":
        mapping = _mapping(data, "AuthorityProtocolRejection")
        _reject_unknown(
            mapping,
            {
                "category",
                "code",
                "message",
                "detail",
                "diagnostics",
                "resolver_failure_kind",
                "resolver_diagnostics",
            },
            "AuthorityProtocolRejection",
        )
        failure = mapping.get("resolver_failure_kind")
        return cls(
            category=_enum(
                _required(mapping, "category"),
                AuthorityProtocolErrorCategory,
                "category",
            ),
            code=_non_empty(_required(mapping, "code"), "code"),
            message=_non_empty(_required(mapping, "message"), "message"),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
            diagnostics=tuple(
                StoreDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
            resolver_failure_kind=None
            if failure is None
            else _enum(
                failure,
                AuthorityResolutionFailureKind,
                "resolver_failure_kind",
            ),
            resolver_diagnostics=tuple(
                AuthorityResolverDiagnostic.from_dict(item)
                for item in _sequence(
                    mapping.get("resolver_diagnostics", ()),
                    "resolver_diagnostics",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorityProtocolResponse:
    """Accepted-or-rejected authority protocol response envelope."""

    metadata: AuthorityProtocolMetadata
    accepted: bool
    result: AuthorityProtocolResult | None = None
    rejection: AuthorityProtocolRejection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, AuthorityProtocolMetadata):
            raise AuthorityProtocolError(
                "metadata must be an AuthorityProtocolMetadata"
            )
        if not isinstance(self.accepted, bool):
            raise AuthorityProtocolError("accepted must be a bool")
        if self.result is not None and not isinstance(
            self.result, AuthorityProtocolResult
        ):
            raise AuthorityProtocolError(
                "result must be an AuthorityProtocolResult or None"
            )
        if self.rejection is not None and not isinstance(
            self.rejection, AuthorityProtocolRejection
        ):
            raise AuthorityProtocolError(
                "rejection must be an AuthorityProtocolRejection or None"
            )
        if self.accepted:
            if self.result is None or self.rejection is not None:
                raise AuthorityProtocolError(
                    "accepted responses require result and no rejection"
                )
        elif self.rejection is None or self.result is not None:
            raise AuthorityProtocolError(
                "rejected responses require rejection and no result"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "metadata": self.metadata.to_dict(),
            "accepted": self.accepted,
            "result": None if self.result is None else self.result.to_dict(),
            "rejection": None
            if self.rejection is None
            else self.rejection.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityProtocolResponse":
        mapping = _mapping(data, "AuthorityProtocolResponse")
        _reject_unknown(
            mapping,
            {"metadata", "accepted", "result", "rejection"},
            "AuthorityProtocolResponse",
        )
        accepted = _bool(_required(mapping, "accepted"), "accepted")
        result_data = mapping.get("result")
        rejection_data = mapping.get("rejection")
        return cls(
            metadata=AuthorityProtocolMetadata.from_dict(_required(mapping, "metadata")),
            accepted=accepted,
            result=None
            if result_data is None
            else AuthorityProtocolResult.from_dict(result_data),
            rejection=None
            if rejection_data is None
            else AuthorityProtocolRejection.from_dict(rejection_data),
        )


def accepted_authority_response(
    metadata: AuthorityProtocolMetadata,
    result: AuthorityProtocolResult,
) -> AuthorityProtocolResponse:
    """Build an accepted protocol response."""

    return AuthorityProtocolResponse(
        metadata=metadata,
        accepted=True,
        result=result,
    )


def rejected_authority_response(
    metadata: AuthorityProtocolMetadata,
    rejection: AuthorityProtocolRejection,
) -> AuthorityProtocolResponse:
    """Build a rejected protocol response."""

    return AuthorityProtocolResponse(
        metadata=metadata,
        accepted=False,
        rejection=rejection,
    )


def protocol_versions_compatible(
    version: AuthorityProtocolVersion,
    *,
    client_version: int = AUTHORITY_PROTOCOL_VERSION,
) -> bool:
    """Return whether a client protocol version is supported."""

    client = _positive_int(client_version, "client_version")
    return (
        version.min_supported_protocol_version <= client <= version.protocol_version
        and version.schema_check.supported
    )


def _optional_instance[T](value: object | None, kind: type[T], field: str) -> None:
    if value is not None and not isinstance(value, kind):
        raise AuthorityProtocolError(f"{field} must be a {kind.__name__} or None")


def _optional_record[T](
    value: object | None,
    factory: Callable[[object], T],
) -> T | None:
    if value is None:
        return None
    return factory(value)


def _tuple_of[T](values: Sequence[object], kind: type[T], field: str) -> tuple[T, ...]:
    items = tuple(values)
    if any(not isinstance(item, kind) for item in items):
        raise AuthorityProtocolError(f"{field} must contain {kind.__name__} values")
    return cast(tuple[T, ...], items)


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityProtocolError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityProtocolError(f"invalid {field} {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityProtocolError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityProtocolError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityProtocolError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityProtocolError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, str | bytes | bytearray):
        raise AuthorityProtocolError(f"{field} must be a sequence")
    if not isinstance(value, Sequence):
        raise AuthorityProtocolError(f"{field} must be a sequence")
    return tuple(value)


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityProtocolError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityProtocolError(f"{field} must be a positive integer")
    return value


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise AuthorityProtocolError(f"{field} must be a bool")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise AuthorityProtocolError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityProtocolError(f"{field} must have string keys")
    try:
        return cast(Mapping[str, PlainData], ensure_plain_data(dict(value)))
    except (PlainDataError, TypeError) as exc:
        raise AuthorityProtocolError(f"{field} must contain plain data") from exc


__all__ = [
    "AUTHORITY_PROTOCOL_VERSION",
    "AuthorityProtocolError",
    "AuthorityProtocolOperationKind",
    "AuthorityProtocolErrorCategory",
    "AuthorityReadinessState",
    "AuthorityProtocolVersion",
    "AuthorityProtocolMetadata",
    "AuthorityProtocolRequest",
    "AuthorityProtocolReadiness",
    "AuthorityProtocolResult",
    "AuthorityProtocolRejection",
    "AuthorityProtocolResponse",
    "accepted_authority_response",
    "rejected_authority_response",
    "protocol_versions_compatible",
]
