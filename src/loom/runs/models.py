"""Public value models for run catalog APIs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

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

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "attempt": self.attempt,
            "fingerprint": self.fingerprint,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
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


__all__ = [
    "ArtifactSummary",
    "CATALOG_WARNING_CODES",
    "CatalogIndexResult",
    "CatalogWarning",
    "CatalogWarningCode",
    "ComparisonEntry",
    "ComparisonSection",
    "ComparisonStatus",
    "ListRunsResult",
    "RunComparison",
    "RunFilter",
    "RunFilterKind",
    "RunSummary",
    "StageSummary",
    "SubmittedOperationSummary",
]
