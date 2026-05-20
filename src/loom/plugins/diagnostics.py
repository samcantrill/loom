"""Plain plugin diagnostics used by CLI and preflight callers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loom.serialization import PlainData

from .entrypoints import (
    KNOWN_PLUGIN_GROUPS,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LoadedPlugin,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    PluginDuplicate,
    PluginFailure,
    PluginLoadResult,
    PluginRecord,
    find_plugin_duplicates,
)

if TYPE_CHECKING:
    from weave.recipes.load import RecipePluginRecord

LOADABLE_PLUGIN_GROUPS: tuple[str, ...] = (
    LOOM_RECIPES_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
)
LISTING_ONLY_PLUGIN_GROUPS: tuple[str, ...] = tuple(
    group for group in KNOWN_PLUGIN_GROUPS if group not in LOADABLE_PLUGIN_GROUPS
)


@dataclass(frozen=True, slots=True)
class PluginGroupReadiness:
    """Diagnostic readiness classification for an entry point group."""

    group: str
    status: str
    reason: str
    revisit_trigger: str

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "group": self.group,
            "status": self.status,
            "reason": self.reason,
            "revisit_trigger": self.revisit_trigger,
        }


_PLUGIN_GROUP_READINESS_DETAILS: dict[str, PluginGroupReadiness] = {
    LOOM_RECIPES_GROUP: PluginGroupReadiness(
        group=LOOM_RECIPES_GROUP,
        status="registry-ready",
        reason="RecipeCatalog owns recipe name validation and replacement policy.",
        revisit_trigger="RecipeCatalog plugin registration policy changes.",
    ),
    LOOM_CODECS_GROUP: PluginGroupReadiness(
        group=LOOM_CODECS_GROUP,
        status="registry-ready",
        reason="CodecRegistry owns codec object validation and duplicate key policy.",
        revisit_trigger="CodecRegistry replacement or adapter policy changes.",
    ),
    LOOM_SOURCES_GROUP: PluginGroupReadiness(
        group=LOOM_SOURCES_GROUP,
        status="listing-only",
        reason="DataSource exists, but no source plugin registry or loader contract is stable.",
        revisit_trigger="A source-owned registry and plugin adapter contract lands.",
    ),
    LOOM_EXECUTORS_GROUP: PluginGroupReadiness(
        group=LOOM_EXECUTORS_GROUP,
        status="listing-only",
        reason=(
            "Executor descriptors cover capabilities, not third-party executor "
            "implementation loading."
        ),
        revisit_trigger="An executor implementation registry or descriptor loader lands.",
    ),
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP: PluginGroupReadiness(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        status="listing-only",
        reason=(
            "Stage 15 owns backend descriptors, config handoff, capabilities, "
            "credentials, URI policy, and operation semantics."
        ),
        revisit_trigger="Stage 15 defines a store-owned backend registry and descriptor contract.",
    ),
    LOOM_RUN_EXPORTERS_GROUP: PluginGroupReadiness(
        group=LOOM_RUN_EXPORTERS_GROUP,
        status="listing-only",
        reason="RunExporter/RunImporter protocols exist, but no plugin registry/loader is stable.",
        revisit_trigger="Run exchange defines supplied exporter/importer plugin registries.",
    ),
    LOOM_SWEEP_PROVIDERS_GROUP: PluginGroupReadiness(
        group=LOOM_SWEEP_PROVIDERS_GROUP,
        status="listing-only",
        reason="Sweep provider protocols exist, but no plugin registry/loader is stable.",
        revisit_trigger="Sweep planning defines a supplied provider plugin registry.",
    ),
    LOOM_EVENT_SINKS_GROUP: PluginGroupReadiness(
        group=LOOM_EVENT_SINKS_GROUP,
        status="registry-ready",
        reason="EventSinkRegistry owns explicit event sink registration and duplicate-name policy.",
        revisit_trigger="Event sink plugin constructor or registry policy changes.",
    ),
}
PLUGIN_GROUP_READINESS_DETAILS: dict[str, PluginGroupReadiness] = dict(
    _PLUGIN_GROUP_READINESS_DETAILS
)
PLUGIN_GROUP_READINESS: dict[str, str] = {
    group: readiness.status
    for group, readiness in _PLUGIN_GROUP_READINESS_DETAILS.items()
}


@dataclass(frozen=True, slots=True)
class PluginSelection:
    """Structured plugin metadata filters."""

    groups: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", _unique_sorted(self.groups, field="groups"))
        object.__setattr__(self, "names", _unique_sorted(self.names, field="names"))
        object.__setattr__(self, "packages", _unique_sorted(self.packages, field="packages"))

    @property
    def is_empty(self) -> bool:
        return not self.groups and not self.names and not self.packages

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "groups": list(self.groups),
            "names": list(self.names),
            "packages": list(self.packages),
        }


@dataclass(frozen=True, slots=True)
class PluginMissingRequest:
    """A requested plugin selector that matched no discovered records."""

    field: str
    value: str

    def to_summary(self) -> dict[str, PlainData]:
        return {"field": self.field, "value": self.value}


@dataclass(frozen=True, slots=True)
class PluginDiagnosticResult:
    """Plain-data plugin diagnostic result."""

    selection: PluginSelection
    records: tuple[PluginRecord, ...]
    load_requested: bool = False
    loaded: tuple[PluginRecord, ...] = ()
    duplicates: tuple[PluginDuplicate, ...] = ()
    failures: tuple[PluginFailure, ...] = ()
    missing: tuple[PluginMissingRequest, ...] = ()
    unsupported_groups: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (
            self.duplicates
            or self.failures
            or self.missing
            or self.unsupported_groups
        )

    @property
    def listing_only_records(self) -> tuple[PluginRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.group not in LOADABLE_PLUGIN_GROUPS
        )

    def to_summary(self) -> dict[str, PlainData]:
        record_statuses = _record_statuses(
            records=self.records,
            loaded=self.loaded,
            duplicates=self.duplicates,
            failures=self.failures,
            load_requested=self.load_requested,
        )
        return {
            "selection": self.selection.to_summary(),
            "load_requested": self.load_requested,
            "ok": self.ok,
            "records": [
                _record_summary(record, status=record_statuses[(record.group, record.name, record.value)])
                for record in self.records
            ],
            "loaded": [record.to_summary() for record in self.loaded],
            "duplicates": [duplicate.to_summary() for duplicate in self.duplicates],
            "failures": [failure.to_summary() for failure in self.failures],
            "missing": [missing.to_summary() for missing in self.missing],
            "unsupported_groups": list(self.unsupported_groups),
            "listing_only": [
                _record_summary(record, status="listing-only")
                for record in self.listing_only_records
            ],
            "counts": {
                "records": len(self.records),
                "loaded": len(self.loaded),
                "duplicates": len(self.duplicates),
                "failures": len(self.failures),
                "missing": len(self.missing),
                "unsupported_groups": len(self.unsupported_groups),
                "listing_only": len(self.listing_only_records),
            },
        }


def filter_plugin_records(
    records: Iterable[PluginRecord],
    selection: PluginSelection,
) -> tuple[PluginRecord, ...]:
    """Filter plugin records by structured metadata selection."""

    return tuple(
        sorted(
            (
                record
                for record in records
                if _matches_selection(record, selection)
            ),
            key=_record_sort_key,
        )
    )


def summarize_plugin_records(
    records: Iterable[PluginRecord],
    *,
    selection: PluginSelection | None = None,
) -> PluginDiagnosticResult:
    """Return metadata-only plugin summaries."""

    normalized_selection = selection or PluginSelection()
    selected = filter_plugin_records(records, normalized_selection)
    return PluginDiagnosticResult(selection=normalized_selection, records=selected)


def plugin_group_readiness(group: str) -> PluginGroupReadiness:
    """Return readiness metadata for a plugin entry point group."""

    return _PLUGIN_GROUP_READINESS_DETAILS.get(
        group,
        PluginGroupReadiness(
            group=group,
            status="listing-only",
            reason="No Stage 14 registry loader is defined for this entry point group.",
            revisit_trigger="An owning subsystem defines a stable registry and loader contract.",
        ),
    )


def check_plugin_records(
    records: Iterable[PluginRecord],
    *,
    selection: PluginSelection,
    load: bool = True,
) -> PluginDiagnosticResult:
    """Check selected plugin records and optionally load registry-ready groups."""

    all_records = tuple(sorted(records, key=_record_sort_key))
    selected = filter_plugin_records(all_records, selection)
    duplicates = find_plugin_duplicates(selected)
    missing = _missing_requests(all_records=all_records, selected=selected, selection=selection)
    unsupported_groups = _unsupported_groups(selected=selected, selection=selection, load=load)

    load_result = (
        _load_registry_ready_plugins(all_records=all_records, selected=selected)
        if load and selected
        else PluginLoadResult(loaded=(), duplicates=(), failures=())
    )
    duplicate_keys = {(duplicate.group, duplicate.name) for duplicate in duplicates}
    loaded = tuple(plugin.record for plugin in load_result.loaded)
    failures = load_result.failures
    load_duplicates = tuple(
        duplicate
        for duplicate in load_result.duplicates
        if (duplicate.group, duplicate.name) not in duplicate_keys
    )

    return PluginDiagnosticResult(
        selection=selection,
        records=selected,
        load_requested=load,
        loaded=loaded,
        duplicates=duplicates + load_duplicates,
        failures=failures,
        missing=missing,
        unsupported_groups=unsupported_groups,
    )


def _load_registry_ready_plugins(
    *,
    all_records: tuple[PluginRecord, ...],
    selected: tuple[PluginRecord, ...],
) -> PluginLoadResult:
    loaded: list[LoadedPlugin] = []
    duplicates: list[PluginDuplicate] = []
    failures: list[PluginFailure] = []

    recipe_records = tuple(record for record in selected if record.group == LOOM_RECIPES_GROUP)
    if recipe_records:
        from weave.recipes import RecipeCatalog
        from weave.recipes.load import load_recipe_entry_points

        result = load_recipe_entry_points(
            records=tuple(_recipe_plugin_record(record) for record in all_records),
            catalog=RecipeCatalog(),
            selected=tuple(_recipe_plugin_record(record) for record in recipe_records),
            strict=False,
        )
        loaded.extend(
            LoadedPlugin(record=_plugin_record(record), value=None)
            for record in result.loaded
        )
        duplicates.extend(
            PluginDuplicate(
                group=duplicate.group,
                name=duplicate.name,
                records=tuple(_plugin_record(record) for record in duplicate.records),
            )
            for duplicate in result.duplicates
        )
        failures.extend(
            PluginFailure(
                record=_plugin_record(failure.record),
                operation=failure.operation,
                error_type=failure.error_type,
                message=failure.message,
            )
            for failure in result.failures
        )

    codec_records = tuple(record for record in selected if record.group == LOOM_CODECS_GROUP)
    if codec_records:
        from loom.io.codecs import CodecRegistry

        from .codecs import load_codec_entry_points

        result = load_codec_entry_points(
            records=all_records,
            registry=CodecRegistry(),
            selected=codec_records,
            strict=False,
        )
        loaded.extend(result.loaded)
        duplicates.extend(result.duplicates)
        failures.extend(result.failures)

    event_sink_records = tuple(
        record for record in selected if record.group == LOOM_EVENT_SINKS_GROUP
    )
    if event_sink_records:
        from loom.pipeline.event_sinks import EventSinkRegistry

        from .event_sinks import load_event_sink_entry_points

        result = load_event_sink_entry_points(
            records=all_records,
            registry=EventSinkRegistry(),
            selected=event_sink_records,
            strict=False,
        )
        loaded.extend(result.loaded)
        duplicates.extend(result.duplicates)
        failures.extend(result.failures)

    return PluginLoadResult(
        loaded=tuple(loaded),
        duplicates=tuple(duplicates),
        failures=tuple(failures),
    )


def _recipe_plugin_record(record: PluginRecord) -> "RecipePluginRecord":
    from weave.recipes.load import RecipePluginRecord

    return RecipePluginRecord(
        group=record.group,
        name=record.name,
        value=record.value,
        package=record.package,
        package_version=record.package_version,
    )


def _plugin_record(record: object) -> PluginRecord:
    return PluginRecord(
        group=str(getattr(record, "group")),
        name=str(getattr(record, "name")),
        value=str(getattr(record, "value")),
        package=_optional_string(getattr(record, "package", None)),
        package_version=_optional_string(getattr(record, "package_version", None)),
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _matches_selection(record: PluginRecord, selection: PluginSelection) -> bool:
    if selection.groups and record.group not in selection.groups:
        return False
    if selection.names and record.name not in selection.names:
        return False
    if selection.packages and record.package not in selection.packages:
        return False
    return True


def _missing_requests(
    *,
    all_records: tuple[PluginRecord, ...],
    selected: tuple[PluginRecord, ...],
    selection: PluginSelection,
) -> tuple[PluginMissingRequest, ...]:
    del all_records
    missing: list[PluginMissingRequest] = []
    for group in selection.groups:
        if not any(record.group == group for record in selected):
            missing.append(PluginMissingRequest(field="group", value=group))
    for name in selection.names:
        if not any(record.name == name for record in selected):
            missing.append(PluginMissingRequest(field="name", value=name))
    for package in selection.packages:
        if not any(record.package == package for record in selected):
            missing.append(PluginMissingRequest(field="package", value=package))
    return tuple(missing)


def _unsupported_groups(
    *,
    selected: tuple[PluginRecord, ...],
    selection: PluginSelection,
    load: bool,
) -> tuple[str, ...]:
    if not load:
        return ()
    groups: set[str] = set(selection.groups)
    groups.update(record.group for record in selected)
    return tuple(sorted(group for group in groups if group not in LOADABLE_PLUGIN_GROUPS))


def _record_summary(record: PluginRecord, *, status: str) -> dict[str, PlainData]:
    summary = record.to_summary()
    summary["status"] = status
    summary["readiness"] = plugin_group_readiness(record.group).status
    return summary


def _record_statuses(
    *,
    records: tuple[PluginRecord, ...],
    loaded: tuple[PluginRecord, ...],
    duplicates: tuple[PluginDuplicate, ...],
    failures: tuple[PluginFailure, ...],
    load_requested: bool,
) -> dict[tuple[str, str, str], str]:
    statuses = {
        (record.group, record.name, record.value): (
            "listing-only"
            if record.group not in LOADABLE_PLUGIN_GROUPS
            else "metadata"
        )
        for record in records
    }
    if load_requested:
        for record in records:
            key = (record.group, record.name, record.value)
            if record.group in LOADABLE_PLUGIN_GROUPS:
                statuses[key] = "load-pending"
    for record in loaded:
        statuses[(record.group, record.name, record.value)] = "loaded"
    for duplicate in duplicates:
        for record in duplicate.records:
            statuses[(record.group, record.name, record.value)] = "duplicate"
    for failure in failures:
        record = failure.record
        statuses[(record.group, record.name, record.value)] = "failed"
    return statuses


def _record_sort_key(record: PluginRecord) -> tuple[str, str, str]:
    return (record.group, record.name, record.value)


def _unique_sorted(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        normalized.add(value.strip())
    return tuple(sorted(normalized))


__all__ = [
    "LISTING_ONLY_PLUGIN_GROUPS",
    "LOADABLE_PLUGIN_GROUPS",
    "PLUGIN_GROUP_READINESS",
    "PLUGIN_GROUP_READINESS_DETAILS",
    "PluginGroupReadiness",
    "PluginDiagnosticResult",
    "PluginMissingRequest",
    "PluginSelection",
    "check_plugin_records",
    "filter_plugin_records",
    "plugin_group_readiness",
    "summarize_plugin_records",
]
