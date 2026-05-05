"""Integration coverage for recipe-to-instantiate target handoff."""

from pathlib import Path
from typing import Any, cast

import pytest

from loom.config import RecipeCatalog, compose_config, instantiate
from tests.support.config_samples import (
    ConstructionProbeTarget,
    construction_event_log,
    reset_instantiate_probe_state,
)

pytestmark = pytest.mark.optional_dependency


def nested_target_recipe(value: str) -> dict[str, Any]:
    return {
        "service": {
            "_target_": "tests.support.config_samples:ConstructionProbeTarget",
            "left": {
                "_target_": "tests.support.config_samples:log_and_return",
                "tag": "left",
                "value": f"{value}-left",
            },
            "right": {
                "_target_": "tests.support.config_samples:log_and_return",
                "tag": "right",
                "value": f"{value}-right",
            },
            "items": [
                {
                    "_target_": "tests.support.config_samples:log_and_return",
                    "tag": "item",
                    "value": f"{value}-item",
                }
            ],
        }
    }


def test_recipe_output_nested_targets_compose_inert_then_instantiate(tmp_path: Path) -> None:
    reset_instantiate_probe_state()
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("target-handoff", nested_target_recipe)

    base.write_text(
        "pipeline:\n"
        "  _recipe_: target-handoff\n"
        "  value: recipe\n",
        encoding="utf-8",
    )

    composed = compose_config(base, recipe_catalog=catalog)

    assert construction_event_log == []
    pipeline = cast(dict[str, Any], composed.resolved["pipeline"])
    service_config = cast(dict[str, Any], pipeline["service"])
    assert service_config == {
        "_target_": "tests.support.config_samples:ConstructionProbeTarget",
        "left": {
            "_target_": "tests.support.config_samples:log_and_return",
            "tag": "left",
            "value": "recipe-left",
        },
        "right": {
            "_target_": "tests.support.config_samples:log_and_return",
            "tag": "right",
            "value": "recipe-right",
        },
        "items": [
            {
                "_target_": "tests.support.config_samples:log_and_return",
                "tag": "item",
                "value": "recipe-item",
            }
        ],
    }

    instantiated = cast(dict[str, Any], instantiate(pipeline))

    service = instantiated["service"]
    assert isinstance(service, ConstructionProbeTarget)
    assert service.kwargs == {
        "left": "recipe-left",
        "right": "recipe-right",
        "items": ["recipe-item"],
    }
    assert construction_event_log == ["left", "right", "item", "parent"]
