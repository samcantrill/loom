"""Collection-level cleanup aggregation over per-run cleanup APIs."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

from loom.pipeline.cleanup.errors import CleanupError
from loom.pipeline.cleanup.execution import execute_cleanup
from loom.pipeline.cleanup.planning import plan_cleanup
from loom.pipeline.cleanup.records import (
    CLEANUP_RECORD_SCHEMA_VERSION,
    CleanupDeleteIntent,
    CleanupManagedRoot,
    CleanupReport,
    CleanupReportEntryStatus,
    CleanupResultOutcome,
)
from loom.pipeline.cleanup.selectors import CleanupSelector
from loom.pipeline.execution.eventing import RuntimeEventDispatcher
from loom.pipeline.stores import CleanupResultFact, PerRunAuthorityStore
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp, utc_timestamp


@dataclass(frozen=True, slots=True)
class CollectionCleanupTarget:
    """One discovered run target for collection cleanup orchestration."""

    run_uri: str
    store: PerRunAuthorityStore
    managed_roots: Iterable[CleanupManagedRoot] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        if self.store is None:
            raise CleanupError("store must not be None")
        object.__setattr__(
            self,
            "managed_roots",
            _managed_roots(self.managed_roots, "managed_roots"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class CollectionCleanupReport:
    """Aggregate dry-run report for candidate-level collection GC."""

    collection_id: str
    created_at: str
    reports: tuple[CleanupReport, ...] = ()
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    selector: Mapping[str, PlainData] = field(default_factory=dict)
    summary: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "collection_id",
            _non_empty_string(self.collection_id, "collection_id"),
        )
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "created_at")
        )
        object.__setattr__(self, "reports", _reports(self.reports, "reports"))
        object.__setattr__(self, "selector", _plain_mapping(self.selector, "selector"))
        object.__setattr__(self, "summary", _plain_mapping(self.summary, "summary"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "collection_id": self.collection_id,
            "created_at": self.created_at,
            "selector": thaw_plain_data(self.selector, path="selector"),
            "reports": [report.to_dict() for report in self.reports],
            "summary": thaw_plain_data(self.summary, path="summary"),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CollectionCleanupReport":
        mapping = _mapping(data, "CollectionCleanupReport")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "collection_id",
                "created_at",
                "selector",
                "reports",
                "summary",
                "metadata",
            },
            "CollectionCleanupReport",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            collection_id=_non_empty_string(
                _required(mapping, "collection_id"), "collection_id"
            ),
            created_at=_timestamp(_required(mapping, "created_at"), "created_at"),
            selector=_plain_mapping(mapping.get("selector", {}), "selector"),
            reports=tuple(
                CleanupReport.from_dict(report)
                for report in _sequence(mapping.get("reports", ()), "reports")
            ),
            summary=_plain_mapping(mapping.get("summary", {}), "summary"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class CollectionCleanupResult:
    """Aggregate mutating cleanup result for candidate-level collection GC."""

    result_id: str
    collection_id: str
    created_at: str
    intent: CleanupDeleteIntent
    results: tuple[CleanupResultFact, ...] = ()
    schema_version: int = CLEANUP_RECORD_SCHEMA_VERSION
    summary: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "result_id", _non_empty_string(self.result_id, "result_id")
        )
        object.__setattr__(
            self,
            "collection_id",
            _non_empty_string(self.collection_id, "collection_id"),
        )
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "created_at")
        )
        if not isinstance(self.intent, CleanupDeleteIntent):
            raise CleanupError("intent must be a CleanupDeleteIntent")
        object.__setattr__(self, "results", _result_facts(self.results, "results"))
        object.__setattr__(self, "summary", _plain_mapping(self.summary, "summary"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "collection_id": self.collection_id,
            "created_at": self.created_at,
            "intent": self.intent.to_dict(),
            "results": [fact.to_dict() for fact in self.results],
            "summary": thaw_plain_data(self.summary, path="summary"),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CollectionCleanupResult":
        mapping = _mapping(data, "CollectionCleanupResult")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "result_id",
                "collection_id",
                "created_at",
                "intent",
                "results",
                "summary",
                "metadata",
            },
            "CollectionCleanupResult",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_RECORD_SCHEMA_VERSION),
                "schema_version",
            ),
            result_id=_non_empty_string(_required(mapping, "result_id"), "result_id"),
            collection_id=_non_empty_string(
                _required(mapping, "collection_id"), "collection_id"
            ),
            created_at=_timestamp(_required(mapping, "created_at"), "created_at"),
            intent=CleanupDeleteIntent.from_dict(_required(mapping, "intent")),
            results=tuple(
                CleanupResultFact.from_dict(fact)
                for fact in _sequence(mapping.get("results", ()), "results")
            ),
            summary=_plain_mapping(mapping.get("summary", {}), "summary"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


def plan_collection_gc(
    targets: Iterable[CollectionCleanupTarget],
    *,
    selector: CleanupSelector | Mapping[str, PlainData] | None = None,
    now: datetime | None = None,
    collection_id: str | None = None,
    created_at: str | None = None,
    report_id_prefix: str | None = None,
    require_ownership: bool = True,
    metadata: Mapping[str, PlainData] | None = None,
) -> CollectionCleanupReport:
    """Return an aggregate collection cleanup report without mutating stores."""

    normalized_targets = _targets(targets)
    selector_record = _selector(selector)
    timestamp = created_at or utc_timestamp(now)
    reports = tuple(
        plan_cleanup(
            target.store,
            target.run_uri,
            selector=selector_record,
            managed_roots=target.managed_roots,
            now=now,
            report_id=_run_record_id(report_id_prefix, index, "cleanup-report"),
            created_at=timestamp,
            require_ownership=require_ownership,
            metadata={**target.metadata, **_plain_metadata(metadata)},
        )
        for index, target in enumerate(normalized_targets, start=1)
    )
    return CollectionCleanupReport(
        collection_id=collection_id or f"cleanup-collection-{uuid.uuid4().hex}",
        created_at=timestamp,
        reports=reports,
        selector=selector_record.to_dict(),
        summary=_report_summary(reports),
        metadata=_plain_metadata(metadata),
    )


def execute_collection_gc(
    targets: Iterable[CollectionCleanupTarget],
    report: CollectionCleanupReport,
    intent: CleanupDeleteIntent,
    *,
    result_id: str | None = None,
    created_at: str | None = None,
    result_id_prefix: str | None = None,
    require_ownership: bool = True,
    event_dispatcher: RuntimeEventDispatcher | None = None,
    emit_event: bool = True,
    metadata: Mapping[str, PlainData] | None = None,
) -> CollectionCleanupResult:
    """Execute selected collection cleanup entries through per-run stores."""

    if not isinstance(report, CollectionCleanupReport):
        raise CleanupError("report must be a CollectionCleanupReport")
    if not isinstance(intent, CleanupDeleteIntent):
        raise CleanupError("intent must be a CleanupDeleteIntent")
    targets_by_run = {target.run_uri: target for target in _targets(targets)}
    timestamp = created_at or utc_timestamp()
    aggregate_result_id = result_id or f"cleanup-collection-result-{uuid.uuid4().hex}"
    per_run_results: list[CleanupResultFact] = []
    for index, run_report in enumerate(report.reports, start=1):
        target = targets_by_run.get(run_report.run_uri)
        if target is None:
            raise CleanupError(
                f"collection cleanup target missing for run {run_report.run_uri!r}"
            )
        per_run_results.append(
            execute_cleanup(
                target.store,
                target.run_uri,
                run_report,
                intent,
                managed_roots=target.managed_roots,
                result_id=_run_record_id(result_id_prefix, index, "cleanup-result"),
                created_at=timestamp,
                require_ownership=require_ownership,
                event_dispatcher=event_dispatcher,
                emit_event=emit_event,
                metadata={
                    "collection_id": report.collection_id,
                    "collection_result_id": aggregate_result_id,
                    **target.metadata,
                    **_plain_metadata(metadata),
                },
            )
        )
    return CollectionCleanupResult(
        result_id=aggregate_result_id,
        collection_id=report.collection_id,
        created_at=timestamp,
        intent=intent,
        results=tuple(per_run_results),
        summary=_result_summary(tuple(per_run_results)),
        metadata={
            "report_collection_id": report.collection_id,
            **_plain_metadata(metadata),
        },
    )


def _targets(
    values: Iterable[CollectionCleanupTarget],
) -> tuple[CollectionCleanupTarget, ...]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise CleanupError("targets must be an iterable of CollectionCleanupTarget")
    targets = tuple(values)
    for index, target in enumerate(targets):
        if not isinstance(target, CollectionCleanupTarget):
            raise CleanupError(f"targets[{index}] must be a CollectionCleanupTarget")
    run_uris = [target.run_uri for target in targets]
    if len(set(run_uris)) != len(run_uris):
        raise CleanupError("collection cleanup targets must have unique run_uri values")
    return targets


def _selector(
    value: CleanupSelector | Mapping[str, PlainData] | None,
) -> CleanupSelector:
    if value is None:
        return CleanupSelector()
    if isinstance(value, CleanupSelector):
        return value
    return CleanupSelector.from_dict(value)


def _run_record_id(prefix: str | None, index: int, default_prefix: str) -> str | None:
    if prefix is None:
        return None
    return f"{prefix}-{default_prefix}-{index}"


def _report_summary(reports: tuple[CleanupReport, ...]) -> dict[str, PlainData]:
    entries = tuple(entry for report in reports for entry in report.entries)
    selected = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.SELECTED
    )
    skipped = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.SKIPPED
    )
    rejected = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.REJECTED
    )
    return {
        "runs": len(reports),
        "candidates": len(entries),
        "selected": selected,
        "skipped": skipped,
        "rejected": rejected,
        "dry_run": True,
    }


def _result_summary(results: tuple[CleanupResultFact, ...]) -> dict[str, PlainData]:
    entries = tuple(entry for fact in results for entry in fact.result.entries)
    deleted = sum(
        1 for entry in entries if entry.outcome is CleanupResultOutcome.DELETED
    )
    skipped = sum(
        1 for entry in entries if entry.outcome is CleanupResultOutcome.SKIPPED
    )
    rejected = sum(
        1 for entry in entries if entry.outcome is CleanupResultOutcome.REJECTED
    )
    failed = sum(1 for entry in entries if entry.outcome is CleanupResultOutcome.FAILED)
    return {
        "runs": len(results),
        "candidates": len(entries),
        "deleted": deleted,
        "skipped": skipped,
        "rejected": rejected,
        "failed": failed,
    }


def _result_facts(
    values: Iterable[CleanupResultFact],
    field: str,
) -> tuple[CleanupResultFact, ...]:
    facts = tuple(values)
    for index, fact in enumerate(facts):
        if not isinstance(fact, CleanupResultFact):
            raise CleanupError(f"{field}[{index}] must be a CleanupResultFact")
    return facts


def _reports(values: Iterable[CleanupReport], field: str) -> tuple[CleanupReport, ...]:
    reports = tuple(values)
    for index, report in enumerate(reports):
        if not isinstance(report, CleanupReport):
            raise CleanupError(f"{field}[{index}] must be a CleanupReport")
    return reports


def _managed_roots(
    values: Iterable[CleanupManagedRoot],
    field: str,
) -> tuple[CleanupManagedRoot, ...]:
    roots = tuple(values)
    for index, root in enumerate(roots):
        if not isinstance(root, CleanupManagedRoot):
            raise CleanupError(f"{field}[{index}] must be a CleanupManagedRoot")
    return roots


def _plain_metadata(
    metadata: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    if metadata is None:
        return {}
    thawed = thaw_plain_data(_plain_mapping(metadata, "metadata"), path="metadata")
    if isinstance(thawed, dict):
        return cast(dict[str, PlainData], thawed)
    return {}


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise CleanupError(f"{field} must be a mapping")
    try:
        return cast(Mapping[str, PlainData], freeze_plain_data(value, path=field))
    except Exception as exc:
        raise CleanupError(f"{field} must contain plain data") from exc


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CleanupError(f"{path}.from_dict expects mapping")
    return value


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise CleanupError(f"{field} is required")
    return mapping[field]


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise CleanupError(f"{field} must be a sequence")
    return tuple(value)


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], path: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        formatted = ", ".join(sorted(unknown))
        raise CleanupError(f"{path} has unsupported field(s): {formatted}")


def _require_schema_version(value: object, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != CLEANUP_RECORD_SCHEMA_VERSION
    ):
        raise CleanupError(f"{field} must be {CLEANUP_RECORD_SCHEMA_VERSION}")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CleanupError(f"{field} must be a non-empty UTC timestamp")
    try:
        return parse_timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CleanupError(f"{field} must be a UTC loom timestamp") from exc


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CleanupError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "CollectionCleanupReport",
    "CollectionCleanupResult",
    "CollectionCleanupTarget",
    "execute_collection_gc",
    "plan_collection_gc",
]
