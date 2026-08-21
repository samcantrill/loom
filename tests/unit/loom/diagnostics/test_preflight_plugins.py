"""Unit tests for selected plugin preflight diagnostics."""

from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

import loom.diagnostics.preflight as preflight
from loom.diagnostics import (
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    run_preflight,
)
from loom.plugins import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
)


pytestmark = pytest.mark.unit

_FUTURE_GROUPS = (
    LOOM_SOURCES_GROUP,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
)


class _RecipeModule(ModuleType):
    recipe: object


def _entry_point(*, group: str, name: str, value: str) -> object:
    return SimpleNamespace(group=group, name=name, value=value)


def test_plugin_preflight_without_selectors_skips_without_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider() -> tuple[object, ...]:
        raise AssertionError("plugin discovery should not run without selectors")

    monkeypatch.setattr(preflight, "_plugin_entry_point_provider", fail_provider)

    result = run_preflight(
        PreflightRequest(config_path="base.yaml", groups=("plugins",))
    )

    assert result.groups == (PreflightGroup.PLUGINS,)
    assert [check.check_id for check in result.checks] == [
        "plugins.metadata",
        "plugins.load",
    ]
    assert all(check.status is PreflightCheckStatus.SKIP for check in result.checks)


def test_plugin_preflight_loads_selected_recipe_in_scratch_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_plugin_entry_point_provider",
        lambda: (
            _entry_point(
                group=LOOM_RECIPES_GROUP,
                name="selected",
                value="loom.plugins._selected:recipe",
            ),
            _entry_point(
                group=LOOM_RECIPES_GROUP,
                name="skipped",
                value="loom.plugins._skipped:recipe",
            ),
        ),
    )
    imported: list[str] = []
    real_import_module = importlib.import_module
    import weave.recipes.load as recipe_load

    def import_module(name: str, package: str | None = None) -> ModuleType:
        if not name.startswith("loom.plugins._"):
            return real_import_module(name, package)
        imported.append(name)
        module = _RecipeModule(name)
        module.recipe = lambda value: {"value": value}
        return module

    monkeypatch.setattr(recipe_load, "import_module", import_module)

    result = run_preflight(
        PreflightRequest(
            config_path="base.yaml",
            groups=("plugins",),
            plugin_groups=(LOOM_RECIPES_GROUP,),
            plugin_names=("selected",),
        )
    )

    assert [check.status for check in result.checks] == [
        PreflightCheckStatus.PASS,
        PreflightCheckStatus.PASS,
    ]
    assert imported == ["loom.plugins._selected"]
    counts = cast(dict[str, Any], result.checks[1].details["counts"])
    assert counts["loaded"] == 1


def test_plugin_preflight_loads_selected_event_sink_in_scratch_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_plugin_entry_point_provider",
        lambda: (
            _entry_point(
                group=LOOM_EVENT_SINKS_GROUP,
                name="selected",
                value="loom.plugins._selected_event_sink:sink",
            ),
            _entry_point(
                group=LOOM_EVENT_SINKS_GROUP,
                name="skipped",
                value="loom.plugins._skipped_event_sink:sink",
            ),
        ),
    )
    imported: list[str] = []
    calls: list[str] = []

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        imported.append(name)
        module = ModuleType(name)

        def sink(event: object, context: object) -> None:
            del event, context
            calls.append(name)

        module.sink = sink  # type: ignore[attr-defined]
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = run_preflight(
        PreflightRequest(
            config_path="base.yaml",
            groups=("plugins",),
            plugin_groups=(LOOM_EVENT_SINKS_GROUP,),
            plugin_names=("selected",),
        )
    )

    assert [check.status for check in result.checks] == [
        PreflightCheckStatus.PASS,
        PreflightCheckStatus.PASS,
    ]
    assert imported == ["loom.plugins._selected_event_sink"]
    assert calls == []
    counts = cast(dict[str, Any], result.checks[1].details["counts"])
    assert counts["loaded"] == 1


def test_plugin_preflight_reports_listing_only_groups_without_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_plugin_entry_point_provider",
        lambda: (
            _entry_point(
                group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                name="store",
                value="loom.plugins._store:backend",
            ),
        ),
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        del package
        raise AssertionError(f"unexpected plugin import {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    result = run_preflight(
        PreflightRequest(
            config_path="base.yaml",
            groups=("plugins",),
            plugin_groups=(LOOM_ARTIFACT_STORE_BACKENDS_GROUP,),
        )
    )

    assert result.checks[0].status is PreflightCheckStatus.PASS
    assert result.checks[1].status is PreflightCheckStatus.SKIP
    unsupported_groups = cast(list[str], result.checks[1].details["unsupported_groups"])
    assert unsupported_groups == [LOOM_ARTIFACT_STORE_BACKENDS_GROUP]


@pytest.mark.parametrize("group", _FUTURE_GROUPS)
def test_plugin_preflight_skips_loading_for_future_groups(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_plugin_entry_point_provider",
        lambda: (
            _entry_point(
                group=group,
                name="future",
                value="loom.plugins._future:factory",
            ),
        ),
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        del package
        raise AssertionError(f"future group target should not be imported: {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    result = run_preflight(
        PreflightRequest(
            config_path="base.yaml",
            groups=("plugins",),
            plugin_groups=(group,),
        )
    )

    assert result.checks[0].status is PreflightCheckStatus.PASS
    assert result.checks[1].status is PreflightCheckStatus.SKIP
    unsupported_groups = cast(list[str], result.checks[1].details["unsupported_groups"])
    assert unsupported_groups == [group]
