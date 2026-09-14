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
    QueueSelectionCandidate,
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
    QueueSelectionPolicy,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor


def test_managed_local_queue_runtime_api_is_removed() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.queue.managed_local")


def test_pipeline_execution_does_not_import_queue_managed_ownership() -> None:
    import importlib

    execution = importlib.import_module("loom.pipeline.execution")

    assert not hasattr(execution, "ManagedAssignment")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.pipeline.execution.managed_local")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.pipeline.execution._managed_local_worker")


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
        "AgentResourceProvider",
        "AgentPage",
        "AgentProjection",
        "ClaimCommand",
        "ClaimOutcome",
        "ClaimResult",
        "CpuResourceProvider",
        "LocalDaemon",
        "LocalDaemonAdmissionRequest",
        "LocalDaemonOperation",
        "LocalDaemonSocketClient",
        "LocalOwnerOperatorPolicy",
        "MemoryResourceProvider",
        "ObserveRequest",
        "ObserveResult",
        "OperationWaitKind",
        "OperationWaitResult",
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
    assert not hasattr(queue, "QueueService")
