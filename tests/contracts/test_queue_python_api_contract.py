"""Contract coverage for the public queue Python API."""

from __future__ import annotations

import loom.queue as queue
import pytest

from pathlib import Path
import sys

from loom.queue import (
    LocalDaemonAdmissionRequest,
    LocalDaemonConfig,
    ResidentWorkerLaunchProfile,
    QueueClient,
    QueueController,
    QueueCycleResult,
    QueueDispatchDisposition,
    QueueDispatchNonStartCause,
    QueueDispatchResult,
    QueueEnqueueRequest,
    QueueService,
    QueueServiceState,
    QueueSelectionCandidate,
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
    QueueSelectionPolicy,
    QueuePreStartCleanupStatus,
    SQLiteQueueRepository,
    normalize_queue_spec,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor


def test_queue_python_api_contract(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "pool-1", "mode": "managed"}],
            "queues": [{"queue_name": "default", "pool_name": "pool-1"}],
        }
    )
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    client = QueueClient(service)

    status = client.start_service()
    item = client.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="default",
            run_uri="file:///runs/item-1",
        )
    )
    step = QueueController(service, clock=clock).run_once()

    assert status.to_dict() == {
        "state": QueueServiceState.RUNNING.value,
        "pool_names": ["pool-1"],
        "queue_names": ["default"],
        "recovery_records": [],
    }
    assert item.queue_item_id == "item-1"
    assert step.to_dict()["outcome"] == "dispatched"


def test_managed_local_queue_runtime_api_is_removed() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.queue.managed_local")


def test_local_daemon_public_request_has_no_executable_or_privileged_fields(
    tmp_path: Path,
) -> None:
    request = LocalDaemonAdmissionRequest(
        queue_item_id="queue-1", run_uri="file:///runs/one"
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=ResidentWorkerLaunchProfile(
            project_root=Path.cwd(),
            python_executable=Path(sys.executable),
            descriptor=ResidentProfileDescriptor(
                "test-local", "v1", "test-project", "test-environment", "test-executor"
            ).to_dict(),
        ),
    )

    assert request.to_dict() == {
        "queue_item_id": "queue-1",
        "run_uri": "file:///runs/one",
    }
    assert config.machine_id == "machine-A"
    assert {
        "LocalDaemon",
        "LocalDaemonAdmissionRequest",
        "LocalDaemonSocketClient",
        "ResidentWorkerLaunchProfile",
    }.issubset(queue.__all__)


def test_queue_selection_public_api_is_import_light_and_in_process_only() -> None:
    candidate = QueueSelectionCandidate(
        queue_item_id="item-1",
        enqueued_at="2020-01-01T00:00:00Z",
        dispatch_attempt=1,
        resources={},
    )
    context = QueueSelectionContext("pool-1", (candidate,), {})
    decision = QueueSelectionDecision(
        QueueSelectionDisposition.SELECTED, "test.selected", "item-1"
    )

    assert QueueSelectionPolicy
    assert context.candidates == (candidate,)
    assert decision.disposition is QueueSelectionDisposition.SELECTED
    assert "QueueClaimResult" not in queue.__all__
    assert not hasattr(QueueService, "claim_next")


def test_queue_dispatch_facts_are_public_and_legacy_deferred_is_not() -> None:
    result = QueueDispatchResult(
        disposition=QueueDispatchDisposition.NOT_STARTED,
        reason_code="test.capacity",
        non_start_cause=QueueDispatchNonStartCause.CAPACITY,
        cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
    )

    assert [value.value for value in QueueDispatchDisposition] == [
        "started",
        "completed",
        "not_started",
        "start_uncertain",
    ]
    assert result.is_safe_capacity_non_start is True
    assert "QueueDispatchNonStartCause" in queue.__all__
    assert "QueuePreStartCleanupStatus" in queue.__all__


def test_queue_cycle_selection_evidence_contract_is_narrow_plain_data() -> None:
    result = QueueCycleResult(
        reconciliation_steps=(),
        dispatch_steps=(),
        active_count=0,
        capacity_blocked=True,
        next_maintenance_at=None,
        selection_stop_reason="queue_selection.policy_error",
    )

    assert result.to_dict() == {
        "reconciliation_steps": [],
        "dispatch_steps": [],
        "active_count": 0,
        "capacity_blocked": True,
        "next_maintenance_at": None,
        "selection_stop_reason": "queue_selection.policy_error",
    }


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
