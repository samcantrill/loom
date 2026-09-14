"""Integration coverage for singular run inspection owner joins."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import stat

import pytest

from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionResult,
    decode_run_inspection_response,
    inspect_run,
    projection_callable,
)
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.timestamps import utc_timestamp
from tests.integration.queue.test_local_daemon_production import (
    _launch_profile,
    _persist_single_stage_run,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def supervisor_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Stop the independent supervisor initialized by the managed fixture."""

    clients: list[AgentProcessSupervisorClient] = []
    initialize = AgentProcessSupervisorService.initialize

    def tracked_initialize(
        agent_root: Path,
        *,
        configuration: SupervisorLaunchConfiguration,
    ) -> AgentProcessSupervisorClient:
        client = initialize(agent_root, configuration=configuration)
        clients.append(client)
        return client

    monkeypatch.setattr(
        AgentProcessSupervisorService,
        "initialize",
        staticmethod(tracked_initialize),
    )
    yield
    for client in reversed(clients):
        try:
            client.shutdown_for_test()
        except Exception:
            pass


def test_managed_inspection_projects_targeted_owners_through_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisor_cleanup: None,
) -> None:
    del supervisor_cleanup
    run_root = tmp_path / "runs"
    run_store, run_uri, _pipeline = _persist_single_stage_run(run_root)
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    observed_at = utc_timestamp()
    daemon = LocalDaemon(config, clock=lambda: observed_at)
    daemon.start()
    server: LocalDaemonSocketServer | None = None
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("inspection-client", LocalDaemonRole.CLIENT)
        )
        admitted = client.submit(
            LocalDaemonAdmissionRequest("managed-inspection-item", run_uri)
        )
        completed = client.wait("managed-inspection-item", timeout_seconds=10)
        source = run_store
        monkeypatch.setattr(
            "loom.diagnostics.run_inspection.utc_timestamp",
            lambda: observed_at,
        )
        direct = inspect_run(run_uri, run_store=source, daemon=daemon)

        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        assert isinstance(direct, RunInspectionResult)
        assert direct.summary == "SUCCEEDED"
        assert direct.admission_id == admitted.admission_id
        assert direct.queue_item_id == "managed-inspection-item"
        assert {stage.state for stage in direct.stages} == {"SUCCEEDED"}
        for name in (
            RunInspectionAxisName.ADMISSION,
            RunInspectionAxisName.LIFECYCLE,
            RunInspectionAxisName.SCHEDULING,
            RunInspectionAxisName.ASSIGNMENT,
            RunInspectionAxisName.CANCELLATION,
            RunInspectionAxisName.MATERIALIZATION,
            RunInspectionAxisName.SERVICE_HEALTH,
            RunInspectionAxisName.TRANSFER_RESULT,
        ):
            assert _axis(direct, name).availability == "available"
        transfer_result = _axis(direct, RunInspectionAxisName.TRANSFER_RESULT)
        assert transfer_result.owner == "local-agent"
        assert transfer_result.state == "populated"

        server = LocalDaemonSocketServer(
            daemon,
            config.endpoint,
            inspect_run=projection_callable(run_store=source, daemon=daemon),
        )
        server.start()
        assert stat.S_IMODE(config.endpoint.stat().st_mode) == 0o600
        via_socket = decode_run_inspection_response(
            LocalDaemonSocketClient(config.endpoint).inspect_run(run_uri)
        )

        assert isinstance(via_socket, RunInspectionResult)
        assert via_socket.run_uri == direct.run_uri
        assert via_socket.summary == direct.summary
        assert via_socket.queue_item_id == direct.queue_item_id
        assert via_socket.admission_id == direct.admission_id
        assert via_socket.stages == direct.stages
        for name in RunInspectionAxisName:
            direct_axis = _axis(direct, name)
            socket_axis = _axis(via_socket, name)
            assert (
                socket_axis.owner,
                socket_axis.availability,
                socket_axis.state,
                socket_axis.freshness,
                socket_axis.code,
            ) == (
                direct_axis.owner,
                direct_axis.availability,
                direct_axis.state,
                direct_axis.freshness,
                direct_axis.code,
            )
            if isinstance(direct_axis.revision, int) and isinstance(
                socket_axis.revision, int
            ):
                assert socket_axis.revision >= direct_axis.revision
        encoded = json.dumps(via_socket.to_dict(), sort_keys=True)
        assert "intent_digest" not in encoded
        assert '"assignments":' not in encoded
        assert '"journal":' not in encoded
        assert "test-project" not in encoded
    finally:
        if server is not None:
            server.stop()
        daemon.stop()


class _ExactQueueReader:
    """Expose only the single primary-key read used by inspection."""

    def __init__(self, service: object) -> None:
        self._service = service
        self.read_ids: list[str] = []

    def read_item(self, queue_item_id: str) -> object:
        self.read_ids.append(queue_item_id)
        return self._service.read_item(queue_item_id)  # type: ignore[attr-defined,no-any-return]


def _axis(
    result: RunInspectionResult,
    name: RunInspectionAxisName,
) -> RunInspectionAxis:
    return next(axis for axis in result.axes if axis.name is name)
