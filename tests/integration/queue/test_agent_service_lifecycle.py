"""Process-backed regressions for foreground agent stop and worker loss."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import sys
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    ResidentWorkerLaunch,
    SupervisorLaunchState,
    _launch_from_value,
)
from loom.queue._managed_local import SQLiteAgentJournal
from loom.queue._remote_stage_execution import (
    ResidentProfileDescriptor,
    ResidentExecutionProfile,
    REMOTE_EXECUTION_CAPABILITY,
    REGULAR_FILE_RELAY_CAPABILITY,
)
from loom.queue.agent_sessions import AgentPolicyConfig, AgentPrincipalPolicy
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.deployment import (
    OutboundAgentServiceConfig,
    OutboundAgentRegistrationConfig,
    run_outbound_agent_service,
)
from tests.integration.queue.test_agent_session_transport import (
    _prepare_remote_sleep_run,
    _fresh_remote_agent_root,
)
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint

pytestmark = pytest.mark.integration


def _wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 10
    while not predicate():
        assert monotonic() < deadline, "agent lifecycle did not settle"
        sleep(0.02)


@dataclass
class _AgentService:
    stop: Event
    thread: Thread
    errors: list[BaseException]


@dataclass
class _RemoteWork:
    daemon: LocalDaemon
    authority: SQLitePerRunAuthorityStore
    run_uri: str
    service_config: OutboundAgentServiceConfig
    supervisor: AgentProcessSupervisorClient
    services: list[_AgentService] = field(default_factory=list)

    def start_agent(self, *, lifetime: str = "persistent") -> _AgentService:
        stop = Event()
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                run_outbound_agent_service(self.service_config, stop=stop, lifetime=lifetime)
            except BaseException as exc:
                errors.append(exc)

        thread = Thread(target=serve, daemon=True)
        service = _AgentService(stop, thread, errors)
        self.services.append(service)
        thread.start()
        return service

    def launches(self) -> tuple[ResidentWorkerLaunch, ...]:
        root = self.service_config.client.agent_root
        assert root is not None
        with sqlite3.connect(root / "supervisor" / "supervisor.sqlite") as conn:
            return tuple(
                _launch_from_value(json.loads(row[0]))
                for row in conn.execute("SELECT launch_json FROM launches")
            )

    def released(self) -> bool:
        with sqlite3.connect(self.daemon.config.control_database) as conn:
            states = [
                row[0] for row in conn.execute("SELECT state FROM remote_assignments")
            ]
        return states == ["RELEASED"]


@pytest.fixture
def remote_owner(tmp_path: Path) -> Iterator[_RemoteWork]:
    credentials = mutual_tls_credentials(tmp_path / "tls")
    descriptor = ResidentProfileDescriptor(
        "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
    )
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                capabilities,
            ),
        )
    )
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_sleep_run(
        store, run_name="lifecycle", machine_id="agent-a"
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        store.root,
        None,
        cpu_capacity=0,
        agent_policy=policy,
        remote_profiles=(descriptor,),
        poll_interval_seconds=0.05,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                certificate_fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential"
            },
        ),
    )
    server.start()
    client_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        (ResidentExecutionProfile(descriptor, Path.cwd(), Path(sys.executable)),),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
    owner = LocalDaemonAgentHttpClient(client_config)
    supervisor = owner._supervisor
    owner.close()
    assert supervisor is not None
    service_config = OutboundAgentServiceConfig(
        client_config,
        OutboundAgentRegistrationConfig(
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            capabilities,
        ),
        0.05,
        tmp_path / "agent.yaml",
        "0" * 64,
        "1" * 64,
    )
    work = _RemoteWork(daemon, authority, run_uri, service_config, supervisor)
    coordinator = daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    )
    try:
        yield work
    finally:
        for service in work.services:
            service.stop.set()
        with suppress(Exception):
            coordinator.cancel("lifecycle")
        for launch in work.launches():
            with suppress(AgentProcessSupervisorError):
                supervisor.contain(launch)
        for service in work.services:
            service.thread.join(timeout=8)
        with suppress(AgentProcessSupervisorError):
            supervisor.shutdown_for_test()
        server.stop()
        daemon.stop()
        assert all(not service.thread.is_alive() for service in work.services)


@pytest.fixture
def remote_work(remote_owner: _RemoteWork) -> _RemoteWork:
    work = remote_owner
    work.start_agent()
    work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    ).submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
    _wait_until(
        lambda: any(
            stage.status is StageStatus.RUNNING
            for stage in work.authority.open_run(work.run_uri).stages
        )
    )
    return work


def test_stop_finishes_cancellation_that_prevents_worker_launch(
    remote_owner: _RemoteWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = remote_owner
    permit_entered, allow_permit = Event(), Event()
    original_permit = LocalDaemonAgentHttpClient.start_permit

    def delayed_permit(client, *args, **kwargs):
        permit_entered.set()
        assert allow_permit.wait(10)
        return original_permit(client, *args, **kwargs)

    monkeypatch.setattr(LocalDaemonAgentHttpClient, "start_permit", delayed_permit)
    coordinator = work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    )
    service = work.start_agent()
    try:
        coordinator.submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
        assert permit_entered.wait(10)
        coordinator.cancel("lifecycle")
        service.stop.set()
    finally:
        allow_permit.set()
    service.thread.join(timeout=3)
    assert not service.thread.is_alive(), service.errors
    assert service.errors == []
    assert coordinator.wait("lifecycle", timeout_seconds=10).state is (
        LocalDaemonAdmissionState.CANCELLED
    )
    assert work.authority.open_run(work.run_uri).status is RunStatus.CANCELLED
    assert work.released()
    assert work.launches() == ()
    with sqlite3.connect(work.daemon.config.execution_database) as conn:
        events = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT payload_json FROM coordinator_events ORDER BY sequence"
            )
        ]
    assert events[0] == {"kind": "cancelled_before_start"}
    assert not any("process_execution_id" in event for event in events)


def test_foreground_stop_preserves_worker_and_interrupts_restart_join(
    remote_work: _RemoteWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = remote_work
    (launch,) = work.launches()
    original = work.supervisor.query(launch)
    first = work.services[0]
    first.stop.set()
    first.thread.join(timeout=2)
    assert not first.thread.is_alive(), first.errors
    assert first.errors == []
    assert work.supervisor.query(launch).state is SupervisorLaunchState.RUNNING

    joining = Event()
    resume = LocalDaemonAgentHttpClient.resume_retained_work

    def observe_join(client, **kwargs):
        joining.set()
        return resume(client, **kwargs)

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "resume_retained_work", observe_join
    )
    replacement = work.start_agent()
    assert joining.wait(5)
    replacement.stop.set()
    replacement.thread.join(timeout=2)
    assert not replacement.thread.is_alive(), replacement.errors
    assert replacement.errors == []
    current = work.supervisor.query(launch)
    assert current.state is SupervisorLaunchState.RUNNING
    assert current.process_id == original.process_id
    assert work.launches() == (launch,)
    assert work.authority.open_run(work.run_uri).status is RunStatus.RUNNING
    root = work.service_config.client.agent_root
    assert root is not None
    journal = SQLiteAgentJournal(root / "journal.sqlite", _allow_initialize=False)
    assert journal.retained_claim_commands()


@pytest.mark.parametrize("restart_before_loss", [False, True])
def test_remote_worker_loss_commits_failure_and_releases_after_containment(
    remote_work: _RemoteWork,
    restart_before_loss: bool,
) -> None:
    work = remote_work
    if restart_before_loss:
        first = work.services[0]
        first.stop.set()
        first.thread.join(timeout=2)
        assert not first.thread.is_alive(), first.errors
    (launch,) = work.launches()
    _kill_worker(work, launch)
    if restart_before_loss:
        # Exercise repair of a previously observed contained/missing-result state.
        contained = work.supervisor.contain(launch)
        assert contained.state is SupervisorLaunchState.CONTAINED
        assert contained.worker_result_digest is None
        assert not contained.successful_exit
        work.start_agent()
    _wait_until(
        lambda: work.authority.open_run(work.run_uri).status is RunStatus.FAILED
    )
    _wait_until(work.released)
    (stage,) = work.authority.open_run(work.run_uri).stages
    assert stage.status is StageStatus.FAILED
    assert len(stage.attempts) == 1
    assert stage.latest_commit is None
    assert stage.artifact_facts == ()
    assert stage.attempts[0].reason is not None
    assert stage.attempts[0].reason.detail["failure_type"] == "executor_infrastructure"
    result = json.loads((launch.workspace_root / "worker-result.json").read_text())
    assert result["failure"]["failure_type"] == "executor_infrastructure"
    assert result["failure"]["signal"] == signal.SIGKILL
    contained = work.supervisor.query(launch)
    assert contained.worker_result_digest is not None
    assert not contained.successful_exit
    assert work.launches() == (launch,)
    assert all(service.errors == [] for service in work.services)


def test_late_cancellation_waits_for_remote_provider_release(
    remote_work: _RemoteWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = remote_work
    releasing = Event()
    allow_release = Event()
    release = LocalDaemonAgentHttpClient._release_provider_claims

    def wait_before_release(client, *args, **kwargs):
        releasing.set()
        assert allow_release.wait(10)
        return release(client, *args, **kwargs)

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "_release_provider_claims", wait_before_release
    )
    coordinator = work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    )
    try:
        (launch,) = work.launches()
        _kill_worker(work, launch)
        assert releasing.wait(10)
        _wait_until(
            lambda: work.authority.open_run(work.run_uri).status is RunStatus.FAILED
        )
        assert coordinator.admission_for_queue_item("lifecycle").state is (
            LocalDaemonAdmissionState.ACTIVE
        )
        assert not work.released()
        coordinator.cancel("lifecycle")
        with pytest.raises(TimeoutError):
            coordinator.wait("lifecycle", timeout_seconds=0.2)
    finally:
        allow_release.set()
    assert coordinator.wait("lifecycle", timeout_seconds=10).state is (
        LocalDaemonAdmissionState.FAILED
    )
    _wait_until(work.released)


def _kill_worker(work: _RemoteWork, launch: ResidentWorkerLaunch) -> None:
    pid = work.supervisor.query(launch).process_id
    assert pid is not None
    descriptor = os.pidfd_open(pid)
    try:
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        assert select.select([descriptor], [], [], 3)[0]
    finally:
        os.close(descriptor)


def test_run_owned_agent_does_not_retire_on_unavailable_or_stale_decision(remote_owner: _RemoteWork, monkeypatch: pytest.MonkeyPatch) -> None:
    work = remote_owner
    reached = Event()
    original = LocalDaemonAgentHttpClient._call
    decisions = []

    def intercepted(self, operation, value, **kwargs):
        if operation == "service_lifetime":
            decisions.append(dict(value))
            reached.set()
            if len(decisions) == 1:
                raise QueueServiceError("coordinator unavailable")
            return {**value, "state": "authorized", "coordinator_id": "stale-owner"}
        return original(self, operation, value, **kwargs)

    from loom.queue.errors import QueueServiceError
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "_call", intercepted)
    service = work.start_agent(lifetime="run")
    assert reached.wait(10)
    _wait_until(lambda: len(decisions) >= 2)
    assert service.thread.is_alive()
    assert work.supervisor.status()["service_process_id"] == work.supervisor.service_process_id
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_retirement_proofs").fetchone()[0] == 0


def test_retirement_replay_stays_authorized_after_new_startup_hold(remote_owner: _RemoteWork, monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    work = remote_owner
    original = LocalDaemonAgentHttpClient._call
    decisions = []
    def interrupted_reply(self, operation, value, **kwargs):
        decision = original(self, operation, value, **kwargs)
        if operation == "service_lifetime" and value["action"] == "observe" and decision["state"] == "authorized" and not decisions:
            work.daemon._lifetime.attach("racing-starter", time.time() + 20)
            replay = original(self, operation, value, **kwargs)
            decisions.extend([decision, replay])
        return decision
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "_call", interrupted_reply)
    service = work.start_agent(lifetime="run")
    service.thread.join(15)
    assert not service.thread.is_alive()
    assert not service.errors
    assert len(decisions) == 2 and decisions[0] == decisions[1]
    assert decisions[1]["state"] == "authorized"
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT state FROM agent_sessions").fetchone()[0] == "RETIRED_CLEAN"
        record = json.loads(conn.execute("SELECT value FROM daemon_metadata WHERE key LIKE 'service-agent:%'").fetchone()[0])
    assert record["state"] == "closed"
    assert not work.daemon._lifetime.retire_if_idle()
    work.daemon._lifetime.release("racing-starter")
