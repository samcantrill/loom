"""Contract tests for future plugin group readiness."""

from __future__ import annotations

import pytest

import loom.plugins.entrypoints as entrypoints
from loom.plugins import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
    LOOM_RUN_EXPORTERS_GROUP,
    LOOM_SOURCES_GROUP,
    LOOM_SWEEP_PROVIDERS_GROUP,
    LOADABLE_PLUGIN_GROUPS,
    PLUGIN_GROUP_READINESS,
    plugin_group_readiness,
)


pytestmark = pytest.mark.contract


def test_future_group_readiness_contract_is_listing_only_except_event_sinks() -> None:
    future_groups = (
        LOOM_SOURCES_GROUP,
        LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        LOOM_RUN_EXPORTERS_GROUP,
        LOOM_SWEEP_PROVIDERS_GROUP,
    )

    assert LOADABLE_PLUGIN_GROUPS == (
        LOOM_RECIPES_GROUP,
        LOOM_CODECS_GROUP,
        LOOM_EVENT_SINKS_GROUP,
        LOOM_EXECUTORS_GROUP,
        LOOM_RESOURCE_VALIDATORS_GROUP,
    )
    assert PLUGIN_GROUP_READINESS == {
        LOOM_RECIPES_GROUP: "registry-ready",
        LOOM_CODECS_GROUP: "registry-ready",
        LOOM_EVENT_SINKS_GROUP: "registry-ready",
        LOOM_EXECUTORS_GROUP: "registry-ready",
        LOOM_RESOURCE_VALIDATORS_GROUP: "registry-ready",
        **{group: "listing-only" for group in future_groups},
    }
    assert plugin_group_readiness(LOOM_EVENT_SINKS_GROUP).status == "registry-ready"
    for group in future_groups:
        assert plugin_group_readiness(group).status == "listing-only"


def test_future_groups_do_not_export_stage_14_loaders() -> None:
    for name in (
        "load_source_entry_points",
        "load_executor_entry_points",
        "load_artifact_store_backend_entry_points",
        "load_run_exporter_entry_points",
        "load_sweep_provider_entry_points",
        "load_event_sink_entry_points",
    ):
        assert not hasattr(entrypoints, name)
