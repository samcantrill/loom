"""Timeout facts cross the immutable executor-result boundary intact."""

from pathlib import Path

from loom.pipeline.execution.lifecycle import write_run_status, write_stage_running
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionResult,
)
from loom.pipeline.execution.reliability import (
    build_reliability_status_detail,
    classify_execution_failure,
    record_timeout_outcome_from_metadata,
)
from loom.pipeline.executors._reliability import metadata_with_timeout, timeout_metadata
from loom.pipeline.reliability import TimeoutOutcome, TimeoutPolicy, TimeoutSupportLevel
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


def test_frozen_executor_result_preserves_timeout_classification_and_record(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "timeout-fixture")
    store.create_run(run_uri)
    timestamp = "2026-09-07T00:00:00Z"
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at=timestamp,
        updated_at=timestamp,
        started_at=timestamp,
    )
    write_stage_running(
        store, run_uri=run_uri, stage_name="build", attempt=1, started_at=timestamp
    )
    metadata = metadata_with_timeout(
        {},
        timeout_metadata(
            policy=TimeoutPolicy(enabled=True, duration_seconds=1),
            support_level=TimeoutSupportLevel.ENFORCED,
            outcome=TimeoutOutcome.TIMED_OUT,
            timed_out=True,
            message="container execution deadline exceeded; cleanup unresolved",
        ),
    )
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        failed_at=timestamp,
        executor="apptainer",
        failure_type="executor_infrastructure",
        message="deadline exceeded",
        exit_code=124,
        executor_metadata=metadata,
    )
    result = StageExecutionResult(
        stage_name="build",
        status=StageStatus.FAILED,
        outputs={},
        failure=failure,
        started_at=timestamp,
        finished_at=timestamp,
        executor_name="apptainer",
        attempt=1,
        executor_metadata=metadata,
    )
    # These are the public objects passed by lifecycle.py, not mutable dict mocks.
    classification = classify_execution_failure(
        failure,
        status=build_reliability_status_detail(
            store,
            run_uri=run_uri,
            stage_name="build",
            stage_status=StageStatus.FAILED,
            attempt=1,
            created_at=timestamp,
        ),
    )
    assert classification.reason_code == "reliability.timeout.timed_out"
    outcome = record_timeout_outcome_from_metadata(
        store,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        stage_status=StageStatus.FAILED,
        recorded_at=timestamp,
        executor_metadata=result.executor_metadata,
    )
    assert outcome is not None
    assert outcome.outcome is TimeoutOutcome.TIMED_OUT
    assert store.list_timeout_outcomes(run_uri, stage_name="build") == (outcome,)
