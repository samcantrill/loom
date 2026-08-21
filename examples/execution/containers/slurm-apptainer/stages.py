"""Stages for the fake Apptainer executor example."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class AnalyzeStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        values = context.stage_config.get("values")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError("values must be a number sequence")
        numbers = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if len(numbers) != len(values):
            raise ValueError("values must contain only numbers")
        return {
            "summary": context.save_artifact(
                "summary",
                {"count": len(numbers), "total": sum(numbers), "container_mode": os.environ.get("LOOM_CONTAINER_EXAMPLE")},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
