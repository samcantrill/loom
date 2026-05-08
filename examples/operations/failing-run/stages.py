"""Stages for the failing diagnostics example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class FailingStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        raise RuntimeError("intentional diagnostics example failure")


class NeverRunsStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        return {
            "text": context.save_artifact(
                "text",
                "This stage should be blocked by the failing upstream stage.",
                artifact_type="text",
                codec_key="text.v1",
            )
        }
