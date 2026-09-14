"""Unit tests for pipeline validation facades."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import validate_pipeline_config
from loom.pipeline.context import StageContext
from loom.pipeline.errors import InputBindingError


pytestmark = pytest.mark.unit

stage_events: list[int] = []
STAGE_TARGET = f"{__name__}:SafeValidationStage"


class SafeValidationStage:
    def __init__(self, *, value: int = 0) -> None:
        stage_events.append(value)

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        return {}


def _valid_config() -> dict[str, object]:
    return {
        "pipeline": {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": STAGE_TARGET,
                        "init": {"value": 7},
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ],
        }
    }


def test_validate_pipeline_config_parses_spec_and_graph() -> None:
    stage_events.clear()
    result = validate_pipeline_config(_valid_config())

    assert result.pipeline_name == "demo"
    assert result.stage_count == 1
    assert tuple(result.graph.nodes) == ("build",)
    assert result.stage_factory_target_paths == ("$.pipeline.stages[0].factory",)
    assert stage_events == []


def test_validate_pipeline_config_rejects_unknown_input_stage() -> None:
    config = _valid_config()
    pipeline = config["pipeline"]
    assert isinstance(pipeline, dict)
    stage = pipeline["stages"][0]
    assert isinstance(stage, dict)
    stage["inputs"] = {"missing": "upstream.data"}

    with pytest.raises(InputBindingError, match="unknown stage"):
        validate_pipeline_config(config)
