"""Generic plugin entry-point discovery and loading helpers."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points

from loom.serialization import PlainData

from .errors import (
    PluginDuplicateError,
    PluginInvalidEntryPointError,
    PluginLoadError,
    PluginRegistrationError,
)

# Public group constants for known plugin namespaces.
LOOM_RECIPES_GROUP = "loom.recipes"
LOOM_CODECS_GROUP = "loom.codecs"
LOOM_SOURCES_GROUP = "loom.sources"
LOOM_EXECUTORS_GROUP = "loom.executors"
LOOM_ARTIFACT_STORE_BACKENDS_GROUP = "loom.artifact_store_backends"
LOOM_RUN_EXPORTERS_GROUP = "loom.run_exporters"
LOOM_SWEEP_PROVIDERS_GROUP = "loom.sweep_providers"
LOOM_EVENT_SINKS_GROUP = "loom.event_sinks"

KNOWN_PLUGIN_GROUPS: tuple[str, ...] = (
    LOOM_RECIPES_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
)

EntryPointProvider = Callable[[], Iterable[object]]
RegisterCallback = Callable[["PluginRecord", object], None]


def _default_entry_point_provider() -> Iterable[object]:
    return entry_points()


@dataclass(frozen=True, slots=True)
class PluginRecord:
    """Metadata describing a plugin entry point."""

    group: str
    name: str
    value: str
    package: str | None = None
    package_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "group", _coerce_non_empty_str(self.group, field="group"))
        object.__setattr__(self, "name", _coerce_non_empty_str(self.name, field="name"))
        object.__setattr__(self, "value", _coerce_non_empty_str(self.value, field="value"))
        package = None if self.package is None else _coerce_optional_str(self.package)
        version = None if self.package_version is None else _coerce_optional_str(self.package_version)
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "package_version", version)

    def to_summary(self) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "group": self.group,
            "name": self.name,
            "value": self.value,
        }
        if self.package is not None:
            data["package"] = self.package
        if self.package_version is not None:
            data["package_version"] = self.package_version
        return data


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """A successfully loaded plugin entry point."""

    record: PluginRecord
    value: object

    def to_summary(self) -> dict[str, PlainData]:
        summary = self.record.to_summary()
        summary["loaded"] = True
        return summary


@dataclass(frozen=True, slots=True)
class PluginDuplicate:
    """Duplicate plugin entry points share the same group and name."""

    group: str
    name: str
    records: tuple[PluginRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "group", _coerce_non_empty_str(self.group, field="group"))
        object.__setattr__(self, "name", _coerce_non_empty_str(self.name, field="name"))
        records = tuple(self.records)
        if len(records) < 2:
            raise PluginInvalidEntryPointError(
                f"PluginDuplicate requires at least two records for group={self.group!r}, name={self.name!r}",
            )
        for record in records:
            if record.group != self.group or record.name != self.name:
                raise PluginInvalidEntryPointError(
                    "all PluginDuplicate records must share the same group and name",
                )
        object.__setattr__(self, "records", records)

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "group": self.group,
            "name": self.name,
            "count": len(self.records),
            "records": [record.to_summary() for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class PluginFailure:
    """A plugin load or registration failure."""

    record: PluginRecord
    operation: str
    error_type: str
    message: str

    @classmethod
    def from_exception(
        cls,
        record: PluginRecord,
        operation: str,
        exc: BaseException,
    ) -> "PluginFailure":
        return cls(
            record=record,
            operation=operation,
            error_type=type(exc).__name__,
            message=str(exc),
        )

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "group": self.record.group,
            "name": self.record.name,
            "operation": self.operation,
            "error_type": self.error_type,
            "message": self.message,
            **{
                key: value
                for key, value in self.record.to_summary().items()
                if key not in {"group", "name"}
            },
        }


@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    """Aggregated result for a plugin load operation."""

    loaded: tuple[LoadedPlugin, ...]
    duplicates: tuple[PluginDuplicate, ...]
    failures: tuple[PluginFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.duplicates and not self.failures

    @property
    def loaded_count(self) -> int:
        return len(self.loaded)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def failure_count(self) -> int:
        return len(self.failures)

    def to_summary(self) -> dict[str, PlainData]:
        return {
            "loaded": [plugin.to_summary() for plugin in self.loaded],
            "duplicates": [duplicate.to_summary() for duplicate in self.duplicates],
            "failures": [failure.to_summary() for failure in self.failures],
            "loaded_count": self.loaded_count,
            "duplicate_count": self.duplicate_count,
            "failure_count": self.failure_count,
        }


def list_entry_points(
    *,
    groups: Iterable[str] | None = None,
    provider: EntryPointProvider = _default_entry_point_provider,
) -> tuple[PluginRecord, ...]:
    """List plugin entry points in a metadata-only and import-light way."""

    group_filter = _coerce_group_filter(groups)
    records: list[PluginRecord] = []

    for entry_point in provider():
        record = _entry_point_to_record(entry_point)
        if group_filter is not None and record.group not in group_filter:
            continue
        records.append(record)

    return tuple(sorted(records, key=_record_sort_key))


def find_plugin_duplicates(records: Iterable[PluginRecord]) -> tuple[PluginDuplicate, ...]:
    """Return duplicate plugin records keyed by group and name."""

    by_key: dict[tuple[str, str], list[PluginRecord]] = {}
    for record in records:
        key = (record.group, record.name)
        by_key.setdefault(key, []).append(record)

    duplicates: list[PluginDuplicate] = []
    for group, name in sorted(by_key):
        if len(by_key[(group, name)]) <= 1:
            continue
        duplicates.append(
            PluginDuplicate(
                group=group,
                name=name,
                records=tuple(by_key[(group, name)]),
            ),
        )

    return tuple(duplicates)


def load_entry_points(
    records: Iterable[PluginRecord],
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
    register: RegisterCallback | None = None,
) -> PluginLoadResult:
    """Load selected plugins by importing their entry-point targets."""

    all_records = tuple(_coerce_plugin_records(records, field="records"))
    selected_records = tuple(
        _coerce_plugin_records(
            all_records if selected is None else selected,
            field="selected",
        )
    )

    duplicate_records = find_plugin_duplicates(selected_records)
    duplicates_by_key = {(duplicate.group, duplicate.name): duplicate for duplicate in duplicate_records}
    if strict and duplicate_records:
        duplicate_result = PluginLoadResult(
            loaded=(),
            duplicates=tuple(duplicate_records),
            failures=(),
        )
        raise PluginDuplicateError(duplicate_records, result=duplicate_result)

    selected_by_key: dict[tuple[str, str], PluginRecord] = {}
    for record in selected_records:
        selected_by_key[(record.group, record.name)] = record

    loaded: list[LoadedPlugin] = []
    failures: list[PluginFailure] = []

    for key in sorted(selected_by_key):
        if key in duplicates_by_key:
            continue
        record = selected_by_key[key]
        try:
            value = _load_entrypoint_value(record.value)
        except Exception as exc:  # noqa: BLE001
            failures.append(PluginFailure.from_exception(record, operation="load", exc=exc))
            continue

        if register is None:
            loaded.append(LoadedPlugin(record=record, value=value))
            continue

        try:
            register(record, value)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                PluginFailure.from_exception(
                    record,
                    operation="registration",
                    exc=exc,
                )
            )
            continue
        loaded.append(LoadedPlugin(record=record, value=value))

    result = PluginLoadResult(
        loaded=tuple(loaded),
        duplicates=tuple(duplicate_records),
        failures=tuple(failures),
    )

    if strict:
        if failures:
            if any(failure.operation == "registration" for failure in failures):
                raise PluginRegistrationError(
                    "plugin registration failed in strict mode",
                    result=result,
                )
            raise PluginLoadError("plugin load failed in strict mode", result=result)

    return result


def _entry_point_to_record(entry_point: object) -> PluginRecord:
    try:
        group = _coerce_non_empty_str(getattr(entry_point, "group"), field="entry_point.group")
        name = _coerce_non_empty_str(getattr(entry_point, "name"), field="entry_point.name")
        value = _coerce_non_empty_str(
            getattr(entry_point, "value"),
            field="entry_point.value",
        )
    except AttributeError as exc:
        raise PluginInvalidEntryPointError(
            f"Entry point metadata is incomplete: {entry_point!r}",
        ) from exc

    return PluginRecord(
        group=group,
        name=name,
        value=value,
        package=_entry_point_package(entry_point),
        package_version=_entry_point_version(entry_point),
    )


def _coerce_group_filter(groups: Iterable[str] | None) -> frozenset[str] | None:
    if groups is None:
        return None

    normalized: set[str] = set()
    for group in groups:
        normalized.add(_coerce_non_empty_str(group, field="group"))
    return frozenset(normalized)


def _entry_point_package(entry_point: object) -> str | None:
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return None
    for attribute in ("name", "project_name", "_name"):
        value = getattr(distribution, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(distribution, str):
        stripped = distribution.strip()
        if stripped:
            return stripped
    return None


def _entry_point_version(entry_point: object) -> str | None:
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return None
    for attribute in ("version", "_version"):
        value = getattr(distribution, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(distribution, Mapping):
        metadata = distribution.get("Version")
        if isinstance(metadata, str) and metadata.strip():
            return metadata.strip()
    return None


def _coerce_non_empty_str(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise PluginInvalidEntryPointError(f"{field} must be a non-empty string")
    stripped = value.strip()
    if not stripped:
        raise PluginInvalidEntryPointError(f"{field} must be a non-empty string")
    return stripped


def _coerce_optional_str(value: str) -> str | None:
    stripped = value.strip()
    if stripped == "":
        return None
    return stripped


def _coerce_plugin_records(
    records: Iterable[PluginRecord],
    *,
    field: str,
) -> tuple[PluginRecord, ...]:
    if not isinstance(records, Iterable):
        raise PluginInvalidEntryPointError(f"{field} must be an iterable of PluginRecord")
    value = tuple(records)

    for index, record in enumerate(value):
        if not isinstance(record, PluginRecord):
            raise PluginInvalidEntryPointError(
                f"{field}[{index}] must be a PluginRecord, got {type(record)!r}",
            )
    return value


def _load_entrypoint_value(value: str) -> object:
    module_name, sep, attr_path = value.partition(":")
    if not module_name:
        raise PluginLoadError(f"invalid entry-point value: {value!r}")

    module = importlib.import_module(module_name)
    if sep == "":
        return module

    target = module
    for attribute in attr_path.split("."):
        if not attribute:
            raise PluginLoadError(f"invalid entry-point value: {value!r}")
        target = getattr(target, attribute)
    return target


def _record_sort_key(record: PluginRecord) -> tuple[str, str, str]:
    return (record.group, record.name, record.value)


__all__ = [
    "KNOWN_PLUGIN_GROUPS",
    "LOOM_ARTIFACT_STORE_BACKENDS_GROUP",
    "LOOM_CODECS_GROUP",
    "LOOM_EXECUTORS_GROUP",
    "LOOM_EVENT_SINKS_GROUP",
    "LOOM_RECIPES_GROUP",
    "LOOM_RUN_EXPORTERS_GROUP",
    "LOOM_SOURCES_GROUP",
    "LOOM_SWEEP_PROVIDERS_GROUP",
    "PluginDuplicate",
    "PluginFailure",
    "PluginLoadError",
    "PluginLoadResult",
    "PluginRecord",
    "find_plugin_duplicates",
    "list_entry_points",
    "load_entry_points",
    "LoadedPlugin",
]
