"""Unit tests for StageContext."""

from pathlib import Path

import pytest

from loom.pipeline.context import StageContext
from loom.pipeline.errors import PipelineValidationError


def test_context_normalizes_paths_and_mappings() -> None:
    context = StageContext(
        run_id="run-1",
        stage_name="build",
        run_dir="tmp/run",
        stage_dir=Path("tmp/run/build"),
        resolved_config={"pipeline": {"name": "x"}},
        stage_config={"v": 1},
        provenance={"git": {"sha": "123"}},
        metadata={"note": "ok"},
    )
    assert context.run_dir == Path("tmp/run")
    assert context.stage_dir == Path("tmp/run/build")
    assert context.resolved_config["pipeline"]["name"] == "x"


def test_context_rejects_non_plain_data_config() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="run-1",
            stage_name="build",
            run_dir="tmp/run",
            stage_dir="tmp/run/build",
            resolved_config={0: "bad-key"},
            stage_config={},
        )


def test_context_requires_identity_strings() -> None:
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="",
            stage_name="build",
            run_dir="tmp/run",
            stage_dir="tmp/run/build",
            resolved_config={},
            stage_config={},
        )
    with pytest.raises(PipelineValidationError):
        StageContext(
            run_id="run-1",
            stage_name="",
            run_dir="tmp/run",
            stage_dir="tmp/run/build",
            resolved_config={},
            stage_config={},
        )
