"""Integration coverage for Phase 4 sweep coordination and queue status."""

from __future__ import annotations

from pathlib import Path

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import RunRequest
from loom.pipeline.stores import TrialState
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepAggregateStatus,
    build_sweep_status,
    enqueue_sweep_trials,
    plan_sweep,
)
from loom.provenance.models import ProvenanceCaptureOptions
from loom.queue import (
    QueueItemStatus,
    QueueService,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


def test_queue_dispatch_records_sqlite_coordination_and_status_readback(
    tmp_path: Path,
) -> None:
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="integration",
            run_uri_root="file:///tmp/integration",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    service = _queue_service(tmp_path)
    service.start()
    coordination = SQLiteWorkspaceCoordinationStore(
        tmp_path / "coordination.sqlite3",
        clock=_clock("2026-05-14T00:00:00Z"),
    )

    result = enqueue_sweep_trials(
        plan,
        queue_service=service,
        queue_name="gpu",
        request_template=_template_request(),
        coordination_store=coordination,
        workspace_id="workspace-1",
        workspace_root_uri="file:///workspace",
        requested_at="2026-05-14T00:00:00Z",
    )

    assert result.submitted_count == 2
    assert result.failed_count == 0
    assert [trial.queue_status for trial in result.trial_results] == [
        QueueItemStatus.QUEUED.value,
        QueueItemStatus.QUEUED.value,
    ]
    recorded = coordination.list_trials("integration")
    assert [trial.state for trial in recorded] == [
        TrialState.PENDING,
        TrialState.PENDING,
    ]
    assert recorded[0].metadata["queue_status"] == "QUEUED"
    queue_items = tuple(
        service.read_item(trial.queue_item_id)
        for trial in result.trial_results
        if trial.queue_item_id is not None
    )
    assert all(item is not None for item in queue_items)

    summary = build_sweep_status(
        plan,
        queue_items=queue_items,
        coordination_trials=recorded,
    )

    assert summary.status is SweepAggregateStatus.RUNNING
    assert summary.counts["queued"] == 2


def _queue_service(tmp_path: Path) -> QueueService:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
        }
    )
    return QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=_clock()),
        clock=_clock(),
    )


def _template_request() -> RunRequest:
    return RunRequest(
        pipeline=PipelineSpec(
            stages=(
                StageSpec(
                    name="build",
                    factory=StageFactorySpec(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                    outputs={"data": OutputSpec(artifact_type="json")},
                ),
            )
        ),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def _clock(*values: str):
    remaining = list(values) or ["2026-05-14T00:00:00Z"]

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
