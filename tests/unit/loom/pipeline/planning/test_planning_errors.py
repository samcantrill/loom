"""Unit tests for planning errors."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import PlanPersistenceError, plan_pipeline
from loom.pipeline.stores import RunStoreError


class _FailingRunStore:
    def read_stage_status(self, run_id: str, stage_name: str) -> None:
        return None

    def read_stage_inputs(self, run_id: str, stage_name: str) -> None:
        return None

    def read_stage_fingerprint(self, run_id: str, stage_name: str) -> None:
        return None

    def read_stage_outputs(self, run_id: str, stage_name: str) -> None:
        return None

    def read_artifact_index(self, run_id: str) -> dict[str, object]:
        return {}

    def write_plan(self, run_id: str, plan: object) -> None:
        raise RunStoreError("cannot write")

    def read_plan(self, run_id: str) -> object:
        return None


class _ArtifactStore:
    def validate(self, ref: object, *, expected_type: str | None = None) -> None:
        return None


def test_plan_persistence_errors_wrap_store_failures() -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "_target_": "project.Build",
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        },
    )
    with pytest.raises(PlanPersistenceError, match="could not persist"):
        plan_pipeline(
            spec,
            run_id="run1",
            run_store=_FailingRunStore(),  # type: ignore[arg-type]
            artifact_store=_ArtifactStore(),  # type: ignore[arg-type]
            persist=True,
        )
