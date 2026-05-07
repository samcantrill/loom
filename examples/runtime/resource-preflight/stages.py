"""Stage target for the resource preflight example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class NoopStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        return {
            "data": context.save_artifact(
                "data",
                {"ok": True},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
