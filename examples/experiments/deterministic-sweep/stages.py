"""Stages for the deterministic manual sweep example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class MeasureTrialStage:
    """Write one small deterministic measurement for a configured trial."""

    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        value = context.stage_config.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("trial value must be a number")
        return {
            "measurement": context.save_artifact(
                "measurement",
                {"value": value, "double": value * 2},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
