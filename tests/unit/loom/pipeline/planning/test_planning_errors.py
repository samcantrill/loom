"""Unit tests for planning errors."""

import pytest
from collections.abc import Mapping

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import PlanPersistenceError, ResumeOptions, plan_pipeline
from loom.pipeline.stores import RunStoreError
from loom.serialization import PlainData


class _FailingPlanStore:
    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None:
        raise RunStoreError("cannot write")

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None:
        return None


def test_plan_persistence_errors_wrap_store_failures() -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        },
    )
    with pytest.raises(PlanPersistenceError, match="could not persist"):
        plan_pipeline(
            spec,
            run_uri="run1",
            plans=_FailingPlanStore(),
            resume=ResumeOptions(enabled=False),
            persist=True,
        )
