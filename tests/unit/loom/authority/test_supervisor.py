"""Unit tests for explicit authority supervisor helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.authority._repository import initialize_authority_repository
from loom.authority.supervisor import (
    AuthoritySupervisorError,
    AuthoritySupervisorProcessState,
    AuthoritySupervisorReadiness,
    AuthoritySupervisorState,
    inspect_authority_supervisor,
    rotate_authority_repository_generation,
    start_authority_supervisor,
    stop_authority_supervisor,
    supervisor_state_path,
)
from loom.pipeline.stores import (
    AuthorityProtocolReadiness,
    AuthorityRegistryValidationStatus,
    AuthorityServiceHealthState,
    read_authority_registry_record,
)


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
        start_authority_supervisor(state_dir=None)  # type: ignore[arg-type]


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


def test_inspect_reports_missing_registry_fail_closed(tmp_path: Path) -> None:
    result = inspect_authority_supervisor(workspace_root=tmp_path)

    assert result.ok is False
    assert result.readiness is AuthoritySupervisorReadiness.UNKNOWN
    assert result.registry_status is AuthorityRegistryValidationStatus.MISSING
