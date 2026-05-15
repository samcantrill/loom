"""Plugin discovery API."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .entrypoints import (
    KNOWN_PLUGIN_GROUPS,
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    PluginLoadError,
    LoadedPlugin,
    PluginDuplicate,
    PluginFailure,
    PluginLoadResult,
    PluginRecord,
    find_plugin_duplicates,
    list_entry_points,
    load_entry_points,
)
from .diagnostics import (
    LISTING_ONLY_PLUGIN_GROUPS,
    LOADABLE_PLUGIN_GROUPS,
    PLUGIN_GROUP_READINESS,
    PluginDiagnosticResult,
    PluginMissingRequest,
    PluginSelection,
    check_plugin_records,
    filter_plugin_records,
    summarize_plugin_records,
)
from .errors import (
    PluginDiscoveryError,
    PluginDuplicateError,
    PluginError,
    PluginInvalidEntryPointError,
    PluginRegistrationError,
)

if TYPE_CHECKING:
    from .codecs import load_codec_entry_points as load_codec_entry_points
    from .recipes import load_recipe_entry_points as load_recipe_entry_points

_LAZY_EXPORTS = {
    "load_codec_entry_points": ".codecs",
    "load_recipe_entry_points": ".recipes",
}


def __getattr__(name: str) -> object:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "KNOWN_PLUGIN_GROUPS",
    "LOOM_ARTIFACT_STORE_BACKENDS_GROUP",
    "LOOM_CODECS_GROUP",
    "LOOM_EVENT_SINKS_GROUP",
    "LOOM_EXECUTORS_GROUP",
    "LOOM_RECIPES_GROUP",
    "LOOM_RUN_EXPORTERS_GROUP",
    "LOOM_SOURCES_GROUP",
    "LOOM_SWEEP_PROVIDERS_GROUP",
    "LISTING_ONLY_PLUGIN_GROUPS",
    "LOADABLE_PLUGIN_GROUPS",
    "PLUGIN_GROUP_READINESS",
    "LoadedPlugin",
    "PluginDiagnosticResult",
    "PluginDiscoveryError",
    "PluginDuplicate",
    "PluginDuplicateError",
    "PluginError",
    "PluginFailure",
    "PluginInvalidEntryPointError",
    "PluginLoadError",
    "PluginLoadResult",
    "PluginMissingRequest",
    "PluginRecord",
    "PluginRegistrationError",
    "PluginSelection",
    "check_plugin_records",
    "find_plugin_duplicates",
    "filter_plugin_records",
    "list_entry_points",
    "load_codec_entry_points",
    "load_recipe_entry_points",
    "load_entry_points",
    "summarize_plugin_records",
]
