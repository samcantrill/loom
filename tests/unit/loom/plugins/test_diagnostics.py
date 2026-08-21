"""Unit tests for plugin diagnostic summaries."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, cast

import pytest

from loom.plugins import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    LOADABLE_PLUGIN_GROUPS,
    PLUGIN_GROUP_READINESS,
    PluginRecord,
    PluginSelection,
    READINESS_FACETS,
    check_plugin_records,
    plugin_group_readiness,
    summarize_plugin_records,
)


pytestmark = pytest.mark.unit

_LISTING_ONLY_GROUPS = (
    LOOM_SOURCES_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
)


def test_group_readiness_classifies_registry_ready_groups() -> None:
    assert LOADABLE_PLUGIN_GROUPS == (
        LOOM_RECIPES_GROUP,
        LOOM_CODECS_GROUP,
        LOOM_EVENT_SINKS_GROUP,
    )
    assert PLUGIN_GROUP_READINESS[LOOM_RECIPES_GROUP] == "registry-ready"
    assert PLUGIN_GROUP_READINESS[LOOM_CODECS_GROUP] == "registry-ready"
    assert PLUGIN_GROUP_READINESS[LOOM_EVENT_SINKS_GROUP] == "registry-ready"
    assert plugin_group_readiness(LOOM_EVENT_SINKS_GROUP).to_summary()["status"] == (
        "registry-ready"
    )

    for group in _LISTING_ONLY_GROUPS:
        readiness = plugin_group_readiness(group)
        assert readiness.group == group
        assert readiness.status == "listing-only"
        assert readiness.reason
        assert readiness.revisit_trigger
        assert readiness.to_summary()["status"] == "listing-only"


def test_group_readiness_exposes_fixed_facet_evidence_and_derives_status() -> None:
    readiness = plugin_group_readiness(LOOM_EXECUTORS_GROUP)

    assert tuple(readiness.facets) == READINESS_FACETS
    assert readiness.facets["contract"].status == "supported"
    assert readiness.facets["registry"].status == "unsupported"
    assert readiness.facets["plugin_loading"].status == "unsupported"
    assert readiness.status == "listing-only"
    assert readiness.to_summary()["facets"]["cli_selection"] == {
        "status": "unsupported",
        "evidence": "Run commands do not yet select executor plugins.",
    }


def test_summarize_plugin_records_keeps_metadata_plain_and_listing_only() -> None:
    record = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="local-plus",
        value="loom.plugins._store:backend",
        package="loom-extra-store",
        package_version="1.0.0",
    )

    result = summarize_plugin_records((record,), selection=PluginSelection(groups=(record.group,)))

    assert result.ok is True
    assert result.to_summary() == {
        "selection": {
            "groups": [LOOM_ARTIFACT_STORE_BACKENDS_GROUP],
            "names": [],
            "packages": [],
        },
        "load_requested": False,
        "ok": True,
        "records": [
            {
                "group": LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                "name": "local-plus",
                "value": "loom.plugins._store:backend",
                "package": "loom-extra-store",
                "package_version": "1.0.0",
                "status": "listing-only",
                "readiness": "listing-only",
            }
        ],
        "loaded": [],
        "duplicates": [],
        "failures": [],
        "missing": [],
        "unsupported_groups": [],
        "listing_only": [
            {
                "group": LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                "name": "local-plus",
                "value": "loom.plugins._store:backend",
                "package": "loom-extra-store",
                "package_version": "1.0.0",
                "status": "listing-only",
                "readiness": "listing-only",
            }
        ],
        "counts": {
            "records": 1,
            "loaded": 0,
            "duplicates": 0,
            "failures": 0,
            "missing": 0,
            "unsupported_groups": 0,
            "listing_only": 1,
        },
    }


def test_check_plugin_records_loads_selected_recipe_only(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="selected",
        value="loom.plugins._recipe_selected:recipe",
    )
    skipped = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="skipped",
        value="loom.plugins._recipe_skipped:recipe",
    )
    imported: list[str] = []
    real_import_module = importlib.import_module
    import weave.recipes.load as recipe_load

    def import_module(name: str, package: str | None = None) -> ModuleType:
        if not name.startswith("loom.plugins._"):
            return real_import_module(name, package)
        imported.append(name)
        module = ModuleType(name)
        module.recipe = lambda value: {"value": value}  # type: ignore[attr-defined]
        return module

    monkeypatch.setattr(recipe_load, "import_module", import_module)

    result = check_plugin_records(
        (selected, skipped),
        selection=PluginSelection(groups=(LOOM_RECIPES_GROUP,), names=("selected",)),
    )

    assert result.ok is True
    assert imported == ["loom.plugins._recipe_selected"]
    summary = result.to_summary()
    assert summary["loaded"] == [selected.to_summary()]
    records = cast(list[dict[str, Any]], summary["records"])
    assert records[0]["status"] == "loaded"


def test_check_plugin_records_loads_selected_event_sink_in_scratch_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="selected",
        value="loom.plugins._event_sink_selected:sink",
    )
    skipped = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="skipped",
        value="loom.plugins._event_sink_skipped:sink",
    )
    imported: list[str] = []

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        imported.append(name)
        module = ModuleType(name)

        def sink(event: object, context: object) -> None:
            del event, context

        module.sink = sink  # type: ignore[attr-defined]
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = check_plugin_records(
        (selected, skipped),
        selection=PluginSelection(
            groups=(LOOM_EVENT_SINKS_GROUP,),
            names=("selected",),
        ),
    )

    assert result.ok is True
    assert imported == ["loom.plugins._event_sink_selected"]
    summary = result.to_summary()
    assert summary["loaded"] == [selected.to_summary()]
    records = cast(list[dict[str, Any]], summary["records"])
    assert records[0]["status"] == "loaded"
    assert records[0]["readiness"] == "registry-ready"


def test_check_plugin_records_fails_closed_for_missing_and_listing_only() -> None:
    record = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="store",
        value="loom.plugins._store:backend",
    )

    result = check_plugin_records(
        (record,),
        selection=PluginSelection(
            groups=(LOOM_ARTIFACT_STORE_BACKENDS_GROUP,),
            names=("missing",),
        ),
    )

    assert result.ok is False
    assert [item.to_summary() for item in result.missing] == [
        {"field": "group", "value": LOOM_ARTIFACT_STORE_BACKENDS_GROUP},
        {"field": "name", "value": "missing"},
    ]
    assert result.unsupported_groups == (LOOM_ARTIFACT_STORE_BACKENDS_GROUP,)
