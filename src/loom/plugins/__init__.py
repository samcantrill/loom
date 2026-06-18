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
    PLUGIN_GROUP_READINESS_DETAILS,
    PluginDiagnosticResult,
    PluginGroupReadiness,
    PluginMissingRequest,
    PluginSelection,
    check_plugin_records,
    filter_plugin_records,
    plugin_group_readiness,
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
    from .artifact_backends import (
        load_artifact_store_backend_entry_points as load_artifact_store_backend_entry_points,
    )
    from .codecs import load_codec_entry_points as load_codec_entry_points
    from .event_sinks import load_event_sink_entry_points as load_event_sink_entry_points
    from .recipes import load_recipe_entry_points as load_recipe_entry_points

_LAZY_EXPORTS = {
    "load_artifact_store_backend_entry_points": ".artifact_backends",
    "load_codec_entry_points": ".codecs",
    "load_event_sink_entry_points": ".event_sinks",
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
    "PLUGIN_GROUP_READINESS_DETAILS",
    "LoadedPlugin",
    "PluginDiagnosticResult",
    "PluginDiscoveryError",
    "PluginDuplicate",
    "PluginDuplicateError",
    "PluginError",
    "PluginFailure",
    "PluginGroupReadiness",
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
    "load_artifact_store_backend_entry_points",
    "list_entry_points",
    "load_codec_entry_points",
    "load_event_sink_entry_points",
    "load_recipe_entry_points",
    "load_entry_points",
    "plugin_group_readiness",
    "summarize_plugin_records",
]
