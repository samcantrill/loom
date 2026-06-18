"""Focused integration tests for plugin diagnostics preflight."""

from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

import loom.diagnostics.preflight as preflight
from loom.diagnostics import PreflightCheckStatus, PreflightRequest, run_preflight
from loom.plugins import LOOM_RECIPES_GROUP


pytestmark = pytest.mark.integration


class _RecipeModule(ModuleType):
    recipe: object


def test_plugin_preflight_reports_selected_load_failure_and_metadata_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_plugin_entry_point_provider",
        lambda: (
            SimpleNamespace(
                group=LOOM_RECIPES_GROUP,
                name="ok",
                value="loom.plugins._ok:recipe",
            ),
            SimpleNamespace(
                group=LOOM_RECIPES_GROUP,
                name="broken",
                value="loom.plugins._broken:recipe",
            ),
        ),
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        if name == "loom.plugins._broken":
            raise RuntimeError("broken import")
        module = _RecipeModule(name)
        module.recipe = lambda value: {"value": value}
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = run_preflight(
        PreflightRequest(
            config_path="base.yaml",
            groups=("plugins",),
            plugin_groups=(LOOM_RECIPES_GROUP,),
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert by_id["plugins.metadata"].status is PreflightCheckStatus.PASS
    assert by_id["plugins.load"].status is PreflightCheckStatus.FAIL
    counts = cast(dict[str, Any], by_id["plugins.load"].details["counts"])
    assert counts["loaded"] == 1
    assert counts["failures"] == 1
