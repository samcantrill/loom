"""Integration tests for local authority supervisor lifecycle helpers."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from loom.authority.supervisor import (
    AuthoritySupervisorProcessState,
    AuthoritySupervisorReadiness,
    inspect_authority_supervisor,
    start_authority_supervisor,
    stop_authority_supervisor,
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
    finally:
        stopped = stop_authority_supervisor(
            state_dir=state_dir,
            workspace_root=workspace,
        )

    assert stopped.process_state is AuthoritySupervisorProcessState.STOPPED
    assert stopped.registry_status is AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
