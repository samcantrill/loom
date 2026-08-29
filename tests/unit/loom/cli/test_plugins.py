"""Unit tests for ``loom plugins`` commands."""

from __future__ import annotations

import importlib
import io
import json
from collections.abc import Iterable
from types import ModuleType, SimpleNamespace

import pytest

import loom.cli.plugins as plugins_command
from loom.cli.main import main
from loom.plugins import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
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
    return SimpleNamespace(group=group, name=name, value=value, dist=dist)


def _fake_provider(entries: Iterable[object]) -> plugins_command.EntryPointProvider:
    entries_tuple = tuple(entries)
    return lambda: entries_tuple


def test_plugins_list_json_is_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_RECIPES_GROUP,
                    name="alpha",
                    value="loom.plugins._alpha:recipe",
                    package="plugin-a",
                    version="1.0.0",
                ),
            )
        ),
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        del package
        raise AssertionError(f"unexpected plugin import {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["plugins", "list", "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == plugins_command.PLUGINS_LIST_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["records"] == [
        {
            "group": LOOM_RECIPES_GROUP,
            "name": "alpha",
            "value": "loom.plugins._alpha:recipe",
            "package": "plugin-a",
            "package_version": "1.0.0",
            "status": "metadata",
            "readiness": "registry-ready",
        }
    ]
    assert stderr.getvalue() == ""


def test_plugins_list_load_imports_only_selected_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_RECIPES_GROUP,
                    name="selected",
                    value="loom.plugins._selected:recipe",
                ),
                _fake_entry_point(
                    group=LOOM_RECIPES_GROUP,
                    name="skipped",
                    value="loom.plugins._skipped:recipe",
                ),
            )
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
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "plugins",
                "list",
                "--load",
                "--group",
                LOOM_RECIPES_GROUP,
                "--name",
                "selected",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert imported == ["loom.plugins._selected"]
    payload = json.loads(stdout.getvalue())
    assert payload["result"]["records"][0]["status"] == "loaded"
    assert payload["result"]["counts"]["loaded"] == 1
    assert stderr.getvalue() == ""


def test_plugins_check_reports_listing_only_group_as_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                    name="store",
                    value="loom.plugins._store:backend",
                ),
            )
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "plugins",
                "check",
                "--group",
                LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == plugins_command.PLUGINS_CHECK_SCHEMA_VERSION
    assert payload["ok"] is False
    assert payload["result"]["unsupported_groups"] == [
        LOOM_ARTIFACT_STORE_BACKENDS_GROUP
    ]
    assert payload["result"]["records"][0]["status"] == "listing-only"
    assert stderr.getvalue() == ""


def test_plugins_list_labels_all_future_groups_listing_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            _fake_entry_point(
                group=group,
                name=f"plugin-{index}",
                value=f"loom.plugins._future_{index}:factory",
            )
            for index, group in enumerate(_FUTURE_GROUPS)
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["plugins", "list", "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    by_group = {record["group"]: record for record in payload["result"]["records"]}
    assert set(by_group) == set(_FUTURE_GROUPS)
    assert {record["readiness"] for record in by_group.values()} == {"listing-only"}
    assert {record["status"] for record in by_group.values()} == {"listing-only"}
    assert stderr.getvalue() == ""


def test_plugins_list_labels_event_sinks_registry_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_EVENT_SINKS_GROUP,
                    name="audit",
                    value="loom.plugins._event_sink:audit",
                ),
            )
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["plugins", "list", "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    record = payload["result"]["records"][0]
    assert record["group"] == LOOM_EVENT_SINKS_GROUP
    assert record["readiness"] == "registry-ready"
    assert record["status"] == "metadata"
    assert stderr.getvalue() == ""


def test_plugins_list_text_reports_facet_evidence_without_importing_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_EXECUTORS_GROUP,
                    name="project",
                    value="loom.plugins._project:executor",
                ),
            )
        ),
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        del package
        raise AssertionError(f"listing-only target should not be imported: {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plugins", "list", "--group", LOOM_EXECUTORS_GROUP],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    output = stdout.getvalue()
    assert "readiness loom.executors contract: supported" in output
    assert "readiness loom.executors plugin_loading: supported" in output
    assert "readiness loom.executors cli_selection: supported" in output
    assert "readiness loom.sources registry: not_applicable" in output
    assert "Run commands explicitly select ordinary executor plugins." in output
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("group", _FUTURE_GROUPS)
def test_plugins_check_does_not_import_future_group_targets(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=group,
                    name="future",
                    value="loom.plugins._future:factory",
                ),
            )
        ),
    )

    def fail_import(name: str, package: str | None = None) -> ModuleType:
        del package
        raise AssertionError(f"future group target should not be imported: {name}")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plugins", "check", "--group", group, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["unsupported_groups"] == [group]
    assert payload["result"]["records"][0]["readiness"] == "listing-only"
    assert stderr.getvalue() == ""


def test_plugins_check_loads_selected_event_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        _fake_provider(
            (
                _fake_entry_point(
                    group=LOOM_EVENT_SINKS_GROUP,
                    name="audit",
                    value="loom.plugins._event_sink:audit",
                ),
            )
        ),
    )
    imported: list[str] = []

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        imported.append(name)
        module = ModuleType(name)

        def audit(event: object, context: object) -> None:
            del event, context

        module.audit = audit  # type: ignore[attr-defined]
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "plugins",
                "check",
                "--group",
                LOOM_EVENT_SINKS_GROUP,
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert imported == ["loom.plugins._event_sink"]
    assert payload["result"]["unsupported_groups"] == []
    assert payload["result"]["records"][0]["status"] == "loaded"
    assert payload["result"]["records"][0]["readiness"] == "registry-ready"
    assert stderr.getvalue() == ""


def test_plugins_check_requires_selector() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["plugins", "check", "--format", "json"], stdout=stdout, stderr=stderr)
        == 2
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.plugins.check_requires_selector"
    assert stderr.getvalue() == ""


def test_plugins_help_does_not_discover_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider() -> tuple[object, ...]:
        raise AssertionError("entry point discovery should not happen for help")

    monkeypatch.setattr(plugins_command, "_entry_point_provider", fail_provider)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["plugins", "--help"], stdout=stdout, stderr=stderr) == 0

    assert "list" in stdout.getvalue()
    assert "check" in stdout.getvalue()
    assert stderr.getvalue() == ""
