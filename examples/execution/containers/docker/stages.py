"""Example stage implementations for Docker executor workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import sys

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class SeedNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        values = _number_sequence(context.stage_config.get("values", [2, 4, 8]))
        return {
            "numbers": context.save_artifact(
                "numbers",
                {
                    "values": values,
                    "container_mode": os.environ.get("LOOM_CONTAINER_EXAMPLE"),
                },
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
            "container_mode": payload.get("container_mode"),
        }
        return {
            "summary": context.save_artifact(
                "summary",
                summary,
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class FailingNumbersStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        print("docker example is failing intentionally", file=sys.stderr)
        raise RuntimeError("docker example failed intentionally")


def _number_sequence(value: object) -> list[int | float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("values must be a sequence of numbers")

    numbers: list[int | float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("values must contain only numbers")
        numbers.append(item)
    return numbers
