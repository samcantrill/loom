"""Recipe entry-point loading helpers owned by `weave`.

The implementation intentionally duplicates only minimal plugin-surface behavior
needed by config composition.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from .base import RecipeImplementation

LOOM_RECIPES_GROUP = "loom.recipes"


class _RecipeCatalog(Protocol):
    def register(self, name: str, recipe: RecipeImplementation, *, replace: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class RecipePluginRecord:
    """Metadata for one discovered recipe plugin entry point."""

    group: str
    name: str
    value: str
    package: str | None = None
    package_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "group", _coerce_non_empty_str(self.group, field="group"))
        object.__setattr__(self, "name", _coerce_non_empty_str(self.name, field="name"))
        object.__setattr__(self, "value", _coerce_non_empty_str(self.value, field="value"))
        if self.package is not None:
            object.__setattr__(self, "package", _coerce_optional_str(self.package, field="package"))
        if self.package_version is not None:
            object.__setattr__(
                self,
                "package_version",
                _coerce_optional_str(self.package_version, field="package_version"),
            )


@dataclass(frozen=True, slots=True)
class RecipePluginDuplicate:
    group: str
    name: str
    records: tuple[RecipePluginRecord, ...]

    def __post_init__(self) -> None:
        if len(self.records) < 2:
            raise ValueError("RecipePluginDuplicate requires at least two records")
        if not self.group:
            raise ValueError("RecipePluginDuplicate.group must not be empty")
        if not self.name:
            raise ValueError("RecipePluginDuplicate.name must not be empty")


@dataclass(frozen=True, slots=True)
class RecipePluginLoadFailure:
    record: RecipePluginRecord
    operation: str
    error_type: str
    message: str

    @classmethod
    def from_exception(
        cls,
        record: RecipePluginRecord,
        operation: str,
        exc: BaseException,
    ) -> "RecipePluginLoadFailure":
        return cls(
            record=record,
            operation=operation,
            error_type=type(exc).__name__,
            message=str(exc),
        )


@dataclass(frozen=True, slots=True)
class RecipePluginLoadResult:
    loaded: tuple[RecipePluginRecord, ...]
    duplicates: tuple[RecipePluginDuplicate, ...]
    failures: tuple[RecipePluginLoadFailure, ...]

    @property
    def ok(self) -> bool:
        return not self.duplicates and not self.failures


class RecipePluginError(RuntimeError):
    """Base recipe plugin loading error."""


class RecipePluginDuplicateError(RecipePluginError):
    """Duplicate recipe entry points were detected in strict mode."""

    def __init__(
        self,
        duplicates: tuple[RecipePluginDuplicate, ...],
        *,
        result: RecipePluginLoadResult | None = None,
    ) -> None:
        super().__init__("recipe plugin duplicate records found in strict mode")
        self.duplicates = duplicates
        self.result = result


class RecipePluginLoadError(RecipePluginError):
    """One or more recipe plugin loads failed in strict mode."""

    def __init__(self, *, result: RecipePluginLoadResult) -> None:
        super().__init__("recipe plugin load failed in strict mode")
        self.result = result


def load_recipe_entry_points(
    records: Iterable[RecipePluginRecord],
    catalog: _RecipeCatalog,
    *,
    selected: Iterable[RecipePluginRecord] | None = None,
    strict: bool = True,
    replace: bool = False,
) -> RecipePluginLoadResult:
    """Load recipe entry points into a recipe catalog."""

    all_records = tuple(_coerce_records(records, field="records"))
    if selected is None:
        candidate_records = tuple(_filter_records(all_records, LOOM_RECIPES_GROUP))
    else:
        requested = tuple(_coerce_records(selected, field="selected"))
        candidate_records = tuple(
            record for record in _filter_records(all_records, LOOM_RECIPES_GROUP)
            if _record_requested(record, requested)
        )

    duplicates = _find_duplicates(candidate_records)
    duplicate_map = {(item.group, item.name): item for item in duplicates}

    if strict and duplicates:
        result = RecipePluginLoadResult(
            loaded=(),
            duplicates=duplicates,
            failures=(),
        )
        raise RecipePluginDuplicateError(duplicates=duplicates, result=result)

    # Deduplicate keys deterministically and preserve first non-duplicate record by path.
    selected_by_key: dict[tuple[str, str], RecipePluginRecord] = {}
    for record in sorted(candidate_records, key=_record_sort_key):
        key = (record.group, record.name)
        if key in duplicate_map:
            continue
        if key in selected_by_key and not replace:
            continue
        selected_by_key[key] = record

    loaded: list[RecipePluginRecord] = []
    failures: list[RecipePluginLoadFailure] = []
    for key in sorted(selected_by_key):
        record = selected_by_key[key]
        try:
            recipe = _load_entry_point_value(record.value)
        except Exception as exc:  # noqa: BLE001
            failures.append(RecipePluginLoadFailure.from_exception(record, operation="load", exc=exc))
            continue

        try:
            catalog.register(name=record.name, recipe=cast(RecipeImplementation, recipe), replace=replace)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                RecipePluginLoadFailure.from_exception(
                    record,
                    operation="register",
                    exc=exc,
                )
            )
            continue

        loaded.append(record)

    result = RecipePluginLoadResult(
        loaded=tuple(loaded),
        duplicates=duplicates,
        failures=tuple(failures),
    )

    if strict and failures:
        raise RecipePluginLoadError(result=result)

    return result


def _record_requested(
    record: RecipePluginRecord,
    requested: tuple[RecipePluginRecord, ...],
) -> bool:
    if not requested:
        return False
    return any(
        request.group == record.group and request.name == record.name
        for request in requested
    )


def _find_duplicates(records: Iterable[RecipePluginRecord]) -> tuple[RecipePluginDuplicate, ...]:
    by_key: dict[tuple[str, str], list[RecipePluginRecord]] = {}
    for record in records:
        by_key.setdefault((record.group, record.name), []).append(record)

    duplicates: list[RecipePluginDuplicate] = []
    for (group, name), entries in by_key.items():
        if len(entries) <= 1:
            continue
        duplicates.append(RecipePluginDuplicate(group=group, name=name, records=tuple(entries)))
    return tuple(sorted(duplicates, key=lambda item: (item.group, item.name)))


def _filter_records(records: Iterable[RecipePluginRecord], group: str) -> tuple[RecipePluginRecord, ...]:
    return tuple(record for record in records if record.group == group)


def _coerce_records(records: Iterable[RecipePluginRecord] | None, *, field: str) -> tuple[RecipePluginRecord, ...]:
    if records is None:
        return ()
    normalized: list[RecipePluginRecord] = []
    for record in records:
        if not isinstance(record, RecipePluginRecord):
            raise TypeError(f"{field} entries must be RecipePluginRecord")
        normalized.append(record)
    return tuple(normalized)


def _coerce_non_empty_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field} must be a non-empty string")
    return value.strip()


def _coerce_optional_str(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or None")
    return value.strip()


def _load_entry_point_value(value: str) -> object:
    module_name, sep, target_name = value.partition(":")
    if not sep:
        raise ValueError(f"Invalid entry point value {value!r}; expected <module>:<attr>")

    module = import_module(module_name)
    if not hasattr(module, target_name):
        raise AttributeError(f"Module {module_name!r} has no attribute {target_name!r}")
    return getattr(module, target_name)


def _record_sort_key(record: RecipePluginRecord) -> tuple[str, str, str]:
    return (record.group, record.name, record.value)


__all__ = [
    "LOOM_RECIPES_GROUP",
    "RecipeImplementation",
    "RecipePluginDuplicate",
    "RecipePluginDuplicateError",
    "RecipePluginError",
    "RecipePluginLoadFailure",
    "RecipePluginLoadError",
    "RecipePluginLoadResult",
    "RecipePluginRecord",
    "load_recipe_entry_points",
]
