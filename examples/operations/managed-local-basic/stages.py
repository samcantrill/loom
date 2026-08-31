"""Small project-owned stages for the managed-local starter."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class ProduceStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data", {"value": 42}, artifact_type="json", codec_key="json.v1"
            )
        }


class ConsumeStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        value = context.load_input("data", expected_type="json")
        return {
            "report": context.save_artifact(
                "report", f"consumed {value}", artifact_type="text", codec_key="text.v1"
            )
        }
