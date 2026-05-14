"""Public value models for run catalog APIs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from loom.state_sources import unknown_source
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .errors import CatalogValidationError


class CatalogWarningCode(StrEnum):
    """Stable machine-readable warning codes for catalog results."""

    INVALID_RUN = "invalid_run"
    UNREADABLE_RUN = "unreadable_run"
    PARTIAL_RUN = "partial_run"
    ACTIVELY_CHANGING_RUN = "actively_changing_run"
    DISAPPEARED_RUN = "disappeared_run"
    LOCAL_LIFECYCLE_UNSUPPORTED = "local_lifecycle_unsupported"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    STALE_OR_CORRUPT_CATALOG = "stale_or_corrupt_catalog"
    UNRECOVERABLE_CATALOG_ERROR = "unrecoverable_catalog_error"


class RunFilterKind(StrEnum):
    """Exact-match filter fields supported by the v8 public model contract."""

    RUN_STATUS = "run_status"
    TAG = "tag"
    CONFIG_FINGERPRINT = "config_fingerprint"
    PIPELINE_FINGERPRINT = "pipeline_fingerprint"
    GIT_COMMIT = "git_commit"
    STAGE_STATUS = "stage_status"
    ARTIFACT_IDENTITY = "artifact_identity"
    ARTIFACT_CHECKSUM = "artifact_checksum"
    EXECUTOR = "executor"
    BACKEND = "backend"


class ComparisonStatus(StrEnum):
    """Status for one metadata comparison entry."""

    SAME = "same"
    DIFFERENT = "different"
    LEFT_ONLY = "left_only"
    RIGHT_ONLY = "right_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CatalogWarning:
    """Nonfatal warning returned alongside catalog results."""

    code: CatalogWarningCode | str
    message: str
    run_uri: str | None = None
    path: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _coerce_warning_code(self.code))
        _validate_non_empty(self.message, "message")
        _validate_optional_non_empty(self.run_uri, "run_uri")
        _validate_optional_non_empty(self.path, "path")
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(self.details, path="details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": _coerce_warning_code(self.code).value,
            "message": self.message,
            "run_uri": self.run_uri,
            "path": self.path,
            "details": thaw_plain_data(self.details, path="details"),
        }


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    """Metadata-only artifact summary for one run."""

    run_uri: str
    artifact_id: str
    logical_name: str | None = None
    uri: str | None = None
    artifact_type: str | None = None
    checksum: str | None = None
    fingerprint: str | None = None
    producer_stage: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    state_source: Mapping[str, PlainData] = field(default_factory=unknown_source)

    def __post_init__(self) -> None:
        _validate_non_empty(self.run_uri, "run_uri")
        _validate_non_empty(self.artifact_id, "artifact_id")
        _validate_optional_non_empty(self.logical_name, "logical_name")
        _validate_optional_non_empty(self.uri, "uri")
        _validate_optional_non_empty(self.artifact_type, "artifact_type")
        _validate_optional_non_empty(self.checksum, "checksum")
        _validate_optional_non_empty(self.fingerprint, "fingerprint")
        _validate_optional_non_empty(self.producer_stage, "producer_stage")
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(self.metadata, path="metadata"),
        )
        object.__setattr__(
            self,
            "state_source",
            freeze_plain_data(self.state_source, path="state_source"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "artifact_id": self.artifact_id,
            "logical_name": self.logical_name,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "state_source": thaw_plain_data(self.state_source, path="state_source"),
        }


@dataclass(frozen=True, slots=True)
class StageSummary:
    """Metadata-only stage summary for one run."""

    stage_name: str
    status: str | None = None
    attempt: int | None = None
    fingerprint: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    state_source: Mapping[str, PlainData] = field(default_factory=unknown_source)

    def __post_init__(self) -> None:
        _validate_non_empty(self.stage_name, "stage_name")
        _validate_optional_non_empty(self.status, "status")
        _validate_optional_non_empty(self.fingerprint, "fingerprint")
        _validate_optional_non_empty(self.started_at, "started_at")
        _validate_optional_non_empty(self.finished_at, "finished_at")
        if self.attempt is not None and (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise CatalogValidationError("attempt must be a positive integer or None")
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(self.metadata, path="metadata"),
        )
        object.__setattr__(
            self,
            "state_source",
            freeze_plain_data(self.state_source, path="state_source"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "attempt": self.attempt,
            "fingerprint": self.fingerprint,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "state_source": thaw_plain_data(self.state_source, path="state_source"),
        }


@dataclass(frozen=True, slots=True)
class SubmittedOperationSummary:
    """Persisted submitted-operation summary selected for catalog output."""

    submission_id: str
    backend: str
    mode: str
    state: str
    created_at: str
    updated_at: str
    active: bool = False
    summary_counts: Mapping[str, int] = field(default_factory=dict)
    state_source: Mapping[str, PlainData] = field(default_factory=unknown_source)

    def __post_init__(self) -> None:
        for field_name in (
            "submission_id",
            "backend",
            "mode",
            "state",
            "created_at",
            "updated_at",
        ):
            _validate_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.active, bool):
            raise CatalogValidationError("active must be a bool")
        object.__setattr__(
            self,
            "summary_counts",
            _validate_int_mapping(self.summary_counts, "summary_counts"),
        )
        object.__setattr__(
            self,
            "state_source",
            freeze_plain_data(self.state_source, path="state_source"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "submission_id": self.submission_id,
            "backend": self.backend,
            "mode": self.mode,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active": self.active,
            "summary_counts": dict(self.summary_counts),
            "state_source": thaw_plain_data(self.state_source, path="state_source"),
        }


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Metadata-only summary for one run."""

    run_uri: str
    status: str | None = None
    display_name: str | None = None
    path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    config_fingerprint: str | None = None
    pipeline_fingerprint: str | None = None
    git_commit: str | None = None
    executor: str | None = None
    backend: str | None = None
    stages: Sequence[StageSummary] = ()
    artifacts: Sequence[ArtifactSummary] = ()
    submitted_operations: Sequence[SubmittedOperationSummary] = ()
    state_source: Mapping[str, PlainData] = field(default_factory=unknown_source)

    def __post_init__(self) -> None:
        _validate_non_empty(self.run_uri, "run_uri")
        for field_name in (
            "status",
            "display_name",
            "path",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
            "config_fingerprint",
            "pipeline_fingerprint",
            "git_commit",
            "executor",
            "backend",
        ):
            _validate_optional_non_empty(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(self.metadata, path="metadata"),
        )
        object.__setattr__(self, "tags", _validate_str_mapping(self.tags, "tags"))
        object.__setattr__(
            self, "stages", _coerce_sequence(self.stages, StageSummary, "stages")
        )
        object.__setattr__(
            self,
            "artifacts",
            _coerce_sequence(self.artifacts, ArtifactSummary, "artifacts"),
        )
        object.__setattr__(
            self,
            "submitted_operations",
            _coerce_sequence(
                self.submitted_operations,
                SubmittedOperationSummary,
                "submitted_operations",
            ),
        )
        object.__setattr__(
            self,
            "state_source",
            freeze_plain_data(self.state_source, path="state_source"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "display_name": self.display_name,
            "path": self.path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "tags": dict(self.tags),
            "config_fingerprint": self.config_fingerprint,
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "git_commit": self.git_commit,
            "executor": self.executor,
            "backend": self.backend,
            "state_source": thaw_plain_data(self.state_source, path="state_source"),
            "stages": [stage.to_dict() for stage in self.stages],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "submitted_operations": [
                operation.to_dict() for operation in self.submitted_operations
            ],
        }


@dataclass(frozen=True, slots=True)
class RunFilter:
    """One exact-match filter for run catalog listing."""

    kind: RunFilterKind | str
    value: str
    key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_filter_kind(self.kind))
        _validate_non_empty(self.value, "value")
        _validate_optional_non_empty(self.key, "key")
        if self.kind is RunFilterKind.TAG and self.key is None:
            raise CatalogValidationError("tag filters require key")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": _coerce_filter_kind(self.kind).value,
            "key": self.key,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ListRunsResult:
    """Result envelope for listing run summaries."""

    summaries: Sequence[RunSummary] = ()
    warnings: Sequence[CatalogWarning] = ()
    filters: Sequence[RunFilter] = ()
    checked_at: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_non_empty(self.checked_at, "checked_at")
        object.__setattr__(
            self, "summaries", _coerce_sequence(self.summaries, RunSummary, "summaries")
        )
        object.__setattr__(
            self,
            "warnings",
            _coerce_sequence(self.warnings, CatalogWarning, "warnings"),
        )
        object.__setattr__(
            self, "filters", _coerce_sequence(self.filters, RunFilter, "filters")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "summaries": [summary.to_dict() for summary in self.summaries],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "filters": [run_filter.to_dict() for run_filter in self.filters],
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True, slots=True)
class CatalogIndexResult:
    """Result envelope for indexing or rebuilding a catalog."""

    indexed_count: int
    skipped_count: int = 0
    warnings: Sequence[CatalogWarning] = ()
    checked_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "indexed_count", _validate_count(self.indexed_count, "indexed_count")
        )
        object.__setattr__(
            self, "skipped_count", _validate_count(self.skipped_count, "skipped_count")
        )
        _validate_optional_non_empty(self.checked_at, "checked_at")
        object.__setattr__(
            self,
            "warnings",
            _coerce_sequence(self.warnings, CatalogWarning, "warnings"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "indexed_count": self.indexed_count,
            "skipped_count": self.skipped_count,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True, slots=True)
class ComparisonEntry:
    """One metadata comparison fact."""

    key: str
    status: ComparisonStatus | str
    left: PlainData = None
    right: PlainData = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty(self.key, "key")
        object.__setattr__(self, "status", _coerce_comparison_status(self.status))
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(self.details, path="details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "key": self.key,
            "status": _coerce_comparison_status(self.status).value,
            "left": self.left,
            "right": self.right,
            "details": thaw_plain_data(self.details, path="details"),
        }


@dataclass(frozen=True, slots=True)
class ComparisonSection:
    """A named group of metadata comparison entries."""

    name: str
    entries: Sequence[ComparisonEntry] = ()

    def __post_init__(self) -> None:
        _validate_non_empty(self.name, "name")
        object.__setattr__(
            self,
            "entries",
            _coerce_sequence(self.entries, ComparisonEntry, "entries"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Metadata-only comparison result for two runs."""

    left_run_uri: str
    right_run_uri: str
    sections: Sequence[ComparisonSection] = ()
    warnings: Sequence[CatalogWarning] = ()
    checked_at: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.left_run_uri, "left_run_uri")
        _validate_non_empty(self.right_run_uri, "right_run_uri")
        _validate_optional_non_empty(self.checked_at, "checked_at")
        object.__setattr__(
            self,
            "sections",
            _coerce_sequence(self.sections, ComparisonSection, "sections"),
        )
        object.__setattr__(
            self,
            "warnings",
            _coerce_sequence(self.warnings, CatalogWarning, "warnings"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "left_run_uri": self.left_run_uri,
            "right_run_uri": self.right_run_uri,
            "sections": [section.to_dict() for section in self.sections],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "checked_at": self.checked_at,
        }


def _validate_non_empty(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise CatalogValidationError(f"{field_name} must be a non-empty string")


def _validate_optional_non_empty(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty(value, field_name)


def _non_empty(value: object, field_name: str) -> str:
    _validate_non_empty(value, field_name)
    return cast(str, value)


def _validate_count(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CatalogValidationError(f"{field_name} must be a non-negative integer")
    return value


def _validate_str_mapping(
    value: Mapping[str, str], field_name: str
) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError(f"{field_name} must be a mapping")
    output: dict[str, str] = {}
    for key, item in value.items():
        _validate_non_empty(key, f"{field_name} key")
        _validate_non_empty(item, f"{field_name}[{key!r}]")
        output[key] = item
    return MappingProxyType(output)


def _validate_int_mapping(
    value: Mapping[str, int], field_name: str
) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError(f"{field_name} must be a mapping")
    output: dict[str, int] = {}
    for key, item in value.items():
        _validate_non_empty(key, f"{field_name} key")
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise CatalogValidationError(
                f"{field_name}[{key!r}] must be a non-negative integer"
            )
        output[key] = item
    return MappingProxyType(output)


def _coerce_sequence(
    value: Sequence[object], item_type: type[Any], field_name: str
) -> tuple[Any, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise CatalogValidationError(f"{field_name} must be a sequence")
    output: list[Any] = []
    for index, item in enumerate(value):
        if not isinstance(item, item_type):
            raise CatalogValidationError(
                f"{field_name}[{index}] must be {item_type.__name__}"
            )
        output.append(item)
    return tuple(output)


def _coerce_warning_code(value: CatalogWarningCode | str) -> CatalogWarningCode:
    try:
        return CatalogWarningCode(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid warning code {value!r}") from exc


def _coerce_filter_kind(value: RunFilterKind | str) -> RunFilterKind:
    try:
        return RunFilterKind(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid filter kind {value!r}") from exc


def _coerce_comparison_status(value: ComparisonStatus | str) -> ComparisonStatus:
    try:
        return ComparisonStatus(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid comparison status {value!r}") from exc


CATALOG_WARNING_CODES: tuple[str, ...] = tuple(
    code.value for code in CatalogWarningCode
)


class RunExchangeDiagnosticSeverity(StrEnum):
    """Machine-readable exchange diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RunExchangeOperationStatus(StrEnum):
    """Result status used by exchange envelopes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


class RunBundleEntryKind(StrEnum):
    """Entry class for local bundle manifest records."""

    MANIFEST = "manifest"
    ARTIFACT = "artifact"
    PAYLOAD = "payload"
    LOG = "log"
    METADATA = "metadata"
    OTHER = "other"


class RunBundleFormatVersion(IntEnum):
    """Manifest format version identifiers."""

    V1 = 1


class RunImportResumeMode(StrEnum):
    """Resume posture for imported history or future migration support."""

    HISTORICAL_ONLY = "historical_only"
    RESUME_CANDIDATE = "resume_candidate"
    RESUME_UNSUPPORTED = "resume_unsupported"


class RunImportCollisionPolicy(StrEnum):
    """Target identity collision policy."""

    REJECT = "reject"
    OVERWRITE = "overwrite"
    REUSE = "reuse"


class RunImportChecksumPolicy(StrEnum):
    """Checksum policy for imported payloads."""

    STRICT = "strict"
    WARNING = "warning"
    IGNORE = "ignore"


class RunImportMaterializationPolicy(StrEnum):
    """Scope of materialization when importing a result."""

    METADATA_ONLY = "metadata_only"
    COMPLETE = "complete"


class RunTargetIdentityPolicyMode(StrEnum):
    """Target identity policy for imported runs."""

    TARGET_LOCAL = "target_local"
    PRESERVE_SOURCE = "preserve_source"


class TransferVerificationStatus(StrEnum):
    """Transfer verification outcome used by transfer evidence records."""

    PROVEN = "proven"
    UNPROVEN = "unproven"
    UNSUPPORTED = "unsupported"


class TransferRecordKind(StrEnum):
    """Source transport or provider identity for transfer evidence."""

    BUNDLE = "local_bundle"
    OFFLINE_EVIDENCE = "offline_evidence"
    FAKE = "fake"
    UNKNOWN = "unknown"


RUN_BUNDLE_MANIFEST_SCHEMA_VERSION = int(RunBundleFormatVersion.V1)
RUN_BUNDLE_MANIFEST_KIND = "loom.run_bundle_manifest.v1"


@dataclass(frozen=True, slots=True)
class RunExchangeDiagnostic:
    """Shared diagnostic for exchange contracts."""

    code: str
    message: str
    severity: RunExchangeDiagnosticSeverity | str = RunExchangeDiagnosticSeverity.ERROR
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty(self.code, "code"))
        object.__setattr__(
            self,
            "message",
            _non_empty(self.message, "message"),
        )
        object.__setattr__(self, "severity", _coerce_run_exchange_severity(self.severity))
        object.__setattr__(
            self,
            "details",
            _freeze_plain(self.details, "details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": RunExchangeDiagnosticSeverity(self.severity).value,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunExchangeDiagnostic":
        payload = _load_record(
            data,
            "RunExchangeDiagnostic",
            required={"code", "message", "severity"},
            optional={"details"},
        )
        return cls(
            code=cast(str, payload["code"]),
            message=cast(str, payload["message"]),
            severity=cast(RunExchangeDiagnosticSeverity, payload["severity"]),
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class RunAdapterIdentity:
    """Identity fields for a concrete exchange adapter."""

    name: str
    version: str | None = None
    kind: str = TransferRecordKind.UNKNOWN.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        object.__setattr__(
            self,
            "kind",
            _coerce_str(self.kind, "kind"),
        )
        if self.version is not None:
            object.__setattr__(self, "version", _non_empty(self.version, "version"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunAdapterIdentity":
        payload = _load_record(
            data,
            "RunAdapterIdentity",
            required={"name", "version", "kind"},
        )
        return cls(
            name=cast(str, payload["name"]),
            version=cast(str | None, payload["version"]),
            kind=cast(str, payload["kind"]),
        )


@dataclass(frozen=True, slots=True)
class PortableRunSourceIdentity:
    """Portable source identity that does not assume a provider format."""

    source_kind: str
    run_uri: str
    source_workspace_id: str | None = None
    source_authority_uri: str | None = None
    source_service_generation: str | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", _coerce_str(self.source_kind, "source_kind"))
        object.__setattr__(self, "run_uri", _non_empty(self.run_uri, "run_uri"))
        if self.source_workspace_id is not None:
            object.__setattr__(
                self,
                "source_workspace_id",
                _non_empty(self.source_workspace_id, "source_workspace_id"),
            )
        if self.source_authority_uri is not None:
            object.__setattr__(
                self,
                "source_authority_uri",
                _non_empty(self.source_authority_uri, "source_authority_uri"),
            )
        if self.source_service_generation is not None:
            object.__setattr__(
                self,
                "source_service_generation",
                _non_empty(self.source_service_generation, "source_service_generation"),
            )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "source_kind": self.source_kind,
            "run_uri": self.run_uri,
            "source_workspace_id": self.source_workspace_id,
            "source_authority_uri": self.source_authority_uri,
            "source_service_generation": self.source_service_generation,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PortableRunSourceIdentity":
        payload = _load_record(
            data,
            "PortableRunSourceIdentity",
            required={
                "source_kind",
                "run_uri",
                "source_workspace_id",
                "source_authority_uri",
                "source_service_generation",
                "extensions",
            },
        )
        return cls(
            source_kind=cast(str, payload["source_kind"]),
            run_uri=cast(str, payload["run_uri"]),
            source_workspace_id=cast(str | None, payload["source_workspace_id"]),
            source_authority_uri=cast(str | None, payload["source_authority_uri"]),
            source_service_generation=cast(
                str | None,
                payload["source_service_generation"],
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class PortableRunTargetIdentityPolicy:
    """Target identity policy for imports and exchange reads."""

    mode: RunTargetIdentityPolicyMode | str = RunTargetIdentityPolicyMode.TARGET_LOCAL
    target_workspace_id: str | None = None
    target_authority_uri: str | None = None
    target_run_uri: str | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _coerce_target_mode(self.mode))
        if self.target_workspace_id is not None:
            object.__setattr__(
                self,
                "target_workspace_id",
                _non_empty(self.target_workspace_id, "target_workspace_id"),
            )
        if self.target_authority_uri is not None:
            object.__setattr__(
                self,
                "target_authority_uri",
                _non_empty(self.target_authority_uri, "target_authority_uri"),
            )
        if self.target_run_uri is not None:
            object.__setattr__(
                self,
                "target_run_uri",
                _non_empty(self.target_run_uri, "target_run_uri"),
            )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": RunTargetIdentityPolicyMode(self.mode).value,
            "target_workspace_id": self.target_workspace_id,
            "target_authority_uri": self.target_authority_uri,
            "target_run_uri": self.target_run_uri,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PortableRunTargetIdentityPolicy":
        payload = _load_record(
            data,
            "PortableRunTargetIdentityPolicy",
            required={
                "mode",
                "target_workspace_id",
                "target_authority_uri",
                "target_run_uri",
                "extensions",
            },
        )
        return cls(
            mode=cast(RunTargetIdentityPolicyMode, payload["mode"]),
            target_workspace_id=cast(str | None, payload["target_workspace_id"]),
            target_authority_uri=cast(str | None, payload["target_authority_uri"]),
            target_run_uri=cast(str | None, payload["target_run_uri"]),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundlePayloadReference:
    """Portable pointer to one exchange payload entry."""

    entry_id: str
    uri: str
    kind: RunBundleEntryKind | str = RunBundleEntryKind.PAYLOAD
    selected: bool = True
    checksum_algorithm: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _non_empty(self.entry_id, "entry_id"))
        object.__setattr__(self, "uri", _non_empty(self.uri, "uri"))
        object.__setattr__(
            self,
            "kind",
            _coerce_bundle_kind(self.kind),
        )
        _coerce_bool(self.selected, "selected")
        if self.size_bytes is not None:
            object.__setattr__(
                self,
                "size_bytes",
                _coerce_non_negative_int(self.size_bytes, "size_bytes"),
            )
        if self.checksum_algorithm is not None:
            object.__setattr__(
                self,
                "checksum_algorithm",
                _non_empty(self.checksum_algorithm, "checksum_algorithm"),
            )
        if self.checksum is not None:
            object.__setattr__(
                self,
                "checksum",
                _non_empty(self.checksum, "checksum"),
            )
        if self.checksum_algorithm is None and self.checksum is not None:
            raise CatalogValidationError("checksum_algorithm is required when checksum is set")
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "entry_id": self.entry_id,
            "uri": self.uri,
            "kind": RunBundleEntryKind(self.kind).value,
            "selected": self.selected,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundlePayloadReference":
        payload = _load_record(
            data,
            "RunBundlePayloadReference",
            required={
                "entry_id",
                "uri",
                "kind",
                "selected",
                "checksum_algorithm",
                "checksum",
                "size_bytes",
                "extensions",
            },
        )
        return cls(
            entry_id=cast(str, payload["entry_id"]),
            uri=cast(str, payload["uri"]),
            kind=cast(RunBundleEntryKind, payload["kind"]),
            selected=cast(bool, payload["selected"]),
            checksum_algorithm=cast(str | None, payload["checksum_algorithm"]),
            checksum=cast(str | None, payload["checksum"]),
            size_bytes=cast(int | None, payload["size_bytes"]),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundleEntry:
    """Versioned record describing one manifest entry."""

    entry_name: str
    kind: RunBundleEntryKind | str
    path: str
    selected: bool = True
    checksum_algorithm: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_name", _non_empty(self.entry_name, "entry_name"))
        object.__setattr__(self, "path", _non_empty(self.path, "path"))
        object.__setattr__(
            self,
            "kind",
            _coerce_bundle_kind(self.kind),
        )
        _coerce_bool(self.selected, "selected")
        if self.size_bytes is not None:
            object.__setattr__(
                self,
                "size_bytes",
                _coerce_non_negative_int(self.size_bytes, "size_bytes"),
            )
        if self.checksum_algorithm is not None:
            object.__setattr__(
                self,
                "checksum_algorithm",
                _non_empty(self.checksum_algorithm, "checksum_algorithm"),
            )
        if self.checksum is not None:
            object.__setattr__(self, "checksum", _non_empty(self.checksum, "checksum"))
        if self.checksum_algorithm is None and self.checksum is not None:
            raise CatalogValidationError("checksum_algorithm is required when checksum is set")
        object.__setattr__(
            self,
            "metadata",
            _freeze_plain(self.metadata, "metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "entry_name": self.entry_name,
            "kind": RunBundleEntryKind(self.kind).value,
            "path": self.path,
            "selected": self.selected,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleEntry":
        payload = _load_record(
            data,
            "RunBundleEntry",
            required={
                "entry_name",
                "kind",
                "path",
                "selected",
                "checksum_algorithm",
                "checksum",
                "size_bytes",
                "metadata",
            },
        )
        return cls(
            entry_name=cast(str, payload["entry_name"]),
            kind=cast(RunBundleEntryKind, payload["kind"]),
            path=cast(str, payload["path"]),
            selected=cast(bool, payload["selected"]),
            checksum_algorithm=cast(str | None, payload["checksum_algorithm"]),
            checksum=cast(str | None, payload["checksum"]),
            size_bytes=cast(int | None, payload["size_bytes"]),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundlePayloadSelection:
    """Payload-selection request metadata for a bundle manifest."""

    include_artifacts: bool = False
    include_logs: bool = False
    include_workspace: bool = False
    include_other: bool = False
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _coerce_bool(self.include_artifacts, "include_artifacts")
        _coerce_bool(self.include_logs, "include_logs")
        _coerce_bool(self.include_workspace, "include_workspace")
        _coerce_bool(self.include_other, "include_other")
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "include_artifacts": self.include_artifacts,
            "include_logs": self.include_logs,
            "include_workspace": self.include_workspace,
            "include_other": self.include_other,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundlePayloadSelection":
        payload = _load_record(
            data,
            "RunBundlePayloadSelection",
            required={
                "include_artifacts",
                "include_logs",
                "include_workspace",
                "include_other",
                "extensions",
            },
        )
        return cls(
            include_artifacts=cast(bool, payload["include_artifacts"]),
            include_logs=cast(bool, payload["include_logs"]),
            include_workspace=cast(bool, payload["include_workspace"]),
            include_other=cast(bool, payload["include_other"]),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundleManifest:
    """Strict manifest record for local bundle adapters."""

    run_uri: str
    source_identity: PortableRunSourceIdentity
    target_identity: PortableRunTargetIdentityPolicy
    schema_version: int = RUN_BUNDLE_MANIFEST_SCHEMA_VERSION
    kind: str = RUN_BUNDLE_MANIFEST_KIND
    format_version: int = int(RunBundleFormatVersion.V1)
    entries: Sequence[RunBundleEntry] = ()
    payload_refs: Sequence[RunBundlePayloadReference] = ()
    payload_selection: RunBundlePayloadSelection = field(
        default_factory=RunBundlePayloadSelection
    )
    checksums: Mapping[str, str] = field(default_factory=dict)
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    warnings: Sequence[RunExchangeDiagnostic] = ()
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind != RUN_BUNDLE_MANIFEST_KIND:
            raise CatalogValidationError(
                f"RunBundleManifest.kind must be {RUN_BUNDLE_MANIFEST_KIND!r}"
            )
        _validate_manifest_version(self.schema_version)
        if not isinstance(self.format_version, int) or isinstance(self.format_version, bool):
            raise CatalogValidationError("format_version must be an integer")
        if self.format_version <= 0:
            raise CatalogValidationError("format_version must be positive")
        if self.format_version != int(RunBundleFormatVersion.V1):
            raise CatalogValidationError("unsupported format_version")
        object.__setattr__(self, "run_uri", _non_empty(self.run_uri, "run_uri"))
        if not isinstance(self.source_identity, PortableRunSourceIdentity):
            raise CatalogValidationError("source_identity must be PortableRunSourceIdentity")
        if not isinstance(self.target_identity, PortableRunTargetIdentityPolicy):
            raise CatalogValidationError("target_identity must be PortableRunTargetIdentityPolicy")
        object.__setattr__(
            self,
            "entries",
            _coerce_sequence(self.entries, RunBundleEntry, "entries"),
        )
        object.__setattr__(
            self,
            "payload_refs",
            _coerce_sequence(self.payload_refs, RunBundlePayloadReference, "payload_refs"),
        )
        object.__setattr__(
            self,
            "payload_selection",
            _coerce_payload_selection(self.payload_selection),
        )
        object.__setattr__(
            self,
            "checksums",
            _validate_str_mapping(cast(Mapping[str, str], self.checksums), "checksums"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        object.__setattr__(
            self,
            "warnings",
            _coerce_sequence(self.warnings, RunExchangeDiagnostic, "warnings"),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "format_version": self.format_version,
            "run_uri": self.run_uri,
            "source_identity": self.source_identity.to_dict(),
            "target_identity": self.target_identity.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
            "payload_refs": [ref.to_dict() for ref in self.payload_refs],
            "payload_selection": self.payload_selection.to_dict(),
            "checksums": dict(self.checksums),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleManifest":
        payload = _load_record(
            data,
            "RunBundleManifest",
            required={
                "schema_version",
                "kind",
                "format_version",
                "run_uri",
                "source_identity",
                "target_identity",
                "entries",
                "payload_refs",
                "payload_selection",
            },
            optional={
                "checksums",
                "diagnostics",
                "warnings",
                "extensions",
            },
        )
        return cls(
            schema_version=cast(int, payload["schema_version"]),
            kind=cast(str, payload["kind"]),
            format_version=cast(int, payload["format_version"]),
            run_uri=cast(str, payload["run_uri"]),
            source_identity=PortableRunSourceIdentity.from_dict(
                payload["source_identity"]
            ),
            target_identity=PortableRunTargetIdentityPolicy.from_dict(
                payload["target_identity"]
            ),
            entries=tuple(
                RunBundleEntry.from_dict(item) for item in cast(tuple[object, ...] | list[object], payload["entries"])
            ),
            payload_refs=tuple(
                RunBundlePayloadReference.from_dict(item)
                for item in cast(tuple[object, ...] | list[object], payload["payload_refs"])
            ),
            payload_selection=RunBundlePayloadSelection.from_dict(
                payload["payload_selection"]
            ),
            checksums=cast(Mapping[str, str], payload.get("checksums", {})),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(tuple[object, ...] | list[object], payload.get("diagnostics", ()))
            ),
            warnings=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(tuple[object, ...] | list[object], payload.get("warnings", ()))
            ),
            extensions=cast(Mapping[str, PlainData], payload.get("extensions", {})),
        )


@dataclass(frozen=True, slots=True)
class PortableRunExportRecord:
    """Adapter-neutral exchange record for export operations."""

    source_identity: PortableRunSourceIdentity
    adapter: RunAdapterIdentity
    selected_payload_refs: Sequence[RunBundlePayloadReference] = ()
    target_identity: PortableRunTargetIdentityPolicy = field(
        default_factory=PortableRunTargetIdentityPolicy
    )
    manifest: RunBundleManifest | None = None
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, PortableRunSourceIdentity):
            raise CatalogValidationError(
                "source_identity must be PortableRunSourceIdentity"
            )
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        object.__setattr__(
            self,
            "selected_payload_refs",
            _coerce_sequence(
                self.selected_payload_refs,
                RunBundlePayloadReference,
                "selected_payload_refs",
            ),
        )
        object.__setattr__(
            self,
            "target_identity",
            _coerce_target_identity_policy(self.target_identity),
        )
        if self.manifest is not None and not isinstance(self.manifest, RunBundleManifest):
            raise CatalogValidationError("manifest must be RunBundleManifest or None")
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "source_identity": self.source_identity.to_dict(),
            "adapter": self.adapter.to_dict(),
            "selected_payload_refs": [
                payload_ref.to_dict() for payload_ref in self.selected_payload_refs
            ],
            "target_identity": self.target_identity.to_dict(),
            "manifest": None if self.manifest is None else self.manifest.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PortableRunExportRecord":
        payload = _load_record(
            data,
            "PortableRunExportRecord",
            required={
                "source_identity",
                "adapter",
                "selected_payload_refs",
                "target_identity",
                "manifest",
                "diagnostics",
                "extensions",
            },
        )
        return cls(
            source_identity=PortableRunSourceIdentity.from_dict(
                payload["source_identity"]
            ),
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            selected_payload_refs=tuple(
                RunBundlePayloadReference.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["selected_payload_refs"]
                )
            ),
            target_identity=PortableRunTargetIdentityPolicy.from_dict(
                payload["target_identity"]
            ),
            manifest=None
            if payload["manifest"] is None
            else RunBundleManifest.from_dict(payload["manifest"]),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class PortableRunImportRecord:
    """Adapter-neutral exchange record for import operations."""

    source_identity: PortableRunSourceIdentity
    adapter: RunAdapterIdentity
    manifest: RunBundleManifest
    selected_payload_refs: Sequence[RunBundlePayloadReference] = ()
    target_identity: PortableRunTargetIdentityPolicy = field(
        default_factory=PortableRunTargetIdentityPolicy
    )
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, PortableRunSourceIdentity):
            raise CatalogValidationError(
                "source_identity must be PortableRunSourceIdentity"
            )
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        if not isinstance(self.manifest, RunBundleManifest):
            raise CatalogValidationError("manifest must be RunBundleManifest")
        object.__setattr__(
            self,
            "selected_payload_refs",
            _coerce_sequence(
                self.selected_payload_refs,
                RunBundlePayloadReference,
                "selected_payload_refs",
            ),
        )
        object.__setattr__(
            self,
            "target_identity",
            _coerce_target_identity_policy(self.target_identity),
        )
        object.__setattr__(
            self,
            "provenance",
            _freeze_plain(self.provenance, "provenance"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "source_identity": self.source_identity.to_dict(),
            "adapter": self.adapter.to_dict(),
            "manifest": self.manifest.to_dict(),
            "selected_payload_refs": [
                payload_ref.to_dict() for payload_ref in self.selected_payload_refs
            ],
            "target_identity": self.target_identity.to_dict(),
            "provenance": thaw_plain_data(self.provenance, path="provenance"),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PortableRunImportRecord":
        payload = _load_record(
            data,
            "PortableRunImportRecord",
            required={
                "source_identity",
                "adapter",
                "manifest",
                "selected_payload_refs",
                "target_identity",
                "provenance",
                "diagnostics",
                "extensions",
            },
        )
        return cls(
            source_identity=PortableRunSourceIdentity.from_dict(
                payload["source_identity"]
            ),
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            manifest=RunBundleManifest.from_dict(payload["manifest"]),
            selected_payload_refs=tuple(
                RunBundlePayloadReference.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["selected_payload_refs"]
                )
            ),
            target_identity=PortableRunTargetIdentityPolicy.from_dict(
                payload["target_identity"]
            ),
            provenance=cast(Mapping[str, PlainData], payload["provenance"]),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundleExportOptions:
    """Options controlling bundle export behavior and selection."""

    include_payloads: bool = False
    include_logs: bool = False
    include_workspace: bool = False
    include_non_terminal_runs: bool = False
    verify_checksums: bool = False
    max_payload_count: int | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _coerce_bool(self.include_payloads, "include_payloads")
        _coerce_bool(self.include_logs, "include_logs")
        _coerce_bool(self.include_workspace, "include_workspace")
        _coerce_bool(self.include_non_terminal_runs, "include_non_terminal_runs")
        _coerce_bool(self.verify_checksums, "verify_checksums")
        if self.max_payload_count is not None:
            object.__setattr__(
                self,
                "max_payload_count",
                _coerce_positive_int(self.max_payload_count, "max_payload_count"),
            )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "include_payloads": self.include_payloads,
            "include_logs": self.include_logs,
            "include_workspace": self.include_workspace,
            "include_non_terminal_runs": self.include_non_terminal_runs,
            "verify_checksums": self.verify_checksums,
            "max_payload_count": self.max_payload_count,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleExportOptions":
        payload = _load_record(
            data,
            "RunBundleExportOptions",
            required={
                "include_payloads",
                "include_logs",
                "include_workspace",
                "include_non_terminal_runs",
                "verify_checksums",
                "max_payload_count",
                "extensions",
            },
        )
        return cls(
            include_payloads=cast(bool, payload["include_payloads"]),
            include_logs=cast(bool, payload["include_logs"]),
            include_workspace=cast(bool, payload["include_workspace"]),
            include_non_terminal_runs=cast(
                bool,
                payload["include_non_terminal_runs"],
            ),
            verify_checksums=cast(bool, payload["verify_checksums"]),
            max_payload_count=cast(int | None, payload["max_payload_count"]),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundleImportPolicy:
    """Import policy attached to adapter-neutral import records."""

    collision_policy: RunImportCollisionPolicy | str = RunImportCollisionPolicy.REJECT
    checksum_policy: RunImportChecksumPolicy | str = RunImportChecksumPolicy.STRICT
    materialization_policy: RunImportMaterializationPolicy | str = RunImportMaterializationPolicy.COMPLETE
    resume_mode: RunImportResumeMode | str = RunImportResumeMode.HISTORICAL_ONLY
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "collision_policy",
            _coerce_collision_policy(self.collision_policy),
        )
        object.__setattr__(
            self,
            "checksum_policy",
            _coerce_checksum_policy(self.checksum_policy),
        )
        object.__setattr__(
            self,
            "materialization_policy",
            _coerce_materialization_policy(self.materialization_policy),
        )
        object.__setattr__(
            self,
            "resume_mode",
            _coerce_resume_mode(self.resume_mode),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "collision_policy": RunImportCollisionPolicy(self.collision_policy).value,
            "checksum_policy": RunImportChecksumPolicy(self.checksum_policy).value,
            "materialization_policy": RunImportMaterializationPolicy(
                self.materialization_policy
            ).value,
            "resume_mode": RunImportResumeMode(self.resume_mode).value,
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleImportPolicy":
        payload = _load_record(
            data,
            "RunBundleImportPolicy",
            required={
                "collision_policy",
                "checksum_policy",
                "materialization_policy",
                "resume_mode",
                "extensions",
            },
        )
        return cls(
            collision_policy=cast(RunImportCollisionPolicy, payload["collision_policy"]),
            checksum_policy=cast(RunImportChecksumPolicy, payload["checksum_policy"]),
            materialization_policy=cast(
                RunImportMaterializationPolicy,
                payload["materialization_policy"],
            ),
            resume_mode=cast(RunImportResumeMode, payload["resume_mode"]),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class TransferVerificationCheck:
    """Per-check transfer verification fact."""

    name: str
    status: TransferVerificationStatus | str
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        object.__setattr__(
            self,
            "status",
            _coerce_transfer_verification_status(self.status),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty(self.message, "message"),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain(self.details, "details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "status": TransferVerificationStatus(self.status).value,
            "message": self.message,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TransferVerificationCheck":
        payload = _load_record(
            data,
            "TransferVerificationCheck",
            required={"name", "status", "message"},
            optional={"details"},
        )
        return cls(
            name=cast(str, payload["name"]),
            status=cast(TransferVerificationStatus, payload["status"]),
            message=cast(str, payload["message"]),
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class TransferVerificationRecord:
    """Transfer evidence envelope."""

    adapter: RunAdapterIdentity
    status: TransferVerificationStatus | str = TransferVerificationStatus.UNPROVEN
    checks: Sequence[TransferVerificationCheck] = ()
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        object.__setattr__(
            self,
            "status",
            _coerce_transfer_verification_status(self.status),
        )
        object.__setattr__(
            self,
            "checks",
            _coerce_sequence(self.checks, TransferVerificationCheck, "checks"),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain(self.details, "details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "adapter": self.adapter.to_dict(),
            "status": TransferVerificationStatus(self.status).value,
            "checks": [check.to_dict() for check in self.checks],
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TransferVerificationRecord":
        payload = _load_record(
            data,
            "TransferVerificationRecord",
            required={"adapter", "status", "checks", "details"},
        )
        return cls(
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            status=cast(TransferVerificationStatus, payload["status"]),
            checks=tuple(
                TransferVerificationCheck.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["checks"]
                )
            ),
            details=cast(Mapping[str, PlainData], payload["details"]),
        )


class MigrationReadinessBlockerCode(StrEnum):
    """Machine-readable import readiness blocker codes."""

    UNSUPPORTED_SOURCE_SCHEMA = "unsupported_source_schema"
    UNSUPPORTED_TARGET_SCHEMA = "unsupported_target_schema"
    RUN_URI_COLLISION = "run_uri_collision"
    UNREBASED_ARTIFACT_URI = "unrebaseable_artifact_uri"
    MISSING_PAYLOAD = "missing_payload"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    TARGET_STORE_UNAVAILABLE = "target_store_unavailable"
    HISTORICAL_ONLY_POLICY = "historical_only_policy"
    NON_TERMINAL_SOURCE = "non_terminal_source"


@dataclass(frozen=True, slots=True)
class MigrationReadinessBlocker:
    """Single blocker with machine-readable identity facts."""

    code: MigrationReadinessBlockerCode | str
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _coerce_readiness_blocker_code(self.code))
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        object.__setattr__(
            self,
            "details",
            _freeze_plain(self.details, "details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": MigrationReadinessBlockerCode(self.code).value,
            "message": self.message,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "MigrationReadinessBlocker":
        payload = _load_record(
            data,
            "MigrationReadinessBlocker",
            required={"code", "message"},
            optional={"details"},
        )
        return cls(
            code=cast(MigrationReadinessBlockerCode, payload["code"]),
            message=cast(str, payload["message"]),
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class MigrationResumeReadiness:
    """Resume-readiness facts for imported history."""

    mode: RunImportResumeMode | str = RunImportResumeMode.HISTORICAL_ONLY
    blockers: Sequence[MigrationReadinessBlocker] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _coerce_resume_mode(self.mode))
        object.__setattr__(
            self,
            "blockers",
            _coerce_sequence(self.blockers, MigrationReadinessBlocker, "blockers"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": RunImportResumeMode(self.mode).value,
            "blockers": [blocker.to_dict() for blocker in self.blockers],
        }

    @classmethod
    def from_dict(cls, data: object) -> "MigrationResumeReadiness":
        payload = _load_record(
            data,
            "MigrationResumeReadiness",
            required={"mode", "blockers"},
        )
        return cls(
            mode=cast(RunImportResumeMode, payload["mode"]),
            blockers=tuple(
                MigrationReadinessBlocker.from_dict(item)
                for item in cast(tuple[object, ...] | list[object], payload["blockers"])
            ),
        )


@dataclass(frozen=True, slots=True)
class RunBundleExportResult:
    """Shared export result envelope for all providers."""

    status: RunExchangeOperationStatus | str
    adapter: RunAdapterIdentity
    manifest: RunBundleManifest | None = None
    exported_payload_count: int = 0
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    transfer_verification: TransferVerificationRecord | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_exchange_status(self.status),
        )
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        if self.manifest is not None and not isinstance(self.manifest, RunBundleManifest):
            raise CatalogValidationError("manifest must be RunBundleManifest or None")
        if not isinstance(self.exported_payload_count, int) or isinstance(self.exported_payload_count, bool) or self.exported_payload_count < 0:
            raise CatalogValidationError(
                "exported_payload_count must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        if self.transfer_verification is not None and not isinstance(
            self.transfer_verification, TransferVerificationRecord
        ):
            raise CatalogValidationError("transfer_verification must be TransferVerificationRecord or None")
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": RunExchangeOperationStatus(self.status).value,
            "adapter": self.adapter.to_dict(),
            "manifest": None if self.manifest is None else self.manifest.to_dict(),
            "exported_payload_count": self.exported_payload_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "transfer_verification": None
            if self.transfer_verification is None
            else self.transfer_verification.to_dict(),
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleExportResult":
        payload = _load_record(
            data,
            "RunBundleExportResult",
            required={
                "status",
                "adapter",
                "manifest",
                "exported_payload_count",
                "diagnostics",
                "transfer_verification",
                "extensions",
            },
        )
        return cls(
            status=cast(RunExchangeOperationStatus, payload["status"]),
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            manifest=None
            if payload["manifest"] is None
            else RunBundleManifest.from_dict(payload["manifest"]),
            exported_payload_count=cast(int, payload["exported_payload_count"]),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            transfer_verification=(
                None
                if payload["transfer_verification"] is None
                else TransferVerificationRecord.from_dict(
                    payload["transfer_verification"]
                )
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


RunExportResult = RunBundleExportResult


@dataclass(frozen=True, slots=True)
class RunBundleInspection:
    """Result from inspecting a bundle manifest and payload-selection metadata."""

    status: RunExchangeOperationStatus | str
    manifest: RunBundleManifest
    included_payload_count: int
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    transfer_verification: TransferVerificationRecord | None = None
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_exchange_status(self.status),
        )
        if not isinstance(self.manifest, RunBundleManifest):
            raise CatalogValidationError("manifest must be RunBundleManifest")
        object.__setattr__(
            self,
            "included_payload_count",
            _coerce_non_negative_int(self.included_payload_count, "included_payload_count"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        if self.transfer_verification is not None and not isinstance(
            self.transfer_verification, TransferVerificationRecord
        ):
            raise CatalogValidationError("transfer_verification must be TransferVerificationRecord or None")
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": RunExchangeOperationStatus(self.status).value,
            "manifest": self.manifest.to_dict(),
            "included_payload_count": self.included_payload_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "transfer_verification": None
            if self.transfer_verification is None
            else self.transfer_verification.to_dict(),
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleInspection":
        payload = _load_record(
            data,
            "RunBundleInspection",
            required={
                "status",
                "manifest",
                "included_payload_count",
                "diagnostics",
                "transfer_verification",
                "extensions",
            },
        )
        return cls(
            status=cast(RunExchangeOperationStatus, payload["status"]),
            manifest=RunBundleManifest.from_dict(payload["manifest"]),
            included_payload_count=cast(int, payload["included_payload_count"]),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            transfer_verification=(
                None
                if payload["transfer_verification"] is None
                else TransferVerificationRecord.from_dict(
                    payload["transfer_verification"]
                )
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@dataclass(frozen=True, slots=True)
class RunBundleImportResult:
    """Shared import result envelope with readiness hints."""

    status: RunExchangeOperationStatus | str
    source_identity: PortableRunSourceIdentity
    adapter: RunAdapterIdentity
    target_run_uri: str | None
    imported_entry_count: int
    imported_payload_count: int
    readiness: MigrationResumeReadiness
    transfer_verification: TransferVerificationRecord | None = None
    imported_source_payload_refs: Sequence[RunBundlePayloadReference] = ()
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    import_provenance: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_exchange_status(self.status),
        )
        if not isinstance(self.source_identity, PortableRunSourceIdentity):
            raise CatalogValidationError("source_identity must be PortableRunSourceIdentity")
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        if self.target_run_uri is not None:
            object.__setattr__(
                self,
                "target_run_uri",
                _non_empty(self.target_run_uri, "target_run_uri"),
            )
        object.__setattr__(
            self,
            "imported_entry_count",
            _coerce_non_negative_int(self.imported_entry_count, "imported_entry_count"),
        )
        object.__setattr__(
            self,
            "imported_payload_count",
            _coerce_non_negative_int(self.imported_payload_count, "imported_payload_count"),
        )
        if not isinstance(self.readiness, MigrationResumeReadiness):
            raise CatalogValidationError("readiness must be MigrationResumeReadiness")
        object.__setattr__(
            self,
            "imported_source_payload_refs",
            _coerce_sequence(
                self.imported_source_payload_refs,
                RunBundlePayloadReference,
                "imported_source_payload_refs",
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        object.__setattr__(
            self,
            "import_provenance",
            _freeze_plain(self.import_provenance, "import_provenance"),
        )
        if self.transfer_verification is not None and not isinstance(
            self.transfer_verification, TransferVerificationRecord
        ):
            raise CatalogValidationError("transfer_verification must be TransferVerificationRecord or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": RunExchangeOperationStatus(self.status).value,
            "source_identity": self.source_identity.to_dict(),
            "adapter": self.adapter.to_dict(),
            "target_run_uri": self.target_run_uri,
            "imported_entry_count": self.imported_entry_count,
            "imported_payload_count": self.imported_payload_count,
            "readiness": self.readiness.to_dict(),
            "transfer_verification": None
            if self.transfer_verification is None
            else self.transfer_verification.to_dict(),
            "imported_source_payload_refs": [
                payload_ref.to_dict()
                for payload_ref in self.imported_source_payload_refs
            ],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "import_provenance": thaw_plain_data(
                self.import_provenance,
                path="import_provenance",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunBundleImportResult":
        payload = _load_record(
            data,
            "RunBundleImportResult",
            required={
                "status",
                "source_identity",
                "adapter",
                "target_run_uri",
                "imported_entry_count",
                "imported_payload_count",
                "readiness",
                "transfer_verification",
                "imported_source_payload_refs",
                "diagnostics",
                "import_provenance",
            },
        )
        return cls(
            status=cast(RunExchangeOperationStatus, payload["status"]),
            source_identity=PortableRunSourceIdentity.from_dict(
                payload["source_identity"]
            ),
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            target_run_uri=cast(str | None, payload["target_run_uri"]),
            imported_entry_count=cast(int, payload["imported_entry_count"]),
            imported_payload_count=cast(int, payload["imported_payload_count"]),
            readiness=MigrationResumeReadiness.from_dict(payload["readiness"]),
            transfer_verification=(
                None
                if payload["transfer_verification"] is None
                else TransferVerificationRecord.from_dict(
                    payload["transfer_verification"]
                )
            ),
            imported_source_payload_refs=tuple(
                RunBundlePayloadReference.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["imported_source_payload_refs"]
                )
            ),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            import_provenance=cast(Mapping[str, PlainData], payload["import_provenance"]),
        )


RunImportResult = RunBundleImportResult


@dataclass(frozen=True, slots=True)
class UnsupportedTransferRecord:
    """Compatibility record when an unsupported provider or path is requested."""

    adapter: RunAdapterIdentity
    reason: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, RunAdapterIdentity):
            raise CatalogValidationError("adapter must be RunAdapterIdentity")
        object.__setattr__(self, "reason", _non_empty(self.reason, "reason"))
        object.__setattr__(self, "detail", _freeze_plain(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "adapter": self.adapter.to_dict(),
            "reason": self.reason,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "UnsupportedTransferRecord":
        payload = _load_record(
            data,
            "UnsupportedTransferRecord",
            required={"adapter", "reason", "detail"},
        )
        return cls(
            adapter=RunAdapterIdentity.from_dict(payload["adapter"]),
            reason=cast(str, payload["reason"]),
            detail=cast(Mapping[str, PlainData], payload["detail"]),
        )


@dataclass(frozen=True, slots=True)
class RunExchangeEnvelope:
    """General envelope shared by helper compatibility shims."""

    status: RunExchangeOperationStatus | str
    diagnostics: Sequence[RunExchangeDiagnostic] = ()
    extensions: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_exchange_status(self.status),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_sequence(self.diagnostics, RunExchangeDiagnostic, "diagnostics"),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_plain(self.extensions, "extensions"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": RunExchangeOperationStatus(self.status).value,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "extensions": thaw_plain_data(self.extensions, path="extensions"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunExchangeEnvelope":
        payload = _load_record(
            data,
            "RunExchangeEnvelope",
            required={"status", "diagnostics", "extensions"},
        )
        return cls(
            status=cast(RunExchangeOperationStatus, payload["status"]),
            diagnostics=tuple(
                RunExchangeDiagnostic.from_dict(item)
                for item in cast(
                    tuple[object, ...] | list[object], payload["diagnostics"]
                )
            ),
            extensions=cast(Mapping[str, PlainData], payload["extensions"]),
        )


@runtime_checkable
class RunExporter(Protocol):
    """Minimal adapter contract for exporting portable run records."""

    adapter: RunAdapterIdentity

    def export(
        self,
        record: PortableRunExportRecord,
        *,
        options: RunBundleExportOptions | None = None,
    ) -> RunBundleExportResult: ...


@runtime_checkable
class RunImporter(Protocol):
    """Minimal adapter contract for importing portable run records."""

    adapter: RunAdapterIdentity

    def inspect(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleInspection: ...

    def import_record(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleImportResult: ...


def _coerce_target_identity_policy(
    value: PortableRunTargetIdentityPolicy,
) -> PortableRunTargetIdentityPolicy:
    if isinstance(value, PortableRunTargetIdentityPolicy):
        return value
    raise CatalogValidationError("target_identity must be PortableRunTargetIdentityPolicy")


def _coerce_exchange_status(
    value: RunExchangeOperationStatus | str,
) -> RunExchangeOperationStatus:
    try:
        return RunExchangeOperationStatus(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid operation status {value!r}") from exc


def _coerce_run_exchange_severity(
    value: RunExchangeDiagnosticSeverity | str,
) -> RunExchangeDiagnosticSeverity:
    try:
        return RunExchangeDiagnosticSeverity(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid diagnostic severity {value!r}") from exc


def _coerce_bundle_kind(value: RunBundleEntryKind | str) -> RunBundleEntryKind:
    try:
        return RunBundleEntryKind(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid bundle kind {value!r}") from exc


def _coerce_target_mode(
    value: RunTargetIdentityPolicyMode | str,
) -> RunTargetIdentityPolicyMode:
    try:
        return RunTargetIdentityPolicyMode(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid target identity mode {value!r}") from exc


def _coerce_str(value: object, field_name: str) -> str:
    _ = _non_empty(value, field_name)
    return cast(str, _)


def _coerce_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogValidationError(f"{field_name} must be a boolean")
    return value


def _coerce_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CatalogValidationError(f"{field_name} must be a positive integer")
    return value


def _coerce_non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CatalogValidationError(f"{field_name} must be a non-negative integer")
    return value


def _coerce_payload_selection(
    value: RunBundlePayloadSelection,
) -> RunBundlePayloadSelection:
    if isinstance(value, RunBundlePayloadSelection):
        return value
    raise CatalogValidationError("payload_selection must be RunBundlePayloadSelection")


def _coerce_collision_policy(
    value: RunImportCollisionPolicy | str,
) -> RunImportCollisionPolicy:
    try:
        return RunImportCollisionPolicy(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid collision policy {value!r}") from exc


def _coerce_checksum_policy(
    value: RunImportChecksumPolicy | str,
) -> RunImportChecksumPolicy:
    try:
        return RunImportChecksumPolicy(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid checksum policy {value!r}") from exc


def _coerce_materialization_policy(
    value: RunImportMaterializationPolicy | str,
) -> RunImportMaterializationPolicy:
    try:
        return RunImportMaterializationPolicy(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid materialization policy {value!r}") from exc


def _coerce_resume_mode(value: RunImportResumeMode | str) -> RunImportResumeMode:
    try:
        return RunImportResumeMode(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid resume mode {value!r}") from exc


def _coerce_readiness_blocker_code(
    value: MigrationReadinessBlockerCode | str,
) -> MigrationReadinessBlockerCode:
    try:
        return MigrationReadinessBlockerCode(value)
    except ValueError as exc:
        raise CatalogValidationError(f"invalid readiness blocker code {value!r}") from exc


def _coerce_transfer_verification_status(
    value: TransferVerificationStatus | str,
) -> TransferVerificationStatus:
    try:
        return TransferVerificationStatus(value)
    except ValueError as exc:
        raise CatalogValidationError(
            f"invalid transfer verification status {value!r}"
        ) from exc


def _coerce_strict_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CatalogValidationError(f"{field_name} must be an integer")
    if value <= 0:
        raise CatalogValidationError(f"{field_name} must be positive")
    return value


def _validate_manifest_version(value: object) -> None:
    value_i = _coerce_strict_int(value, "schema_version")
    if value_i != RUN_BUNDLE_MANIFEST_SCHEMA_VERSION:
        raise CatalogValidationError(
            f"unsupported manifest schema_version {value_i}, expected {RUN_BUNDLE_MANIFEST_SCHEMA_VERSION}"
        )


def _freeze_plain(value: object, field_name: str) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=field_name)
    except Exception as exc:
        raise CatalogValidationError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise CatalogValidationError(f"{field_name} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _load_record(
    data: object,
    record_name: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, object]:
    try:
        payload = cast(Mapping[str, object], cast(Mapping[str, object], data))
    except Exception as exc:
        raise CatalogValidationError(f"{record_name}.from_dict expects mapping") from exc
    if not isinstance(payload, Mapping):
        raise CatalogValidationError(f"{record_name}.from_dict expects mapping")
    all_fields = set(payload)
    optional_fields = optional or set()
    if not required.issubset(all_fields):
        missing = ", ".join(sorted(required - all_fields))
        raise CatalogValidationError(f"{record_name}.from_dict missing field(s): {missing}")
    extra = all_fields - required - optional_fields
    if extra:
        extra_fields = ", ".join(sorted(extra))
        raise CatalogValidationError(f"{record_name}.from_dict unknown field(s): {extra_fields}")
    return dict(payload)


def _coerce_strict_sequence_to_object(value: object, item_type: type[Any], field_name: str) -> tuple[Any, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise CatalogValidationError(f"{field_name} must be a sequence")
    output: list[Any] = []
    for idx, item in enumerate(value):
        if not isinstance(item, item_type):
            raise CatalogValidationError(
                f"{field_name}[{idx}] must be {item_type.__name__}"
            )
        output.append(item)
    return tuple(output)


__all__ = [
    "CATALOG_WARNING_CODES",
    "ArtifactSummary",
    "CatalogIndexResult",
    "CatalogWarning",
    "CatalogWarningCode",
    "ComparisonEntry",
    "ComparisonSection",
    "ComparisonStatus",
    "ListRunsResult",
    "MigrationReadinessBlocker",
    "MigrationReadinessBlockerCode",
    "MigrationResumeReadiness",
    "PortableRunExportRecord",
    "PortableRunImportRecord",
    "PortableRunSourceIdentity",
    "PortableRunTargetIdentityPolicy",
    "RUN_BUNDLE_MANIFEST_KIND",
    "RUN_BUNDLE_MANIFEST_SCHEMA_VERSION",
    "RunAdapterIdentity",
    "RunBundleEntry",
    "RunBundleEntryKind",
    "RunBundleExportOptions",
    "RunBundleExportResult",
    "RunBundleFormatVersion",
    "RunBundleImportPolicy",
    "RunBundleInspection",
    "RunBundleImportResult",
    "RunBundleManifest",
    "RunBundlePayloadReference",
    "RunBundlePayloadSelection",
    "RunExchangeDiagnostic",
    "RunExchangeDiagnosticSeverity",
    "RunExchangeEnvelope",
    "RunExchangeOperationStatus",
    "RunExportResult",
    "RunImportCollisionPolicy",
    "RunImportChecksumPolicy",
    "RunImportMaterializationPolicy",
    "RunImportResult",
    "RunImportResumeMode",
    "RunExporter",
    "RunImporter",
    "RunTargetIdentityPolicyMode",
    "RunComparison",
    "RunFilter",
    "RunFilterKind",
    "RunSummary",
    "StageSummary",
    "SubmittedOperationSummary",
    "TransferRecordKind",
    "TransferVerificationCheck",
    "TransferVerificationRecord",
    "TransferVerificationStatus",
    "UnsupportedTransferRecord",
]
