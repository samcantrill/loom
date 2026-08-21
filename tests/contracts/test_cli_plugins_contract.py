"""Contract tests for ``loom plugins`` JSON output."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

import loom.cli.plugins as plugins_command
from loom.cli.main import main
from loom.plugins import LOOM_ARTIFACT_STORE_BACKENDS_GROUP, LOOM_RECIPES_GROUP


pytestmark = pytest.mark.contract


def _entry_point(*, group: str, name: str, value: str) -> object:
    return SimpleNamespace(group=group, name=name, value=value)


def test_plugins_list_json_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        lambda: (
            _entry_point(
                group=LOOM_RECIPES_GROUP,
                name="alpha",
                value="loom.plugins.contract_recipe:recipe",
            ),
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["plugins", "list", "--format", "json"], stdout=stdout, stderr=stderr) == 0

    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plugins.list.v2"
    assert payload["ok"] is True
    assert payload["warnings"] == []
    assert payload["result"]["records"] == [
        {
            "group": LOOM_RECIPES_GROUP,
            "name": "alpha",
            "value": "loom.plugins.contract_recipe:recipe",
            "status": "metadata",
            "readiness": "registry-ready",
        }
    ]
    readiness = payload["result"]["group_readiness"]
    assert [item["group"] for item in readiness][:2] == [LOOM_RECIPES_GROUP, "loom.codecs"]
    assert set(readiness[0]["facets"]) == {
        "contract",
        "python_injection",
        "registry",
        "plugin_loading",
        "cli_selection",
        "fresh_process_reconstruction",
    }


def test_plugins_check_listing_only_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugins_command,
        "_entry_point_provider",
        lambda: (
            _entry_point(
                group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
                name="backend",
                value="loom.plugins.contract_store:backend",
            ),
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
    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.plugins.check.v2"
    assert payload["ok"] is False
    assert payload["result"]["records"][0]["readiness"] == "listing-only"
    assert payload["result"]["unsupported_groups"] == [LOOM_ARTIFACT_STORE_BACKENDS_GROUP]
