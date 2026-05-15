"""Contract tests for plugin discovery metadata and loading semantics."""

from __future__ import annotations

from collections.abc import Iterable
from types import ModuleType

import importlib
import pytest

import loom.plugins.entrypoints as entrypoints
from loom.plugins import (
    KNOWN_PLUGIN_GROUPS,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    PluginDuplicateError,
    PluginLoadError,
    PluginRecord,
    load_entry_points,
)


pytestmark = pytest.mark.contract


class _DummyEP:
    def __init__(self, group: str, name: str, value: str) -> None:
        self.group = group
        self.name = name
        self.value = value


def _fake_provider(entries: Iterable[object]) -> callable[[], list[object]]:
    return lambda: list(entries)


def _module_for_name(name: str, with_factory: bool = True) -> ModuleType:
    module = ModuleType(name)
    if with_factory:
        module.factory = lambda: object()  # noqa: E731
    return module


def test_metadata_listing_does_not_import_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _fake_provider(
        [
            _DummyEP(group=LOOM_CODECS_GROUP, name="one", value="loom.plugins.contract_a:factory"),
            _DummyEP(group=LOOM_RECIPES_GROUP, name="two", value="loom.plugins.contract_b:factory"),
        ]
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        raise AssertionError(f"import called unexpectedly for {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    records = entrypoints.list_entry_points(provider=provider)

    assert len(records) == 2
    assert records[0].value == "loom.plugins.contract_a:factory"
    assert records[1].value == "loom.plugins.contract_b:factory"


def test_selected_loading_only_imports_selected_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="selected",
        value="loom.plugins.contract_selected:factory",
    )
    skipped = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="skipped",
        value="loom.plugins.contract_skipped:factory",
    )

    calls: list[str] = []

    def tracked_import(name: str, package: str | None = None) -> ModuleType:
        calls.append(name)
        if name == "loom.plugins.contract_selected":
            return _module_for_name(name)
        return _module_for_name(name, with_factory=False)

    monkeypatch.setattr(importlib, "import_module", tracked_import)

    result = load_entry_points((selected, skipped), selected=(selected,), strict=True)
    assert [item.record.name for item in result.loaded] == ["selected"]
    assert calls == ["loom.plugins.contract_selected"]
    assert result.failures == ()


def test_duplicates_short_circuit_in_strict_mode() -> None:
    duplicate_a = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="dup",
        value="loom.plugins.contract_dup:factory",
    )
    duplicate_b = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="dup",
        value="loom.plugins.contract_dup:second",
    )

    with pytest.raises(PluginDuplicateError):
        load_entry_points((duplicate_a, duplicate_b), strict=True)


def test_load_failures_are_reported_for_missing_targets() -> None:
    record = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="broken",
        value="loom.plugins.contract_missing:missing",
    )

    with pytest.raises(PluginLoadError) as exc_info:
        load_entry_points((record,), strict=True)

    result = exc_info.value.result
    assert result is not None
    assert result.failure_count == 1
    assert result.failures[0].operation == "load"
    assert result.failures[0].message


def test_future_group_constants_are_metadata_contracts_only() -> None:
    assert KNOWN_PLUGIN_GROUPS == (
        LOOM_RECIPES_GROUP,
        LOOM_CODECS_GROUP,
        LOOM_SOURCES_GROUP,
        LOOM_EXECUTORS_GROUP,
        LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        LOOM_RUN_EXPORTERS_GROUP,
        LOOM_SWEEP_PROVIDERS_GROUP,
        LOOM_EVENT_SINKS_GROUP,
    )

    assert not hasattr(entrypoints, "load_source_entry_points")
    assert not hasattr(entrypoints, "load_artifact_store_backend_entry_points")
    assert not hasattr(entrypoints, "load_sweep_provider_entry_points")
    assert not hasattr(entrypoints, "load_event_sink_entry_points")
