"""Focused contracts for shared preparation request and capture boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue.preparation import (
    PrepareRunRequest,
    PreparationSource,
    capture_shared_input,
)
from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
import sys


def _request(*, mode: str = "shared") -> PrepareRunRequest:
    return PrepareRunRequest(
        "prepare-demo-001",
        "demo-001",
        PreparationSource(mode, "projects", "example-project", ("configs",)),
        "configs/experiment.yaml",
        "example-cpu",
    )


def test_shared_capture_is_finite_and_immutable(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("pipeline: {}\n", encoding="utf-8")

    request = _request()
    first = capture_shared_input(request, source_root=root, snapshot_root=tmp_path / "snapshots")
    snapshot = tmp_path / "snapshots" / first.path
    assert (snapshot / "configs" / "experiment.yaml").read_text(encoding="utf-8") == "pipeline: {}\n"
    assert first.to_dict()["reference"] == {
        "schema_version": 1,
        "kind": "loom.shared-preparation-input",
        "root": "projects",
        "path": first.path,
    }


def test_staged_is_a_valid_future_vocabulary_but_not_a_shared_capture() -> None:
    with pytest.raises(QueueServiceError, match="unsupported"):
        capture_shared_input(
            _request(mode="staged"), source_root=Path("."), snapshot_root=Path("snapshots")
        )


def test_capture_rejects_symlinked_project_components_and_tampered_reuse(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    actual = tmp_path / "actual"
    (actual / "configs").mkdir(parents=True)
    (actual / "configs" / "experiment.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    root.mkdir()
    (root / "example-project").symlink_to(actual, target_is_directory=True)
    with pytest.raises(QueueServiceError, match="symbolic link"):
        capture_shared_input(_request(), source_root=root, snapshot_root=tmp_path / "snapshots")

    project = root / "example-project"
    (root / "example-project").unlink()
    (project / "configs").mkdir(parents=True)
    (project / "configs" / "experiment.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    receipt = capture_shared_input(_request(), source_root=root, snapshot_root=tmp_path / "snapshots")
    snapshot = tmp_path / "snapshots" / receipt.path
    (snapshot / "configs" / "experiment.yaml").write_text("changed", encoding="utf-8")
    with pytest.raises(QueueServiceError, match="capture"):
        capture_shared_input(_request(), source_root=root, snapshot_root=tmp_path / "snapshots")


@pytest.mark.parametrize("path", ("/absolute", "../escape", "configs/../../escape"))
def test_request_rejects_escape_paths_before_capture(path: str) -> None:
    with pytest.raises(QueueServiceError, match="relative path"):
        PrepareRunRequest(
            "prepare-demo-001", "demo-001", PreparationSource("shared", "projects", ".", ("configs",)), path, "example-cpu"
        )


def test_preparation_operation_is_principal_bound_idempotent_and_cancellable(tmp_path: Path) -> None:
    profile = ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor=ResidentProfileDescriptor("local", "v1", "project", "environment", "executor").to_dict(),
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=profile,
        preparation_enabled=True,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        view = daemon.client_view(LocalDaemonPrincipal("client-a", LocalDaemonRole.CLIENT))
        accepted = view.prepare_run(_request())
        replay = view.prepare_run(_request())
        assert accepted == replay
        assert accepted.state == "pending"
        assert accepted.result is not None
        assert accepted.result["coordinator_id"] == daemon.status().coordinator_id
        assert view.cancel_preparation("prepare-demo-001").state == "cancelled"
        with pytest.raises(Exception, match="conflicts"):
            daemon.client_view(LocalDaemonPrincipal("client-b", LocalDaemonRole.CLIENT)).prepare_run(_request())
    finally:
        daemon.stop()
