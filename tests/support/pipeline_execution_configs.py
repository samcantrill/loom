"""Shared local execution test configs."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loom.serialization import PlainData


def local_execution_config(
    *, counter_path: Path | None = None, value: int = 1
) -> dict[str, PlainData]:
    stage_config: dict[str, object] = {"value": value}
    if counter_path is not None:
        stage_config["counter_path"] = str(counter_path)
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "demo",
                "stages": [
                    {
                        "name": "build",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                        },
                        "config": stage_config,
                        "outputs": {
                            "data": {"artifact_type": "json", "codec_key": "json.v1"}
                        },
                    },
                    {
                        "name": "report",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                        },
                        "inputs": {"data": "build.data"},
                        "outputs": {
                            "text": {"artifact_type": "text", "codec_key": "text.v1"}
                        },
                    },
                ],
            }
        },
    )
