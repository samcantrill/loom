"""Package-level plugin public API tests."""

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_import_loom_plugins_public_symbols() -> None:
    import loom.plugins as plugins

    assert plugins.__all__
    assert plugins.KNOWN_PLUGIN_GROUPS
    assert plugins.LOOM_RECIPES_GROUP == "loom.recipes"
    assert plugins.LOOM_CODECS_GROUP == "loom.codecs"
    assert plugins.LOOM_SOURCES_GROUP == "loom.sources"
    assert plugins.LOOM_EXECUTORS_GROUP == "loom.executors"
    assert plugins.LOOM_ARTIFACT_STORE_BACKENDS_GROUP == "loom.artifact_store_backends"
    assert plugins.LOOM_RUN_EXPORTERS_GROUP == "loom.run_exporters"
    assert plugins.LOOM_SWEEP_PROVIDERS_GROUP == "loom.sweep_providers"
    assert plugins.LOOM_EVENT_SINKS_GROUP == "loom.event_sinks"

    assert plugins.PluginRecord
    assert plugins.LoadedPlugin
    assert plugins.PluginDuplicate
    assert plugins.PluginFailure
    assert plugins.PluginLoadResult
    assert plugins.PluginDiscoveryError
    assert plugins.PluginInvalidEntryPointError
    assert plugins.PluginDuplicateError
    assert plugins.PluginRegistrationError
    assert plugins.PluginLoadError
    assert plugins.load_recipe_entry_points
    assert plugins.load_codec_entry_points
    assert plugins.list_entry_points
    assert plugins.find_plugin_duplicates
    assert plugins.load_entry_points


def test_import_loom_root_does_not_export_plugins() -> None:
    script = dedent(
        """
        import sys

        import loom

        if "loom.plugins" in sys.modules:
            raise SystemExit("loom.plugins was imported eagerly")
        if "plugins" in loom.__all__:
            raise SystemExit("loom.plugins is exported from the root package")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
