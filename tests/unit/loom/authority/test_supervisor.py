"""Unit tests for explicit authority supervisor helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import patch

from loom.authority._repository import initialize_authority_repository
from loom.authority.supervisor import (
    AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR,
    AuthoritySupervisorError,
    AuthoritySupervisorProcessState,
    AuthoritySupervisorReadiness,
    AuthoritySupervisorState,
    inspect_authority_supervisor,
    rotate_authority_repository_generation,
    restart_authority_supervisor,
    start_authority_supervisor,
    stop_authority_supervisor,
    supervisor_state_path,
    workspace_default_supervisor_state_dir,
)
from loom.pipeline.stores import (
    AuthorityProtocolReadiness,
    AuthorityRegistryValidationStatus,
    AuthorityServiceHealthState,
    read_authority_registry_record,
)
from loom.serialization import json_loads


pytestmark = pytest.mark.unit


class _FakeProcess:
    pid = 43210

    def poll(self) -> int | None:
        return None


class _ExitedFakeProcess:
    pid = 43211
    returncode = 1

    def poll(self) -> int:
        return self.returncode


def test_supervisor_state_round_trips(tmp_path: Path) -> None:
    state = AuthoritySupervisorState(
        pid=123,
        endpoint="http://127.0.0.1:8765",
        state_dir=tmp_path / "state",
        workspace_root=tmp_path,
        workspace_id="workspace-a",
        service_generation="generation-1",
        host="127.0.0.1",
        port=8765,
        started_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:00:00Z",
    )

    restored = AuthoritySupervisorState.from_dict(state.to_dict())

    assert restored == state
    assert supervisor_state_path(tmp_path / "state").name == "supervisor.json"


def test_start_requires_explicit_state_dir() -> None:
    with pytest.raises(AuthoritySupervisorError, match="state-dir"):
        start_authority_supervisor(state_dir=None)


def test_workspace_default_state_dir_is_explicit_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    assert workspace_default_supervisor_state_dir(workspace) == (
        workspace.resolve() / AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR
    )


def test_state_dir_conflicts_with_workspace_default(tmp_path: Path) -> None:
    with pytest.raises(AuthoritySupervisorError, match="mutually exclusive"):
        start_authority_supervisor(
            state_dir=tmp_path / "state",
            use_workspace_default=True,
            workspace_root=tmp_path / "workspace",
        )


def test_start_writes_supervisor_state_and_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor._wait_until_ready",
        lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
    )

    result = start_authority_supervisor(
        state_dir=tmp_path / "state",
        workspace_root=tmp_path / "workspace",
        workspace_id="workspace-a",
        port=8766,
        service_generation="generation-1",
    )

    record = read_authority_registry_record(tmp_path / "workspace")
    assert result.ok is True
    assert result.process_state is AuthoritySupervisorProcessState.RUNNING
    assert record.service_generation == "generation-1"
    assert record.workspace_id == "workspace-a"
    assert record.reference.endpoint == "http://127.0.0.1:8766"
    assert record.service_health_state is AuthorityServiceHealthState.READY
    assert supervisor_state_path(tmp_path / "state").exists()


def test_start_rejects_second_live_authority_for_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor._wait_until_ready",
        lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
    )
    monkeypatch.setattr("loom.authority.supervisor._process_running", lambda pid: True)
    monkeypatch.setattr(
        "loom.authority.supervisor._readiness_for_state",
        lambda state, *, process_state: AuthoritySupervisorReadiness.READY,
    )

    start_authority_supervisor(
        state_dir=tmp_path / "state-a",
        workspace_root=tmp_path / "workspace",
        workspace_id="workspace-a",
        port=8770,
        service_generation="generation-1",
    )

    with pytest.raises(AuthoritySupervisorError) as exc_info:
        start_authority_supervisor(
            state_dir=tmp_path / "state-b",
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
            port=8771,
            service_generation="generation-2",
        )

    assert exc_info.value.code == "authority_supervisor.workspace_authority_exists"


def test_start_fails_if_process_exits_during_startup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _ExitedFakeProcess(),
    )

    with pytest.raises(AuthoritySupervisorError, match="exited during startup"):
        start_authority_supervisor(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
            port=8766,
            service_generation="generation-1",
        )


def test_stop_marks_registry_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor._wait_until_ready",
        lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor._terminate_process",
        lambda pid, *, timeout_seconds: True,
    )
    start_authority_supervisor(
        state_dir=tmp_path / "state",
        workspace_root=tmp_path / "workspace",
        workspace_id="workspace-a",
        port=8767,
        service_generation="generation-1",
    )

    result = stop_authority_supervisor(workspace_root=tmp_path / "workspace")

    assert result.process_state is AuthoritySupervisorProcessState.STOPPED
    assert result.registry_status is AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE
    record = read_authority_registry_record(tmp_path / "workspace")
    assert record.service_health_state is AuthorityServiceHealthState.UNAVAILABLE


def test_rotate_generation_updates_existing_repository(tmp_path: Path) -> None:
    initialize_authority_repository(tmp_path / "state", service_generation="old")

    identity = rotate_authority_repository_generation(
        tmp_path / "state",
        service_generation="new",
    )

    assert identity.service_generation == "new"


def test_restart_rotates_service_generation_and_restarts_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    ):
        monkeypatch.setattr(
            "loom.authority.supervisor._wait_until_ready",
            lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
        )
        monkeypatch.setattr(
            "loom.authority.supervisor._terminate_process",
            lambda pid, *, timeout_seconds: True,
        )

        started = start_authority_supervisor(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
            port=8768,
        )
        restarted = restart_authority_supervisor(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
            port=8768,
        )

        assert restarted.command == "restart"
        assert restarted.ok is True
        assert restarted.process_state is AuthoritySupervisorProcessState.RUNNING
        assert restarted.readiness is AuthoritySupervisorReadiness.READY
        assert restarted.service_generation != started.service_generation


def test_stale_state_reports_unavailable_and_unready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    ):
        monkeypatch.setattr(
            "loom.authority.supervisor._wait_until_ready",
            lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
        )

        start_authority_supervisor(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
            port=8769,
        )
        state_path = supervisor_state_path(tmp_path / "state")
        state_payload = json_loads(state_path.read_text(encoding="utf-8"))
        state = AuthoritySupervisorState.from_dict(state_payload)
        stale = AuthoritySupervisorState(
            pid=state.pid + 1,
            endpoint=state.endpoint,
            state_dir=state.state_dir,
            workspace_root=state.workspace_root,
            workspace_id=state.workspace_id,
            service_generation=state.service_generation,
            host=state.host,
            port=state.port,
            started_at=state.started_at,
            updated_at=state.updated_at,
        )
        state_path.write_text(
            json.dumps(stale.to_dict(), sort_keys=True),
            encoding="utf-8",
        )

        result = inspect_authority_supervisor(
            workspace_root=tmp_path / "workspace",
            workspace_id="workspace-a",
        )

        assert result.command == "status"
        assert result.ok is False
        assert result.process_state is AuthoritySupervisorProcessState.STALE
        assert result.readiness is AuthoritySupervisorReadiness.UNAVAILABLE


def test_inspect_reports_missing_registry_fail_closed(tmp_path: Path) -> None:
    result = inspect_authority_supervisor(workspace_root=tmp_path)

    assert result.ok is False
    assert result.readiness is AuthoritySupervisorReadiness.UNKNOWN
    assert result.registry_status is AuthorityRegistryValidationStatus.MISSING
