"""Integration coverage for singular run inspection owner joins."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import json
from pathlib import Path
import stat
from typing import Any

import pytest

from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionResult,
    RunLocationReachability,
    decode_run_inspection_response,
    inspect_run,
    projection_callable,
)
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.planning import (
    plan_afterok_slurm_dry_run,
    plan_single_job_slurm_dry_run,
)
from loom.queue import (
    LaunchContract,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
    QueueController,
    QueueEnqueueRequest,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
)
from loom.queue.slurm import SlurmQueueDispatchAdapter, prepared_slurm_launch
from loom.pipeline.status import RunStatus
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.timestamps import utc_timestamp
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store
from tests.integration.queue.test_delegated_slurm_controller import (
    _clock,
    _started_service,
)
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
    run_store, run_uri, _pipeline = _persist_single_stage_run(run_root, skip=True)
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
        assert {stage.state for stage in direct.stages} == {"SKIPPED"}
        for name in (
            RunInspectionAxisName.ADMISSION,
            RunInspectionAxisName.LIFECYCLE,
            RunInspectionAxisName.SCHEDULING,
            RunInspectionAxisName.ASSIGNMENT,
            RunInspectionAxisName.CANCELLATION,
            RunInspectionAxisName.MATERIALIZATION,
            RunInspectionAxisName.SERVICE_HEALTH,
        ):
            assert _axis(direct, name).availability == "available"

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
        assert via_socket.to_dict() == direct.to_dict()
        encoded = json.dumps(via_socket.to_dict(), sort_keys=True)
        assert "intent_digest" not in encoded
        assert '"assignments":' not in encoded
        assert "test-project" not in encoded
    finally:
        if server is not None:
            server.stop()
        daemon.stop()


@pytest.mark.parametrize(
    ("planner", "stage_upstreams", "planning_id", "queue_item_id"),
    (
        (
            plan_single_job_slurm_dry_run,
            {"build": ()},
            "inspect-single",
            "inspect-single-item",
        ),
        (
            plan_afterok_slurm_dry_run,
            {"extract": (), "report": ("extract",)},
            "inspect-afterok",
            "inspect-afterok-item",
        ),
    ),
    ids=("single-job", "afterok"),
)
def test_service_less_slurm_inspection_follows_one_exact_queue_reference(
    tmp_path: Path,
    planner: Callable[..., Any],
    stage_upstreams: dict[str, tuple[str, ...]],
    planning_id: str,
    queue_item_id: str,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        stage_upstreams,
        authority_backed=True,
    )
    planning = planner(
        run_store=store,
        run_uri=run_uri,
        planning_id=planning_id,
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id=queue_item_id,
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    controller = QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=900),
                run_store=store,
            )
        },
    )
    driven = controller.drive_foreground(
        pool_name="slurm-pool",
        until_quiescent=True,
    )
    queue = _ExactQueueReader(service)

    result = inspect_run(run_uri, run_store=store, queue_service=queue)

    assert driven.quiescent is True
    assert queue.read_ids == [queue_item_id]
    assert isinstance(result, RunInspectionResult)
    assert result.run_uri == run_uri
    assert result.queue_item_id == queue_item_id
    assert result.admission_id is None
    assert result.summary == "SUBMITTED"
    assert _axis(result, RunInspectionAxisName.LIFECYCLE).state == "SUBMITTED"
    for name in (
        RunInspectionAxisName.ADMISSION,
        RunInspectionAxisName.SCHEDULING,
        RunInspectionAxisName.ASSIGNMENT,
        RunInspectionAxisName.EXTERNAL_SCHEDULER,
        RunInspectionAxisName.TRANSFER_RESULT,
        RunInspectionAxisName.CANCELLATION,
        RunInspectionAxisName.MATERIALIZATION,
    ):
        assert _axis(result, name).availability == "available"
    log_locations = tuple(
        location for location in result.locations if location.kind == "log"
    )
    shared_log_locations = tuple(
        location
        for location in log_locations
        if location.reachability is RunLocationReachability.SHARED_UNKNOWN
    )
    assert len(shared_log_locations) == len(planning.submission.jobs) * 2
    assert all(location.uri.startswith("file:///") for location in log_locations)
    assert all(
        location.reachability is RunLocationReachability.SHARED_UNKNOWN
        for location in shared_log_locations
    )
    assert all(
        location.availability in {"available", "recorded"} for location in log_locations
    )
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert "SECRET_SHOULD_NOT_BE_COPIED" not in encoded
    assert "loom prepared-run" not in encoded
    assert "sbatch" not in encoded


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
