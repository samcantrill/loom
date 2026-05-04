"""Trusted dummy stages for local execution tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class JsonProducerStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        value = context.stage_config.get("value", 1)
        counter_path = context.stage_config.get("counter_path")
        if isinstance(counter_path, str):
            path = Path(counter_path)
            current = int(path.read_text(encoding="utf-8")) if path.exists() else 0
            path.write_text(str(current + 1), encoding="utf-8")
        return {
            "data": context.save_artifact(
                "data",
                {"value": value},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class TextConsumerStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        assert context.artifact_store is not None
        data = context.artifact_store.load(inputs["data"], expected_type="json")
        return {
            "text": context.save_artifact(
                "text",
                f"seen {data}",
                artifact_type="text",
                codec_key="text.v1",
            )
        }


class FailingStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        raise RuntimeError("stage failed intentionally")


class BadOutputStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        return {}


class NotAStage:
    pass
