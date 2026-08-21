from __future__ import annotations

from typing import cast

import pytest

from loom.plugins.activation import (
    PluginActivationManifest,
    compare_plugin_activation_records,
    parse_plugin_selector,
    resolve_plugin_selections,
)
from loom.plugins.entrypoints import (
    LOOM_CODECS_GROUP,
    PluginInvalidEntryPointError,
    PluginRecord,
)
from loom.pipeline.execution.models import RunRequest
from loom.pipeline.execution.errors import RunRequestError


def _record(
    name: str = "example", value: str = "project.plugins:codec"
) -> PluginRecord:
    return PluginRecord(
        group=LOOM_CODECS_GROUP,
        name=name,
        value=value,
        package="project",
        package_version="1",
    )


def test_activation_manifest_round_trips_strict_sorted_identity() -> None:
    manifest = PluginActivationManifest(plugins=(_record("z"), _record("a")))

    summaries = cast(list[dict[str, object]], manifest.to_dict()["plugins"])
    assert [item["name"] for item in summaries] == ["a", "z"]
    assert PluginActivationManifest.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"schema_version": 1, "plugins": [], "extra": True},
        {"schema_version": True, "plugins": []},
        {"schema_version": 2, "plugins": []},
        {"schema_version": 1, "plugins": ()},
        {
            "schema_version": 1,
            "plugins": [
                {
                    "group": LOOM_CODECS_GROUP,
                    "name": "example",
                    "value": "project.plugins:codec",
                    "extra": True,
                }
            ],
        },
    ],
)
def test_activation_manifest_rejects_non_schema_v1_exact_shape(data: object) -> None:
    with pytest.raises(PluginInvalidEntryPointError):
        PluginActivationManifest.from_dict(data)


def test_activation_manifest_rejects_duplicate_group_name() -> None:
    with pytest.raises(PluginInvalidEntryPointError, match="unique group/name"):
        PluginActivationManifest(plugins=(_record(), _record(value="other:codec")))


def test_selection_is_exact_applicable_and_does_not_accept_duplicates() -> None:
    record = _record()
    assert resolve_plugin_selections(
        ("loom.codecs:example",), (record,), allowed_groups=(LOOM_CODECS_GROUP,)
    ) == (record,)
    with pytest.raises(PluginInvalidEntryPointError):
        parse_plugin_selector("loom.codecs:example:extra")
    with pytest.raises(PluginInvalidEntryPointError):
        resolve_plugin_selections(
            ("loom.executors:example",), (record,), allowed_groups=(LOOM_CODECS_GROUP,)
        )


def test_reconstruction_comparison_never_invents_distribution_identity() -> None:
    recorded = PluginRecord(
        group=LOOM_CODECS_GROUP, name="example", value="project.plugins:codec"
    )
    assert compare_plugin_activation_records((recorded,), (_record(),)) == (
        "plugin distribution evidence unavailable for loom.codecs:example",
    )


def test_caller_metadata_cannot_claim_plugin_activation_authority() -> None:
    with pytest.raises(RunRequestError, match="reserved plugin_activations"):
        RunRequest(
            config={},
            metadata={"plugin_activations": {"schema_version": 1, "plugins": []}},
        )
    assert compare_plugin_activation_records(
        (_record(),), (_record(value="project.plugins:other"),)
    ) == ("plugin target changed for loom.codecs:example",)
