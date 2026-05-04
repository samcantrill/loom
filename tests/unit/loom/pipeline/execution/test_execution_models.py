"""Unit tests for execution models."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    ConfigSnapshotInputs,
    ExecutionFailure,
    FailurePolicy,
    RunRequest,
    RunRequestError,
)


def test_run_request_requires_config_or_pipeline() -> None:
    with pytest.raises(RunRequestError):
        RunRequest()


def test_run_request_rejects_continue_on_failure() -> None:
    with pytest.raises(RunRequestError, match="continue-on-failure"):
        RunRequest(
            pipeline=PipelineSpec.from_config(
                {
                    "stages": [
                        {
                            "name": "build",
                            "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage",
                            "outputs": {"data": {"artifact_type": "json"}},
                        }
                    ]
                }
            ),
            failure_policy=FailurePolicy(stop_on_first_failure=False),
        )


def test_execution_failure_round_trips_plain_data() -> None:
    failure = ExecutionFailure(
        schema_version=1,
        run_id="run1",
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="stage_exception",
        message="boom",
        details={"path": "x"},
    )

    assert ExecutionFailure.from_dict(failure.to_dict()) == failure


def test_config_snapshot_inputs_validate_strings() -> None:
    with pytest.raises(RunRequestError):
        ConfigSnapshotInputs(raw=object())  # type: ignore[arg-type]
