"""Unit tests for prepared-run continuation validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import (
    InsufficientPreparedStateError,
    PREPARED_RUN_CONTINUATION_WHOLE_RUN,
    PREPARED_RUN_SCHEMA_VERSION,
    PreparedRunContinueRequest,
    PreparedRunRecord,
    UnsupportedContinuationExecutorError,
    continue_prepared_run,
)
from loom.pipeline.execution.lifecycle import write_run_status
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import RunOptions, build_runtime_metadata
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _stage() -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(
            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
        ),
        outputs={"data": OutputSpec(artifact_type="json")},
    )


def _prepared_run(tmp_path: Path) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    spec = PipelineSpec(stages=(_stage(),))
    plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        build_runtime_metadata(
            RunOptions(run_uri=run_uri, executor="local"),
            stage_ids=spec.stage_names,
        ).to_dict(),
    )
    store.write_prepared_run(
        run_uri,
        PreparedRunRecord(
            schema_version=PREPARED_RUN_SCHEMA_VERSION,
            run_uri=run_uri,
            prepared_at="2020-01-01T00:00:02Z",
            executor_name="slurm-single-job",
            continuation_type=PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            plan={"plan_summary": {"stage_count": 1}},
            runtime={"stage_count": 1, "executor": "slurm-single-job"},
        ).to_dict(),
    )
    return store, run_uri


def test_prepared_run_continue_fails_with_structured_insufficient_state(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)

    with pytest.raises(InsufficientPreparedStateError) as exc_info:
        continue_prepared_run(
            run_store=store,
            request=PreparedRunContinueRequest(run_uri=run_uri, executor="local"),
        )

    assert exc_info.value.code == "execution.prepared_run.insufficient_prepared_state"
    assert exc_info.value.context == {"run_uri": run_uri}


def test_prepared_run_continue_rejects_recursive_executor_before_store_access(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")

    with pytest.raises(UnsupportedContinuationExecutorError):
        continue_prepared_run(
            run_store=store,
            request=PreparedRunContinueRequest(
                run_uri="file:///tmp/does-not-exist",
                executor="slurm-single-job",
            ),
        )
