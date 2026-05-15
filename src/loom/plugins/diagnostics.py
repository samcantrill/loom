"""Plain plugin diagnostics used by CLI and preflight callers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from loom.serialization import PlainData

from .entrypoints import (
    KNOWN_PLUGIN_GROUPS,
    LOOM_CODECS_GROUP,
    LOOM_RECIPES_GROUP,
    LoadedPlugin,
    PluginDuplicate,
    PluginFailure,
    PluginLoadResult,
    PluginRecord,
    find_plugin_duplicates,
)

LOADABLE_PLUGIN_GROUPS: tuple[str, ...] = (LOOM_RECIPES_GROUP, LOOM_CODECS_GROUP)
LISTING_ONLY_PLUGIN_GROUPS: tuple[str, ...] = tuple(
    group for group in KNOWN_PLUGIN_GROUPS if group not in LOADABLE_PLUGIN_GROUPS
)
PLUGIN_GROUP_READINESS: dict[str, str] = {
    LOOM_RECIPES_GROUP: "registry-ready",
    LOOM_CODECS_GROUP: "registry-ready",
    **{group: "listing-only" for group in LISTING_ONLY_PLUGIN_GROUPS},
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
        from loom.config.recipes import RecipeCatalog

        from .recipes import load_recipe_entry_points

        result = load_recipe_entry_points(
            records=all_records,
            catalog=RecipeCatalog(),
            selected=recipe_records,
            strict=False,
        )
        loaded.extend(result.loaded)
        duplicates.extend(result.duplicates)
        failures.extend(result.failures)

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

    return PluginLoadResult(
        loaded=tuple(loaded),
        duplicates=tuple(duplicates),
        failures=tuple(failures),
    )


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
    summary["readiness"] = PLUGIN_GROUP_READINESS.get(record.group, "listing-only")
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
    "PluginDiagnosticResult",
    "PluginMissingRequest",
    "PluginSelection",
    "check_plugin_records",
    "filter_plugin_records",
    "summarize_plugin_records",
]
