"""Contracts for runtime option serialization and ownership boundaries."""

from __future__ import annotations

from loom.pipeline.execution.models import RunRequest, StageExecutionRequest
from loom.pipeline.planning.models import PlanSelectors, ResumeOptions
from loom.pipeline.runtime import RunOptions
from loom.serialization import stable_json_dumps


def test_run_options_plain_data_serialization_contract() -> None:
    options = RunOptions(
        run_uri="runs/example",
        executor="local",
        tags={"purpose": "contract"},
        notes=["plain data"],
        stage_options={
            "stage_a": {
                "resources": {
                    "entries": {
                        "memory": {
                            "kind": "memory",
                            "amount": 512,
                            "unit": "MiB",
                        }
                    }
                }
            }
        },
    )

    document = options.to_dict()
    assert stable_json_dumps(document)
    assert RunOptions.from_dict(document).to_dict() == document


def test_run_options_adapt_to_planning_owned_models() -> None:
    options = RunOptions(
        selectors={
            "force_stages": ["extract"],
            "from_stage": "extract",
            "only_stages": ["train"],
            "skip_stages": ["publish"],
        },
        resume={"enabled": False},
    )

    assert options.to_plan_selectors() == PlanSelectors(
        force_stages=("extract",),
        from_stage="extract",
        only_stages=("train",),
        skip_stages=("publish",),
    )
    assert options.to_resume_options() == ResumeOptions(enabled=False)


def test_execution_envelope_exposes_runtime_options_without_environment_values() -> None:
    assert "options" in RunRequest.__dataclass_fields__
    assert "resolved_runtime" in StageExecutionRequest.__dataclass_fields__
    assert "runtime_options" not in StageExecutionRequest.__dataclass_fields__
    assert "environment" not in StageExecutionRequest.__dataclass_fields__
