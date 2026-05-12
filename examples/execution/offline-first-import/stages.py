"""Stages for the offline-first import workflow example."""

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


class SummarizeNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        payload = context.load_input("numbers", expected_type="json")
        if not isinstance(payload, dict):
            raise ValueError("numbers artifact must decode to a mapping")
        values = _number_sequence(payload.get("values", []))
        total = sum(values)
        summary = {
            "count": len(values),
            "total": total,
            "mean": total / len(values) if values else None,
        }
        return {
            "summary": context.save_artifact(
                "summary",
                summary,
                artifact_type="json",
                codec_key="json.v1",
            ),
            "note": context.save_artifact(
                "note",
                f"Imported total={summary['total']}",
                artifact_type="text",
                codec_key="text.v1",
            ),
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
