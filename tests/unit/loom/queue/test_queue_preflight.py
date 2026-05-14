"""Unit coverage for queue preflight diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.queue.preflight import QueuePreflightStatus, run_queue_preflight
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


pytestmark = pytest.mark.unit


def test_queue_preflight_reports_delegated_slurm_and_workspace_warnings(
    tmp_path: Path,
) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: slurm-pool
              mode: delegated
          queues:
            - queue_name: slurm
              pool_name: slurm-pool
        """,
        encoding="utf-8",
    )

    result = run_queue_preflight(
        config_path,
        slurm_command_checker=lambda command: command != "sacct",
    )

    assert result.status is QueuePreflightStatus.WARN
    checks = {check.check_id: check for check in result.checks}
    assert checks["queue.config.load"].status is QueuePreflightStatus.PASS
    assert checks["queue.service.repository"].status is QueuePreflightStatus.PASS
    assert checks["queue.slurm.commands"].status is QueuePreflightStatus.WARN
    assert checks["queue.slurm.commands"].details["missing"] == ["sacct"]
    assert (
        checks["queue.delegated_workspace_assumptions"].status
        is QueuePreflightStatus.WARN
    )


def test_queue_preflight_reconciles_managed_pool_limits_when_store_is_supplied(
    tmp_path: Path,
) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: gpu-pool
              mode: managed
              resources:
                gpu: 2
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)

    result = run_queue_preflight(
        config_path,
        coordination_store=store,
        workspace_id="workspace-1",
    )

    assert result.status is QueuePreflightStatus.PASS
    checks = {check.check_id: check for check in result.checks}
    assert checks["queue.managed_pool_limits"].status is QueuePreflightStatus.PASS
    assert checks["queue.managed_pool_limits"].details["ok"] is True
