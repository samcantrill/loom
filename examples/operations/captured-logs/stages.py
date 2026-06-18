"""Stages for the captured logs diagnostics example."""

from __future__ import annotations

import sys
from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class NoisyStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        print("stdout line one")
        print("stdout line two")
        sys.stderr.write("stderr line one\n")
        return {
            "data": context.save_artifact(
                "data",
                {"logged": True},
                artifact_type="json",
                codec_key="json.v1",
            )
        }
