"""Stages for the run catalog and bundle portability example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class ProduceVariantStage:
    """Persist one small, meaningful payload for a configured variant."""

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        variant = context.stage_config.get("variant")
        if not isinstance(variant, str) or not variant:
            raise ValueError("variant must be a non-empty string")
        return {
            "payload": context.save_artifact(
                "payload",
                f"variant={variant}\n",
                artifact_type="text",
                codec_key="text.v1",
            )
        }
