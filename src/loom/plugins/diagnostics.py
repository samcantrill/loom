"""Plain plugin diagnostics used by CLI and preflight callers."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from loom.serialization import PlainData

from .entrypoints import (
    KNOWN_PLUGIN_GROUPS,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
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
    LOOM_EXECUTORS_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
)
_ORIGINAL_IMPORT_MODULE = importlib.import_module

LISTING_ONLY_PLUGIN_GROUPS: tuple[str, ...] = tuple(
    group for group in KNOWN_PLUGIN_GROUPS if group not in LOADABLE_PLUGIN_GROUPS
)

READINESS_FACETS: tuple[str, ...] = (
    "contract",
    "python_injection",
    "registry",
    "plugin_loading",
    "cli_selection",
    "fresh_process_reconstruction",
)
ReadinessFacetStatus = Literal["supported", "unsupported", "not_applicable"]


@dataclass(frozen=True, slots=True)
class PluginReadinessFacet:
    """One independently reported extension capability."""

    status: ReadinessFacetStatus
    evidence: str

    def __post_init__(self) -> None:
        if self.status not in {"supported", "unsupported", "not_applicable"}:
            raise ValueError(
                "readiness facet status must be supported, unsupported, or not_applicable"
            )
        if not isinstance(self.evidence, str) or not self.evidence:
            raise ValueError("readiness facet evidence must be a non-empty string")

    def to_summary(self) -> dict[str, PlainData]:
        return {"status": self.status, "evidence": self.evidence}


@dataclass(frozen=True, slots=True)
class PluginGroupReadiness:
    """Diagnostic readiness classification for an entry point group."""

    group: str
    reason: str
    revisit_trigger: str
    facets: Mapping[str, PluginReadinessFacet]

    def __post_init__(self) -> None:
        normalized = dict(self.facets)
        if tuple(normalized) != READINESS_FACETS:
            raise ValueError(
                "readiness facets must use the fixed readiness facet order"
            )
        if not all(
            isinstance(facet, PluginReadinessFacet) for facet in normalized.values()
        ):
            raise TypeError("readiness facets must be PluginReadinessFacet values")
        object.__setattr__(self, "facets", MappingProxyType(normalized))

    @property
    def status(self) -> str:
        """Compatibility summary derived solely from registry and loading support."""

        if (
            self.facets["registry"].status == "supported"
            and self.facets["plugin_loading"].status == "supported"
        ):
            return "registry-ready"
        return "listing-only"

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "group": self.group,
            "status": self.status,
            "reason": self.reason,
            "revisit_trigger": self.revisit_trigger,
            "facets": {name: facet.to_summary() for name, facet in self.facets.items()},
        }


def _facet(status: ReadinessFacetStatus, evidence: str) -> PluginReadinessFacet:
    return PluginReadinessFacet(status=status, evidence=evidence)


def _facets(
    *,
    contract: tuple[ReadinessFacetStatus, str],
    python_injection: tuple[ReadinessFacetStatus, str],
    registry: tuple[ReadinessFacetStatus, str],
    plugin_loading: tuple[ReadinessFacetStatus, str],
    cli_selection: tuple[ReadinessFacetStatus, str],
    fresh_process_reconstruction: tuple[ReadinessFacetStatus, str],
) -> dict[str, PluginReadinessFacet]:
    return {
        "contract": _facet(*contract),
        "python_injection": _facet(*python_injection),
        "registry": _facet(*registry),
        "plugin_loading": _facet(*plugin_loading),
        "cli_selection": _facet(*cli_selection),
        "fresh_process_reconstruction": _facet(*fresh_process_reconstruction),
    }


_PLUGIN_GROUP_READINESS_DETAILS: dict[str, PluginGroupReadiness] = {
    LOOM_RECIPES_GROUP: PluginGroupReadiness(
        group=LOOM_RECIPES_GROUP,
        reason="RecipeCatalog owns recipe name validation and replacement policy.",
        revisit_trigger="RecipeCatalog plugin registration policy changes.",
        facets=_facets(
            contract=(
                "supported",
                "RecipeCatalog defines recipe registration behavior.",
            ),
            python_injection=(
                "supported",
                "Applications can register trusted recipes directly.",
            ),
            registry=("supported", "RecipeCatalog owns recipe-name validation."),
            plugin_loading=(
                "supported",
                "Selected entry points load into a supplied RecipeCatalog.",
            ),
            cli_selection=(
                "unsupported",
                "Run commands do not yet select recipe plugins.",
            ),
            fresh_process_reconstruction=(
                "unsupported",
                "Prepared runs do not record plugin activations.",
            ),
        ),
    ),
    LOOM_CODECS_GROUP: PluginGroupReadiness(
        group=LOOM_CODECS_GROUP,
        reason="CodecRegistry owns codec object validation and duplicate key policy.",
        revisit_trigger="CodecRegistry replacement or adapter policy changes.",
        facets=_facets(
            contract=("supported", "Codec defines key, encode, and decode behavior."),
            python_injection=(
                "supported",
                "Applications can register codecs in a supplied CodecRegistry.",
            ),
            registry=(
                "supported",
                "CodecRegistry validates codec keys and duplicates.",
            ),
            plugin_loading=(
                "supported",
                "Selected entry points load into a supplied CodecRegistry.",
            ),
            cli_selection=(
                "supported",
                "Run commands explicitly select codec plugins.",
            ),
            fresh_process_reconstruction=(
                "supported",
                "Fresh workers reconstruct selected codec registries from current selectors.",
            ),
        ),
    ),
    LOOM_SOURCES_GROUP: PluginGroupReadiness(
        group=LOOM_SOURCES_GROUP,
        reason="DataSource exists, but no source plugin registry or loader contract is stable.",
        revisit_trigger="A source-owned registry and plugin adapter contract lands.",
        facets=_facets(
            contract=("supported", "DataSource remains a subsystem protocol."),
            python_injection=(
                "not_applicable",
                "No source injection seam is owned by the runtime.",
            ),
            registry=("not_applicable", "No source registry is defined."),
            plugin_loading=(
                "not_applicable",
                "No source entry-point adapter is defined.",
            ),
            cli_selection=("not_applicable", "No source plugin selection exists."),
            fresh_process_reconstruction=(
                "not_applicable",
                "No source plugin activation is persisted.",
            ),
        ),
    ),
    LOOM_EXECUTORS_GROUP: PluginGroupReadiness(
        group=LOOM_EXECUTORS_GROUP,
        reason="ExecutorRegistry pairs ordinary descriptors and factories instance-locally.",
        revisit_trigger="CLI activation or submitted executor ownership changes.",
        facets=_facets(
            contract=("supported", "Executor defines stage execution behavior."),
            python_injection=(
                "supported",
                "PipelineRunner accepts an explicitly built executor.",
            ),
            registry=(
                "supported",
                "ExecutorRegistry owns descriptor/factory/name pairing.",
            ),
            plugin_loading=(
                "supported",
                "Selected entry points load into a supplied ExecutorRegistry.",
            ),
            cli_selection=(
                "supported",
                "Run commands explicitly select ordinary executor plugins.",
            ),
            fresh_process_reconstruction=(
                "not_applicable",
                "Workers consume the selected executor and do not reconstruct dispatch executors.",
            ),
        ),
    ),
    LOOM_RESOURCE_VALIDATORS_GROUP: PluginGroupReadiness(
        group=LOOM_RESOURCE_VALIDATORS_GROUP,
        reason="ResourceValidatorRegistry owns resource-kind and duplicate validation.",
        revisit_trigger="CLI activation or worker reconstruction policy changes.",
        facets=_facets(
            contract=(
                "supported",
                "ResourceValidator is the existing direct callable contract.",
            ),
            python_injection=(
                "supported",
                "Applications pass a selected validator registry explicitly.",
            ),
            registry=(
                "supported",
                "ResourceValidatorRegistry owns kind and duplicate checks.",
            ),
            plugin_loading=(
                "supported",
                "Selected entry points load direct validators into a supplied registry.",
            ),
            cli_selection=(
                "supported",
                "Validate, plan, preflight, and run commands explicitly select validator plugins.",
            ),
            fresh_process_reconstruction=(
                "supported",
                "Fresh workers reconstruct selected validator registries from current selectors.",
            ),
        ),
    ),
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP: PluginGroupReadiness(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        reason=(
            "Stage 15 owns backend descriptors, config handoff, capabilities, "
            "credentials, URI policy, and operation semantics."
        ),
        revisit_trigger="Stage 15 defines a store-owned backend registry and descriptor contract.",
        facets=_facets(
            contract=(
                "unsupported",
                "No backend extension contract is published by this group.",
            ),
            python_injection=(
                "not_applicable",
                "No backend injection seam is owned here.",
            ),
            registry=(
                "not_applicable",
                "No backend registry is defined for this group.",
            ),
            plugin_loading=(
                "not_applicable",
                "No backend entry-point adapter is defined.",
            ),
            cli_selection=("not_applicable", "No backend plugin selection exists."),
            fresh_process_reconstruction=(
                "not_applicable",
                "No backend plugin activation is persisted.",
            ),
        ),
    ),
    LOOM_RUN_EXPORTERS_GROUP: PluginGroupReadiness(
        group=LOOM_RUN_EXPORTERS_GROUP,
        reason="RunExporter/RunImporter protocols exist, but no plugin registry/loader is stable.",
        revisit_trigger="Run exchange defines supplied exporter/importer plugin registries.",
        facets=_facets(
            contract=("supported", "Run exchange defines exporter/importer protocols."),
            python_injection=(
                "not_applicable",
                "No exporter/importer injection seam is defined.",
            ),
            registry=("not_applicable", "No exporter/importer registry is defined."),
            plugin_loading=(
                "not_applicable",
                "No exporter/importer entry-point adapter is defined.",
            ),
            cli_selection=(
                "not_applicable",
                "No exporter/importer plugin selection exists.",
            ),
            fresh_process_reconstruction=(
                "not_applicable",
                "No exporter/importer activation is persisted.",
            ),
        ),
    ),
    LOOM_SWEEP_PROVIDERS_GROUP: PluginGroupReadiness(
        group=LOOM_SWEEP_PROVIDERS_GROUP,
        reason="Sweep provider protocols exist, but no plugin registry/loader is stable.",
        revisit_trigger="Sweep planning defines a supplied provider plugin registry.",
        facets=_facets(
            contract=(
                "supported",
                "Sweep provider protocols define proposal behavior.",
            ),
            python_injection=(
                "not_applicable",
                "No provider injection seam is defined.",
            ),
            registry=("not_applicable", "No provider registry is defined."),
            plugin_loading=(
                "not_applicable",
                "No provider entry-point adapter is defined.",
            ),
            cli_selection=("not_applicable", "No provider plugin selection exists."),
            fresh_process_reconstruction=(
                "not_applicable",
                "No provider activation is persisted.",
            ),
        ),
    ),
    LOOM_EVENT_SINKS_GROUP: PluginGroupReadiness(
        group=LOOM_EVENT_SINKS_GROUP,
        reason="EventSinkRegistry owns explicit event sink registration and duplicate-name policy.",
        revisit_trigger="Event sink plugin constructor or registry policy changes.",
        facets=_facets(
            contract=("supported", "EventSink defines observe-only callback behavior."),
            python_injection=(
                "supported",
                "Applications can register sinks in a supplied EventSinkRegistry.",
            ),
            registry=(
                "supported",
                "EventSinkRegistry validates names and duplicate registration.",
            ),
            plugin_loading=(
                "supported",
                "Selected entry points load into a supplied EventSinkRegistry.",
            ),
            cli_selection=(
                "unsupported",
                "Run commands do not yet select event sink plugins.",
            ),
            fresh_process_reconstruction=(
                "unsupported",
                "Prepared runs do not record plugin activations.",
            ),
        ),
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
        object.__setattr__(
            self, "packages", _unique_sorted(self.packages, field="packages")
        )

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
            self.duplicates or self.failures or self.missing or self.unsupported_groups
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
                _record_summary(
                    record,
                    status=record_statuses[(record.group, record.name, record.value)],
                )
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
            (record for record in records if _matches_selection(record, selection)),
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
            reason="No Stage 14 registry loader is defined for this entry point group.",
            revisit_trigger="An owning subsystem defines a stable registry and loader contract.",
            facets=_facets(
                contract=(
                    "not_applicable",
                    "The group is not a known Loom extension contract.",
                ),
                python_injection=(
                    "not_applicable",
                    "The group has no owned injection seam.",
                ),
                registry=("not_applicable", "The group has no owned registry."),
                plugin_loading=(
                    "not_applicable",
                    "The group has no entry-point adapter.",
                ),
                cli_selection=(
                    "not_applicable",
                    "The group has no CLI selection path.",
                ),
                fresh_process_reconstruction=(
                    "not_applicable",
                    "The group has no persisted activation.",
                ),
            ),
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
    missing = _missing_requests(
        all_records=all_records, selected=selected, selection=selection
    )
    unsupported_groups = _unsupported_groups(
        selected=selected, selection=selection, load=load
    )

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

    recipe_records = tuple(
        record for record in selected if record.group == LOOM_RECIPES_GROUP
    )
    if recipe_records:
        _initialize_weave_recipe_dependencies()
        from weave.recipes.load import load_recipe_entry_points

        result = load_recipe_entry_points(
            records=tuple(_recipe_plugin_record(record) for record in all_records),
            catalog=_ScratchRecipeCatalog(),
            selected=tuple(_recipe_plugin_record(record) for record in recipe_records),
            strict=False,
            group=LOOM_RECIPES_GROUP,
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

    codec_records = tuple(
        record for record in selected if record.group == LOOM_CODECS_GROUP
    )
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

    executor_records = tuple(
        record for record in selected if record.group == LOOM_EXECUTORS_GROUP
    )
    if executor_records:
        from loom.pipeline.executors import ExecutorRegistry

        from .executors import load_executor_entry_points

        result = load_executor_entry_points(
            records=all_records,
            registry=ExecutorRegistry(),
            selected=executor_records,
            strict=False,
        )
        loaded.extend(result.loaded)
        duplicates.extend(result.duplicates)
        failures.extend(result.failures)

    validator_records = tuple(
        record for record in selected if record.group == LOOM_RESOURCE_VALIDATORS_GROUP
    )
    if validator_records:
        from loom.pipeline.resources import ResourceValidatorRegistry

        from .resource_validators import load_resource_validator_entry_points

        _registry, result = load_resource_validator_entry_points(
            records=all_records,
            registry=ResourceValidatorRegistry(),
            selected=validator_records,
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


class _ScratchRecipeCatalog:
    """Minimal recipe catalog for diagnostics-only plugin load checks."""

    def __init__(self) -> None:
        self._recipes: dict[str, object] = {}

    def register(self, name: str, recipe: object, *, replace: bool = False) -> None:
        if name in self._recipes and not replace:
            raise ValueError(f"Recipe {name!r} is already registered")
        self._recipes[name] = recipe


def _initialize_weave_recipe_dependencies() -> None:
    # Tests and callers may monkeypatch importlib.import_module to control plugin
    # target imports. Pydantic also uses that hook lazily, so initialize it first
    # with the original importer and then let weave capture the caller's hook for
    # actual entry-point target loading.
    current_import_module = importlib.import_module
    try:
        importlib.import_module = _ORIGINAL_IMPORT_MODULE
        from pydantic import BaseModel, ConfigDict

        _ = (BaseModel, ConfigDict)
    finally:
        importlib.import_module = current_import_module


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
    return tuple(
        sorted(group for group in groups if group not in LOADABLE_PLUGIN_GROUPS)
    )


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
            "listing-only" if record.group not in LOADABLE_PLUGIN_GROUPS else "metadata"
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
