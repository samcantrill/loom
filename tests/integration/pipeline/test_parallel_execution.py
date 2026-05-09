"""Integration tests for bounded local parallel stage execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline import OutputSpec, PipelineRunner, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import FailurePolicy, RunRequest
from loom.pipeline.execution.authority_adapter import (
    create_authority_backed_serial_run_store,
)
from loom.pipeline.runtime import RunOptions
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LeaseRecord, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


pytestmark = pytest.mark.integration


class _CountingRenewalAuthority(SQLitePerRunAuthorityStore):
    def __init__(self) -> None:
        super().__init__(clock=lambda: "2020-01-01T00:00:00Z")
        self.renewal_count = 0

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        self.renewal_count += 1
        return super().renew_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )


def test_bounded_parallel_runs_independent_stages_concurrently(
    tmp_path: Path,
) -> None:
    marker_dir = tmp_path / "markers"
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "parallel")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _coordinated_stage("left", marker_dir=marker_dir),
                    _coordinated_stage("right", marker_dir=marker_dir),
                )
            ),
            run_uri=run_uri,
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 2}},
            ),
        )
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.stage_results["left"].status is StageStatus.SUCCEEDED
    assert result.stage_results["right"].status is StageStatus.SUCCEEDED
    assert set(run_store.read_artifact_index(run_uri)) == {"left.data", "right.data"}
    snapshot = authority.snapshot(run_uri)
    assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
        "left": StageStatus.SUCCEEDED,
        "right": StageStatus.SUCCEEDED,
    }
    assert all(stage.latest_commit is not None for stage in snapshot.stages)
    assert all(stage.active_lease is None for stage in snapshot.stages)


def test_parallel_stages_renew_active_stage_leases(tmp_path: Path) -> None:
    authority = _CountingRenewalAuthority()
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    runner = PipelineRunner(run_store=run_store)
    runner._stage_lease_renewal_interval_seconds = 0.01

    result = runner.run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    StageSpec(
                        name="slow",
                        factory=StageFactorySpec(
                            target_path="tests.support.pipeline_execution_stages.SleepStage"
                        ),
                        stage_config={"seconds": 0.05},
                        outputs={
                            "data": OutputSpec(
                                artifact_type="json",
                                codec_key="json.v1",
                            )
                        },
                    ),
                )
            ),
            run_uri=path_to_run_uri(tmp_path / "runs" / "lease-renewal"),
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 2}},
            ),
        )
    )

    assert result.status is RunStatus.SUCCEEDED
    assert authority.renewal_count > 0


def test_explicit_single_parallelism_keeps_serial_local_path(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "serial-explicit-one")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    StageSpec(
                        name="build",
                        factory=StageFactorySpec(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                        outputs={
                            "data": OutputSpec(
                                artifact_type="json",
                                codec_key="json.v1",
                            )
                        },
                    ),
                )
            ),
            run_uri=run_uri,
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 1}},
            ),
        )
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.stage_results["build"].status is StageStatus.SUCCEEDED


def test_parallel_stage_interruption_records_durable_failure(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "stage-interrupted")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    StageSpec(
                        name="interrupt",
                        factory=StageFactorySpec(
                            target_path="tests.support.pipeline_execution_stages.KeyboardInterruptStage"
                        ),
                        outputs={
                            "data": OutputSpec(
                                artifact_type="json",
                                codec_key="json.v1",
                            )
                        },
                    ),
                )
            ),
            run_uri=run_uri,
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 2}},
            ),
        )
    )

    assert result.status is RunStatus.FAILED
    assert result.stage_results["interrupt"].status is StageStatus.FAILED
    assert result.stage_results["interrupt"].failure is not None
    assert result.stage_results["interrupt"].failure.exception_type == (
        "builtins.KeyboardInterrupt"
    )
    snapshot = authority.snapshot(run_uri)
    assert snapshot.stages[0].active_lease is None
    assert snapshot.stages[0].latest_commit is None


def test_default_parallel_failure_policy_stops_new_independent_work(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "default-failure")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=_failure_policy_pipeline(),
            run_uri=run_uri,
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 2}},
            ),
        )
    )

    assert result.status is RunStatus.FAILED
    assert result.stage_results["fail"].status is StageStatus.FAILED
    assert result.stage_results["ok"].status is StageStatus.SUCCEEDED
    assert result.stage_results["after_ok"].status is StageStatus.BLOCKED


def test_continue_independent_failure_policy_runs_unrelated_branch(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "continue-independent")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=_failure_policy_pipeline(),
            run_uri=run_uri,
            options=RunOptions(
                execution={
                    "settings": {
                        "max_parallel_stages": 2,
                        "failure_policy": "continue_independent",
                    }
                },
            ),
        )
    )

    assert result.status is RunStatus.FAILED
    assert result.stage_results["fail"].status is StageStatus.FAILED
    assert result.stage_results["ok"].status is StageStatus.SUCCEEDED
    assert result.stage_results["after_ok"].status is StageStatus.SUCCEEDED


def test_run_request_failure_policy_can_continue_independent_branch(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=_failure_policy_pipeline(),
            run_uri=path_to_run_uri(tmp_path / "runs" / "request-policy"),
            options=RunOptions(
                execution={"settings": {"max_parallel_stages": 2}},
            ),
            failure_policy=FailurePolicy(stop_on_first_failure=False),
        )
    )

    assert result.stage_results["after_ok"].status is StageStatus.SUCCEEDED


def _coordinated_stage(name: str, *, marker_dir: Path) -> StageSpec:
    return StageSpec(
        name=name,
        factory=StageFactorySpec(
            target_path="tests.support.pipeline_execution_stages.CoordinatedStage"
        ),
        stage_config={"marker_dir": str(marker_dir), "wait_for": 2},
        outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
    )


def _failure_policy_pipeline() -> PipelineSpec:
    return PipelineSpec(
        stages=(
            StageSpec(
                name="fail",
                factory=StageFactorySpec(
                    target_path="tests.support.pipeline_execution_stages.FailingStage"
                ),
                outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
            ),
            StageSpec(
                name="ok",
                factory=StageFactorySpec(
                    target_path="tests.support.pipeline_execution_stages.SleepStage"
                ),
                stage_config={"seconds": 0.1},
                outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
            ),
            StageSpec(
                name="after_ok",
                factory=StageFactorySpec(
                    target_path="tests.support.pipeline_execution_stages.TextConsumerStage"
                ),
                inputs={"data": "ok.data"},
                outputs={"text": OutputSpec(artifact_type="text", codec_key="text.v1")},
            ),
        )
    )
