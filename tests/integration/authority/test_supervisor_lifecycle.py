"""Integration tests for local authority supervisor lifecycle helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import socket
import subprocess
import sys
from threading import Barrier
from time import monotonic, sleep
from pathlib import Path

import pytest

import loom.authority.supervisor as supervisor
from loom.authority._service_locks import AuthorityServiceLocks
from loom.authority.supervisor import (
    AuthoritySupervisorError,
    AuthoritySupervisorProcessState,
    AuthoritySupervisorReadiness,
    AuthoritySupervisorState,
    inspect_authority_supervisor,
    restart_authority_supervisor,
    start_authority_supervisor,
    stop_authority_supervisor,
    workspace_default_supervisor_state_dir,
)
from loom.pipeline.stores import (
    AuthorityRegistryValidationStatus,
    read_authority_registry_record,
)


pytestmark = pytest.mark.integration


def test_supervisor_lifecycle_starts_writes_registry_and_stops(tmp_path: Path) -> None:
    port = _free_port()
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    second_port = _free_port()

    try:
        started = start_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
            workspace_id="workspace-a",
            port=port,
        )
        status = inspect_authority_supervisor(workspace_root=workspace)

        record = read_authority_registry_record(workspace)
        assert started.ok is True
        assert started.readiness is AuthoritySupervisorReadiness.READY
        assert status.ok is True
        assert status.registry_status is AuthorityRegistryValidationStatus.VALID
        assert record.reference.endpoint == f"http://127.0.0.1:{port}"
        assert record.state_dir == str(state_dir.resolve())
        state = AuthoritySupervisorState.from_dict(
            json.loads((state_dir / "supervisor.json").read_text(encoding="utf-8"))
        )
        assert state.process_start_ticks
        assert state.process_boot_id

        restarted = restart_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
            workspace_id="workspace-a",
            port=second_port,
        )
        assert restarted.ok is True
        assert restarted.readiness is AuthoritySupervisorReadiness.READY
        assert restarted.process_state is AuthoritySupervisorProcessState.RUNNING
        assert restarted.service_generation != started.service_generation
        assert started.pid != restarted.pid

        status_after_restart = inspect_authority_supervisor(workspace_root=workspace)
        assert status_after_restart.ok is True
        assert (
            status_after_restart.process_state
            is AuthoritySupervisorProcessState.RUNNING
        )
        assert status_after_restart.readiness is AuthoritySupervisorReadiness.READY
        assert status_after_restart.service_generation == restarted.service_generation
    finally:
        stopped = stop_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
        )

    assert stopped.process_state is AuthoritySupervisorProcessState.STOPPED
    assert (
        stopped.registry_status is AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE
    )
    stopped_again = stop_authority_supervisor(
        state_dir=state_dir, workspace_root=workspace
    )
    assert stopped_again.ok is True
    assert stopped_again.process_state is AuthoritySupervisorProcessState.STOPPED


def test_supervisor_lifecycle_supports_explicit_workspace_default(
    tmp_path: Path,
) -> None:
    port = _free_port()
    workspace = tmp_path / "workspace"
    state_dir = workspace_default_supervisor_state_dir(workspace)

    try:
        started = start_authority_supervisor(
            use_workspace_default=True,
            workspace_root=workspace,
            workspace_id="workspace-default",
            port=port,
        )

        assert started.ok is True
        assert started.state_dir == state_dir
        assert (state_dir / "supervisor.json").is_file()
        record = read_authority_registry_record(workspace)
        assert record.state_dir == str(state_dir)
    finally:
        stopped = stop_authority_supervisor(
            use_workspace_default=True,
            workspace_root=workspace,
        )

    assert stopped.process_state is AuthoritySupervisorProcessState.STOPPED


def test_concurrent_starts_leave_one_authority_service_for_root(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    barrier = Barrier(2)
    ports = (_free_port(), _free_port())

    def start(port: int):
        barrier.wait(timeout=8)
        return start_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
            workspace_id="workspace-a",
            port=port,
            timeout_seconds=8,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(start, port) for port in ports]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result(timeout=15))
                except Exception as exc:  # noqa: BLE001 - assert lifecycle failure below.
                    outcomes.append(exc)
        started = [item for item in outcomes if not isinstance(item, Exception)]
        rejected = [item for item in outcomes if isinstance(item, Exception)]
        assert len(started) == 1
        assert len(rejected) == 1
        assert isinstance(rejected[0], AuthoritySupervisorError)
        assert inspect_authority_supervisor(workspace_root=workspace).ok is True
    finally:
        stop_authority_supervisor(state_dir=state_dir, workspace_root=workspace)


def test_start_and_stop_overlap_never_leave_two_authority_services(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    initial = start_authority_supervisor(
        state_dir=state_dir,
        workspace_root=workspace,
        workspace_id="workspace-a",
        port=_free_port(),
        timeout_seconds=8,
    )
    barrier = Barrier(2)

    def start():
        barrier.wait(timeout=8)
        try:
            return start_authority_supervisor(
                state_dir=state_dir,
                workspace_root=workspace,
                workspace_id="workspace-a",
                port=_free_port(),
                timeout_seconds=8,
            )
        except AuthoritySupervisorError as exc:
            return exc

    def stop():
        barrier.wait(timeout=8)
        try:
            return stop_authority_supervisor(
                state_dir=state_dir,
                workspace_root=workspace,
                timeout_seconds=8,
            )
        except AuthoritySupervisorError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            start_future = workers.submit(start)
            stop_future = workers.submit(stop)
            start_result = start_future.result(timeout=15)
            stop_result = stop_future.result(timeout=15)
        if isinstance(stop_result, AuthoritySupervisorError):
            assert stop_result.code == "authority_supervisor.lifecycle_locked"
        else:
            assert stop_result.ok is True
        if isinstance(start_result, AuthoritySupervisorError):
            assert start_result.code in {
                "authority_supervisor.already_running",
                "authority_supervisor.lifecycle_locked",
            }
        else:
            assert start_result.ok is True
            assert start_result.pid != initial.pid
    finally:
        stop_authority_supervisor(state_dir=state_dir, workspace_root=workspace)


def test_direct_service_entrypoint_cannot_bypass_supervisor_ownership(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    started = start_authority_supervisor(
        state_dir=state_dir,
        workspace_root=workspace,
        workspace_id="workspace-a",
        port=_free_port(),
        timeout_seconds=8,
    )
    try:
        direct = subprocess.run(
            [
                sys.executable,
                "-m",
                "loom.authority._server",
                "--state-dir",
                str(state_dir),
                "--workspace-root",
                str(workspace),
                "--workspace-id",
                "workspace-a",
                "--port",
                str(_free_port()),
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )

        assert direct.returncode != 0
        assert "already owned" in direct.stderr
        assert inspect_authority_supervisor(workspace_root=workspace).pid == started.pid
    finally:
        stop_authority_supervisor(state_dir=state_dir, workspace_root=workspace)


def test_launcher_loss_after_spawn_leaves_discoverable_stoppable_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"

    def interrupted_startup(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(supervisor, "_wait_until_ready", interrupted_startup)
    with pytest.raises(KeyboardInterrupt):
        start_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
            workspace_id="workspace-a",
            port=_free_port(),
            timeout_seconds=8,
        )

    try:
        deadline = monotonic() + 8
        while True:
            observed = inspect_authority_supervisor(workspace_root=workspace)
            if (
                observed.process_state is AuthoritySupervisorProcessState.RUNNING
                and observed.readiness is AuthoritySupervisorReadiness.READY
            ):
                break
            if monotonic() >= deadline:
                pytest.fail("child authority service did not publish bootstrap state")
            sleep(0.05)
        assert read_authority_registry_record(workspace).state_dir == str(state_dir)
    finally:
        stopped = stop_authority_supervisor(workspace_root=workspace)

    assert stopped.ok is True
    assert stopped.process_state is AuthoritySupervisorProcessState.STOPPED


def test_stale_stop_cannot_overwrite_a_replacement_bootstrap(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    start_authority_supervisor(
        state_dir=state_dir,
        workspace_root=workspace,
        port=_free_port(),
        timeout_seconds=8,
    )
    assert stop_authority_supervisor(state_dir=state_dir, workspace_root=workspace).ok
    state_path = supervisor.supervisor_state_path(state_dir)
    original_state = state_path.read_bytes()
    original_registry = read_authority_registry_record(workspace)

    # A replacement child retains these locks if its launcher dies before
    # publication, leaving the previous service's state visible briefly.
    with AuthorityServiceLocks.acquire(state_dir=state_dir, workspace_root=workspace):
        stopped = stop_authority_supervisor(
            state_dir=state_dir, workspace_root=workspace
        )
        assert not stopped.ok
        assert stopped.process_state is AuthoritySupervisorProcessState.UNKNOWN
        assert state_path.read_bytes() == original_state
        assert read_authority_registry_record(workspace) == original_registry


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
