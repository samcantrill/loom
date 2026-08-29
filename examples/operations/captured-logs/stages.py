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
        workspace_note = context.local_workspace_path("notes", "project.log")
        workspace_note.write_text("project-owned workspace file\n", encoding="utf-8")
        report_path = context.local_output_path("report", suffix=".txt")
        report_path.write_text("registered report\n", encoding="utf-8")
        return {
            "data": context.save_artifact(
                "data",
                {"logged": True},
                artifact_type="json",
                codec_key="json.v1",
            ),
            "report": context.register_local_artifact(
                "report",
                report_path,
                artifact_type="text",
                codec_key="text.v1",
            ),
        }
