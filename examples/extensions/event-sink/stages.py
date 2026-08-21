"""Stages for the observe-only event sink example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class PublishStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        return {
            "report": context.save_artifact(
                "report", "event sink example\n", artifact_type="text", codec_key="text.v1"
            )
        }
