"""Small domain-neutral stages for the SLURM live operations example."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class SeedNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        return {
            "numbers": context.save_artifact(
                "numbers",
                {"values": [2, 4, 8]},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class SummarizeNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        payload = context.load_input("numbers", expected_type="json")
        values = payload["values"] if isinstance(payload, dict) else []
        total = sum(value for value in values if isinstance(value, int | float))
        return {
            "summary": context.save_artifact(
                "summary",
                {"count": len(values), "total": total},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
