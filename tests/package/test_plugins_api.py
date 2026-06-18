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
    assert plugins.PluginSelection
    assert plugins.PluginDiagnosticResult
    assert plugins.PluginGroupReadiness
    assert plugins.PluginMissingRequest
    assert plugins.PluginDiscoveryError
    assert plugins.PluginInvalidEntryPointError
    assert plugins.PluginDuplicateError
    assert plugins.PluginRegistrationError
    assert plugins.PluginLoadError
    assert plugins.load_recipe_entry_points
    assert plugins.load_codec_entry_points
    assert plugins.list_entry_points
    assert plugins.find_plugin_duplicates
    assert plugins.filter_plugin_records
    assert plugins.summarize_plugin_records
    assert plugins.check_plugin_records
    assert plugins.plugin_group_readiness
    assert plugins.LOADABLE_PLUGIN_GROUPS == (
        plugins.LOOM_RECIPES_GROUP,
        plugins.LOOM_CODECS_GROUP,
        plugins.LOOM_EVENT_SINKS_GROUP,
    )
    assert (
        plugins.LOOM_ARTIFACT_STORE_BACKENDS_GROUP in plugins.LISTING_ONLY_PLUGIN_GROUPS
    )
    assert plugins.load_artifact_store_backend_entry_points
    assert plugins.load_event_sink_entry_points
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


def test_import_loom_plugins_is_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.plugins

        for forbidden in ("weave", "loom.io", "loom.cli", "omegaconf", "yaml"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.plugins")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_cli_help_does_not_discover_plugin_entry_points() -> None:
    script = dedent(
        """
        import importlib.metadata

        def fail_entry_points(*args, **kwargs):
            raise SystemExit("entry point discovery was called for help")

        importlib.metadata.entry_points = fail_entry_points

        from loom.cli.main import main

        raise SystemExit(main(["plugins", "--help"]))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "list" in result.stdout
    assert "check" in result.stdout
