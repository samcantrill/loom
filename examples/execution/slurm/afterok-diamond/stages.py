"""Small domain-neutral stage for the SLURM afterok diamond example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class JsonStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        return {
            "data": context.save_artifact(
                "data",
                {"input_count": len(inputs)},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
