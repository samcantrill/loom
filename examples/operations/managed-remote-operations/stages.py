"""Bounded simulated work that outlives the foreground agent restart."""

from collections.abc import Mapping
import os
import time

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext


class WorkStage:
    def __init__(self, duration_seconds: float = 20) -> None:
        self.duration_seconds = duration_seconds

    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        time.sleep(self.duration_seconds)
        return {
            "report": context.save_artifact(
                "report",
                {"value": 42, "worker_pid": os.getpid()},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
