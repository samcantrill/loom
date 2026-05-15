"""Package-level plugin public API tests."""

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
    assert plugins.list_entry_points
    assert plugins.find_plugin_duplicates
    assert plugins.load_entry_points


def test_import_loom_root_does_not_export_plugins() -> None:
    import loom

    assert not hasattr(loom, "plugins")
