"""Small project-owned CPU work for the authenticated remote journey."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class RemoteCpuStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "report": context.save_artifact(
                "report",
                "remote CPU artifact",
                artifact_type="text",
                codec_key="text.v1",
            )
        }
