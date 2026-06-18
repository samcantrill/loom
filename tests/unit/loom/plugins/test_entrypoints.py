"""Unit tests for plugin entry-point discovery and loading records."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from types import ModuleType, SimpleNamespace

import pytest

from loom.plugins import (
    LOOM_CODECS_GROUP,
    LOOM_RECIPES_GROUP,
    KNOWN_PLUGIN_GROUPS,
    PluginDuplicate,
    PluginDuplicateError,
    PluginFailure,
    PluginLoadError,
    PluginRecord,
    PluginRegistrationError,
    find_plugin_duplicates,
    list_entry_points,
    load_entry_points,
)


class _FactoryModule(ModuleType):
    factory: Callable[[], object]


class _TrackingModuleFactory:
    def __init__(self, with_factory: bool = True) -> None:
        self.calls: list[str] = []
        self.with_factory = with_factory

    def __call__(self, name: str, package: str | None = None) -> ModuleType:
        self.calls.append(name)
        module = _FactoryModule(name)
        if self.with_factory:
            module.factory = lambda: object()  # noqa: E731
        return module


class _NoFactoryModuleFactory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, name: str, package: str | None = None) -> ModuleType:
        self.calls.append(name)
        return ModuleType(name)


def _fake_entry_point(
    *,
    group: str,
    name: str,
    value: str,
    package: str | None = None,
    version: str | None = None,
) -> object:
    dist = None
    if package is not None or version is not None:
        dist = SimpleNamespace(name=package, version=version)

    class FakeEP:
        def __init__(self) -> None:
            self._loaded = False

        def load(self) -> object:
            self._loaded = True
            raise AssertionError("entry point loading should not happen during listing")

    return SimpleNamespace(
        group=group,
        name=name,
        value=value,
        dist=dist,
        load=FakeEP().load,
    )


def _fake_provider(entries: Iterable[object]) -> Callable[[], list[object]]:
    return lambda: list(entries)


def test_known_group_constants_match_plan() -> None:
    assert KNOWN_PLUGIN_GROUPS == (
        "loom.recipes",
        "loom.codecs",
        "loom.sources",
        "loom.executors",
        "loom.artifact_store_backends",
        "loom.run_exporters",
        "loom.sweep_providers",
        "loom.event_sinks",
    )

    assert set(KNOWN_PLUGIN_GROUPS) == {
        LOOM_RECIPES_GROUP,
        LOOM_CODECS_GROUP,
        "loom.sources",
        "loom.executors",
        "loom.artifact_store_backends",
        "loom.run_exporters",
        "loom.sweep_providers",
        "loom.event_sinks",
    }


def test_list_entry_points_is_deterministic_and_does_not_import_targets() -> None:
    provider = _fake_provider(
        [
            _fake_entry_point(
                group=LOOM_CODECS_GROUP,
                name="zeta",
                value="missing.module:object",
                package="backend-a",
                version="0.1.0",
            ),
            _fake_entry_point(
                group=LOOM_RECIPES_GROUP,
                name="alpha",
                value="missing.module.other:factory",
                package="backend-b",
                version="1.2.3",
            ),
            _fake_entry_point(
                group=LOOM_CODECS_GROUP,
                name="alpha",
                value="missing.again:builder",
            ),
        ]
    )

    records = list_entry_points(provider=provider)
    assert [(record.group, record.name, record.value) for record in records] == [
        (LOOM_CODECS_GROUP, "alpha", "missing.again:builder"),
        (LOOM_CODECS_GROUP, "zeta", "missing.module:object"),
        (LOOM_RECIPES_GROUP, "alpha", "missing.module.other:factory"),
    ]
    assert records[0].package is None
    assert records[0].package_version is None
    assert records[1].package == "backend-a"
    assert records[1].package_version == "0.1.0"
    assert records[2].package == "backend-b"
    assert records[2].package_version == "1.2.3"


def test_find_plugin_duplicates_identifies_group_name_conflicts() -> None:
    records = (
        PluginRecord(
            group=LOOM_RECIPES_GROUP,
            name="same",
            value="math:sqrt",
            package="pkg-a",
        ),
        PluginRecord(
            group=LOOM_RECIPES_GROUP,
            name="same",
            value="math:pow",
            package="pkg-b",
        ),
        PluginRecord(group=LOOM_RECIPES_GROUP, name="unique", value="math:prod"),
        PluginRecord(group=LOOM_CODECS_GROUP, name="same", value="math:floor"),
    )
    duplicates = find_plugin_duplicates(records)
    assert duplicates == (
        PluginDuplicate(
            group=LOOM_RECIPES_GROUP,
            name="same",
            records=(
                PluginRecord(
                    group=LOOM_RECIPES_GROUP,
                    name="same",
                    value="math:sqrt",
                    package="pkg-a",
                ),
                PluginRecord(
                    group=LOOM_RECIPES_GROUP,
                    name="same",
                    value="math:pow",
                    package="pkg-b",
                ),
            ),
        ),
    )


def test_load_entry_points_loads_only_selected_records(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="selected",
        value="loom.plugins._selected:factory",
    )
    skipped = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="skipped",
        value="loom.plugins._skipped:factory",
    )

    tracker = _TrackingModuleFactory()
    monkeypatch.setattr(importlib, "import_module", tracker)

    result = load_entry_points(
        (selected, skipped),
        selected=(selected,),
        strict=True,
    )

    assert [item.record.name for item in result.loaded] == ["selected"]
    assert tracker.calls == ["loom.plugins._selected"]
    assert result.failures == ()


def test_strict_mode_fails_closed_for_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate_a = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="shared",
        value="loom.plugins._dup:first",
    )
    duplicate_b = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="shared",
        value="loom.plugins._dup:second",
    )
    unique = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="unique",
        value="loom.plugins._unique:factory",
    )
    tracker = _TrackingModuleFactory()
    monkeypatch.setattr(importlib, "import_module", tracker)

    with pytest.raises(PluginDuplicateError) as exc_info:
        load_entry_points((duplicate_a, duplicate_b, unique), strict=True)

    strict_result = exc_info.value.result
    assert strict_result is not None
    assert strict_result.duplicate_count == 1
    assert strict_result.failure_count == 0
    assert strict_result.loaded_count == 0
    assert tracker.calls == []


def test_strict_mode_wraps_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="broken",
        value="loom.plugins._missing:missing",
    )
    missing_factory = _NoFactoryModuleFactory()
    monkeypatch.setattr(importlib, "import_module", missing_factory)

    with pytest.raises(PluginLoadError) as exc_info:
        load_entry_points((broken,), strict=True)

    load_error_result = exc_info.value.result
    assert load_error_result is not None
    assert load_error_result.failure_count == 1
    assert load_error_result.duplicates == ()
    assert load_error_result.failures[0].operation == "load"


def test_best_effort_collects_failures_and_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    good = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="ok",
        value="loom.plugins._ok:factory",
    )
    duplicate_a = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="shared",
        value="loom.plugins._dup:first",
    )
    duplicate_b = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="shared",
        value="loom.plugins._dup:second",
    )
    missing = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="missing",
        value="loom.plugins._missing:missing",
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        module = _FactoryModule(name)
        if name == "loom.plugins._ok":
            module.factory = lambda: object()  # noqa: E731
        if name == "loom.plugins._missing":
            # module exists but target attribute is absent.
            pass
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = load_entry_points((good, duplicate_a, duplicate_b, missing), strict=False)

    assert result.loaded_count == 1
    assert result.loaded[0].record.name == "ok"
    assert result.duplicate_count == 1
    assert result.failure_count == 1
    assert result.failures[0].operation == "load"
    assert result.failures[0].error_type == "AttributeError"


def test_registration_failure_is_reported_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FactoryModule("loom.plugins._register")
    module.factory = lambda: "plugin"  # noqa: E731

    def import_module(name: str, package: str | None = None) -> ModuleType:
        if name == "loom.plugins._register":
            return module
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr(importlib, "import_module", import_module)

    def register(record: PluginRecord, _value: object) -> None:
        raise RuntimeError(f"cannot register {record.name}")

    records = (PluginRecord(group=LOOM_CODECS_GROUP, name="one", value="loom.plugins._register:factory"),)
    result = load_entry_points(records, selected=records, strict=False, register=register)

    assert result.failure_count == 1
    failure = result.failures[0]
    assert failure.operation == "registration"
    assert failure.error_type == "RuntimeError"
    assert failure.message == "cannot register one"
    assert result.loaded_count == 0

    with pytest.raises(PluginRegistrationError):
        load_entry_points(records, selected=records, strict=True, register=register)


def test_load_summary_omits_python_objects() -> None:
    record = PluginRecord(group=LOOM_RECIPES_GROUP, name="summary", value="loom.plugins._summary:factory")
    loaded = PluginFailure.from_exception(
        record=record,
        operation="load",
        exc=RuntimeError("boom"),
    )

    summary = loaded.to_summary()
    assert summary["error_type"] == "RuntimeError"
    assert summary["message"] == "boom"
    assert "traceback" not in summary

    loaded_summary = record.to_summary()
    assert loaded_summary == {
        "group": LOOM_RECIPES_GROUP,
        "name": "summary",
        "value": "loom.plugins._summary:factory",
    }


def test_load_result_summary_keeps_only_plain_data(monkeypatch: pytest.MonkeyPatch) -> None:
    record = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="plain",
        value="loom.plugins._plain:factory",
    )

    module = _FactoryModule("loom.plugins._plain")
    module.factory = lambda: {"secret": object()}  # noqa: E731

    monkeypatch.setattr(importlib, "import_module", lambda name, package=None: module)

    result = load_entry_points((record,), strict=False)
    summary = result.to_summary()
    loaded_entries = summary["loaded"]
    assert isinstance(loaded_entries, list)
    loaded_summary = loaded_entries[0]
    assert isinstance(loaded_summary, dict)
    assert loaded_summary["group"] == LOOM_CODECS_GROUP
    assert loaded_summary["name"] == "plain"
    assert loaded_summary["value"] == "loom.plugins._plain:factory"
    assert loaded_summary["loaded"] is True
    assert "secret" not in str(loaded_summary)
