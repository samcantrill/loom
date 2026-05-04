"""Example stage implementations for the local pipeline example."""

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
        payload = {"values": values}
        return {
            "numbers": context.save_artifact(
                "numbers",
                payload,
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
        if context.artifact_store is None:
            raise RuntimeError("artifact store is required")

        payload = context.artifact_store.load(inputs["numbers"], expected_type="json")
        if not isinstance(payload, dict):
            raise ValueError("numbers artifact must decode to a mapping")

        values = _number_sequence(payload.get("values", []))
        total = sum(values)
        summary = {
            "count": len(values),
            "total": total,
            "mean": total / len(values) if values else None,
        }
        note = f"Processed {summary['count']} values with total {summary['total']}."
        return {
            "summary": context.save_artifact(
                "summary",
                summary,
                artifact_type="json",
                codec_key="json.v1",
            ),
            "note": context.save_artifact(
                "note",
                note,
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

