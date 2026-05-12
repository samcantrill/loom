"""Stages for the offline import rejection example."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class SeedNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        values = _number_sequence(context.stage_config.get("values", [1, 2, 3]))
        return {
            "numbers": context.save_artifact(
                "numbers",
                {"values": values},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


def _number_sequence(value: object) -> list[int | float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("values must be a sequence of numbers")
    numbers: list[int | float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("values must contain only numbers")
        numbers.append(item)
    return numbers
