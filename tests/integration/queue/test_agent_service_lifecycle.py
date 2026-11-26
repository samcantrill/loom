"""Process-backed regressions for foreground agent stop and worker loss."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field, replace
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

from loom._pidfd import open_pidfd, send_pidfd_signal

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
from tests.support.agent_sessions import (
    restart_daemon,
    _prepare_remote_sleep_run,
    _fresh_remote_agent_root,
)
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint

pytestmark = pytest.mark.integration


def _wait_until(predicate: Callable[[], bool], *, timeout_seconds: float = 10) -> None:
    deadline = monotonic() + timeout_seconds
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
def remote_owner(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[_RemoteWork]:
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
        store, run_name="lifecycle", machine_id="agent-a", seconds=getattr(request, "param", 30)
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
        ),
        # Service registration, shared-storage preparation and ordinary empty
        # polls precede the worker-loss scenario; they are not its deadline.
        timeout_seconds=30,
    )
    return work


@pytest.mark.parametrize("negotiated", [False, True], ids=["synchronous", "pending-replay"])
def test_stop_finishes_cancellation_that_prevents_worker_launch(
    remote_owner: _RemoteWork,
    monkeypatch: pytest.MonkeyPatch,
    negotiated: bool,
) -> None:
    from loom.queue.agent_sessions import AgentSessionService, LIFECYCLE_CAPABILITY

    # An older coordinator replies to the permit synchronously. A negotiated
    # HTTP 202 is a durable replay boundary at which an agent may stop.
    if not negotiated:
        handshake = AgentSessionService.handshake

        def synchronous(service):
            result = dict(handshake(service))
            capabilities = result["capabilities"]
            assert isinstance(capabilities, (tuple, list))
            result["capabilities"] = [value for value in capabilities if value != LIFECYCLE_CAPABILITY]
            return result
        monkeypatch.setattr(AgentSessionService, "handshake", synchronous)

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
    if negotiated:
        assert work.launches() == ()
        work.start_agent()  # Reopen the retained assignment and settle the denied permit.
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
    from loom.queue._agent_progress import _cooperative, _steps

    resume = LocalDaemonAgentHttpClient._resume_retained_assignments

    @_cooperative
    def observe_join(client, *args, **kwargs):
        joining.set()
        return (yield from _steps(resume, client, *args, **kwargs))

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "_resume_retained_assignments", observe_join
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
    descriptor = open_pidfd(pid)
    try:
        send_pidfd_signal(descriptor, signal.SIGKILL)
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
    # Reconnection also replays the handshake, offer and quiet control poll.
    _wait_until(lambda: len(decisions) >= 2, timeout_seconds=30)
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


@pytest.mark.parametrize("accepted", [False, True])
def test_service_registration_recovers_uncertainty_across_coordinator_restart(
    remote_owner: _RemoteWork, monkeypatch: pytest.MonkeyPatch, accepted: bool,
) -> None:
    from loom.queue.agent_sessions import AgentRegistration
    from loom.queue.errors import QueueServiceError, QueueConflictError

    work = remote_owner
    registration = work.service_config.registration
    client = LocalDaemonAgentHttpClient(work.service_config.client)
    hello = client.handshake()
    request = AgentRegistration(
        "uncertain-service-registration", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]),
        client.agent_root_id, registration.config_revision, registration.inventory_revision,
        registration.availability_revision, registration.pools, registration.capabilities,
    )
    original = client._call

    def lose_registration(operation, value, **kwargs):
        if operation == "register":
            if accepted:
                original(operation, value, **kwargs)
            raise QueueServiceError("registration outcome is indeterminate")
        return original(operation, value, **kwargs)

    monkeypatch.setattr(client, "_call", lose_registration)
    try:
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client._register_service(request)
        assert client._require_journal().pending_registration() == request
        with pytest.raises(QueueConflictError, match="another configuration"):
            client._register_service(replace(request, config_revision="changed"))
        assert client._require_journal().pending_registration() == request
    finally:
        client.close()
    restart_daemon(work.daemon)
    service = work.start_agent()

    def registered_in_current_epoch():
        with sqlite3.connect(work.daemon.config.control_database) as conn:
            rows = conn.execute("SELECT coordinator_epoch FROM agent_sessions WHERE state = 'ACTIVE'").fetchall()
        return len(rows) == 1 and rows[0][0] == work.daemon._epoch

    _wait_until(registered_in_current_epoch)
    service.stop.set()
    service.thread.join(10)
    assert not service.thread.is_alive() and not service.errors
    root = work.service_config.client.agent_root
    assert root is not None
    with sqlite3.connect(root / "control.sqlite") as conn:
        intents = conn.execute("SELECT operation_id, result_json FROM agent_registration_intents").fetchall()
        assert len(intents) == (1 if accepted else 2)
        assert all(result is not None for _operation, result in intents)
        if not accepted:
            rejected = next(json.loads(value) for key, value in intents if key == request.idempotency_key)
            assert rejected["registration_rejected"] == "stale_epoch"
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 1


def test_persistent_service_rotates_registration_only_after_clean_retirement(remote_owner: _RemoteWork, monkeypatch):
    from loom.queue.agent_sessions import AgentRegistration

    work = remote_owner
    registration = work.service_config.registration
    client = LocalDaemonAgentHttpClient(work.service_config.client)
    hello = client.handshake()
    request = AgentRegistration(
        "retired-service-registration", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]),
        client.agent_root_id, registration.config_revision, registration.inventory_revision,
        registration.availability_revision, registration.pools, registration.capabilities,
    )
    try:
        session = client._register_service(request)
        client.retire_clean(session.session_id, idempotency_key="retire-before-service-restart")
    finally:
        client.close()

    def current_sessions():
        with sqlite3.connect(work.daemon.config.control_database) as conn:
            return conn.execute("SELECT session_id FROM agent_sessions WHERE state = 'ACTIVE'").fetchall()

    active_id = None
    resumed = Event()
    active_session = LocalDaemonAgentHttpClient.active_session

    def observe_session(self):
        value = active_session(self)
        if value is not None:
            resumed.set()
        return value

    monkeypatch.setattr(LocalDaemonAgentHttpClient, "active_session", observe_session)
    for _restart in range(2):
        resumed.clear()
        service = work.start_agent()
        assert resumed.wait(10)
        _wait_until(lambda: len(current_sessions()) == 1)
        current = current_sessions()[0][0]
        assert current != session.session_id
        if active_id is not None:
            assert current == active_id
        active_id = current
        service.stop.set()
        service.thread.join(10)
        assert not service.thread.is_alive() and not service.errors
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0] == 2


@pytest.mark.parametrize("loss", ["absent", "later-absent", "fenced", "committed"])
@pytest.mark.parametrize("remote_owner", [0.1], indirect=True)
def test_outstanding_poll_recovery_across_coordinator_epoch(
    remote_owner: _RemoteWork, monkeypatch: pytest.MonkeyPatch, loss: str,
) -> None:
    from loom.queue._agent_progress import _cooperative, _steps

    work = remote_owner
    lost = Event()
    original_call = LocalDaemonAgentHttpClient._call

    class LostApplication(BaseException):
        pass

    @_cooperative
    def lose_response(client, operation, value, **kwargs):
        if operation == "poll" and not lost.is_set():
            if loss == "later-absent" and value["sequence"] == 1:
                result = yield from _steps(original_call, client, operation, value, **kwargs)
                assert result["result"] == "wait"
                coordinator.submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
                return result
            if loss == "fenced":
                with pytest.raises(QueueServiceError):
                    yield from _steps(original_call, client, operation, value, **kwargs)
            if loss == "committed":
                result = yield from _steps(original_call, client, operation, value, **kwargs)
                if result.get("result") != "assignment":
                    return result
            lost.set()
            raise LostApplication()
        return (yield from _steps(original_call, client, operation, value, **kwargs))

    from loom.queue.agent_sessions import AgentSessionService
    from loom.queue.errors import QueueServiceError

    original_delivery = AgentSessionService._take_targeted_delivery

    def lose_before_delivery(service, **kwargs):
        if loss == "fenced" and not lost.is_set():
            raise QueueServiceError("fixture interruption after poll intent")
        return original_delivery(service, **kwargs)

    monkeypatch.setattr(AgentSessionService, "_take_targeted_delivery", lose_before_delivery)
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "_call", lose_response)
    coordinator = work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    )
    if loss != "later-absent":
        coordinator.submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
    first = work.start_agent()
    assert lost.wait(15)
    first.thread.join(timeout=10)
    assert not first.thread.is_alive()
    assert len(first.errors) == 1 and isinstance(first.errors[0], LostApplication)
    root = work.service_config.client.agent_root
    assert root is not None
    with sqlite3.connect(root / "control.sqlite") as conn:
        assert conn.execute("SELECT state FROM agent_poll_state_local").fetchone()[0] == "PENDING"
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        poll = conn.execute("SELECT active, result_json FROM agent_poll_state").fetchone()
    if loss == "absent":
        assert poll is None
    elif loss == "later-absent":
        assert poll is not None and poll[0] == 0
        assert json.loads(poll[1])["sequence"] == 1
        assert json.loads(poll[1])["result"] == "wait"
        with sqlite3.connect(root / "control.sqlite") as conn:
            assert conn.execute("SELECT sequence FROM agent_poll_state_local").fetchone()[0] == 2
    elif loss == "fenced":
        # The initial delivery check now shares the same exact-identity fence
        # cleanup as later checks. The lost client reply still leaves PENDING
        # locally, and epoch recovery below must retain one assignment/launch.
        assert poll == (0, None)
    else:
        assert poll is not None and poll[0] == 0
        assert json.loads(poll[1])["result"] == "assignment"
    from loom.queue.errors import QueueConflictError

    probe = LocalDaemonAgentHttpClient(work.service_config.client)
    try:
        with pytest.raises(
            QueueConflictError, match="retained poll request identity conflicts"
        ):
            probe._resume_pending_poll(wait_timeout_ms=1000)
    finally:
        probe.close()
    old_epoch = work.daemon._epoch
    restart_daemon(work.daemon)
    assert work.daemon._epoch != old_epoch
    second = work.start_agent()
    deadline = monotonic() + 45
    while not work.released():
        assert monotonic() < deadline, "recovered delivery did not release"
        assert not second.errors
        sleep(0.05)
    assert not second.errors
    assert len(work.launches()) == 1
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0] == 1


@pytest.mark.parametrize("already_accepted", [True, False])
def test_late_renewal_reply_preserves_new_offer(remote_owner, monkeypatch, already_accepted):
    from loom.queue import agent_session_transport as transport
    from loom.queue._agent_progress import _Spawn, _delay, _run_manager, _steps
    from loom.queue.agent_sessions import AgentRegistration

    config = remote_owner.service_config
    client = LocalDaemonAgentHttpClient(config.client)
    hello = client.handshake()
    registration = config.registration
    session = client.register(AgentRegistration(
        "late-renewal", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]), client.agent_root_id,
        registration.config_revision, registration.inventory_revision,
        registration.availability_revision, registration.pools, registration.capabilities,
    ))
    first = client.refresh_resource_offer()
    journal = client._require_journal()
    offer = journal.current_resource_offer(session.session_id)
    assert offer is not None and first is not None
    dispatch = transport._dispatch
    held, release = Event(), Event()

    def delay_renewal(view, operation, value):
        if operation == "renew" and not held.is_set():
            result = dispatch(view, operation, value) if already_accepted else None
            held.set()
            assert release.wait(10)
            if result is not None:
                return result
        return dispatch(view, operation, value)

    monkeypatch.setattr(transport, "_dispatch", delay_renewal)
    client._service_progress = True

    def advance():
        attempt = yield _Spawn(_steps(client.refresh_resource_offer))
        try:
            while not held.is_set():
                yield from _delay(0.01)
            replacement = yield from _steps(
                client.publish_offer, replace(offer, ttl_seconds=45, availability_revision="replacement"),
                idempotency_key="replacement-offer", expected_availability_revision=offer.availability_revision,
            )
        finally:
            release.set()
        while not attempt.complete:
            yield from _delay(0.01)
        assert attempt.error is None
        if already_accepted:
            assert attempt.value["offer_id"] == first["offer_id"]
        else:
            assert attempt.value is None
        assert journal.pending_resource_mutation(session.session_id) is None
        next_renewal = journal.next_offer_renewal(session.session_id)
        assert next_renewal is not None and next_renewal.sequence == 1
        assert next_renewal.offer_id == replacement["offer_id"] != first["offer_id"]
        receipt = yield from _steps(client.renew_offer, next_renewal)
        assert receipt["state"] == "renewed" and receipt["offer_id"] == replacement["offer_id"]

    try:
        _run_manager(advance(), _delay(0))
    finally:
        release.set()
        client.close()


def test_agent_restart_recovers_fenced_poll_without_coordinator_restart(
    remote_owner: _RemoteWork, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost rejection after real offer expiry must not wedge startup replay."""
    from loom.queue.errors import QueueConflictError
    import loom.queue.deployment as deployment
    from loom.queue._agent_progress import _cooperative, _delay, _steps

    work = remote_owner
    lost, recovery_finished = Event(), Event()
    during_recovery = []
    offset = [0]
    monkeypatch.setattr(deployment, "monotonic", lambda: monotonic() + offset[0])
    original_refresh = LocalDaemonAgentHttpClient.refresh_resource_offer
    original_call = LocalDaemonAgentHttpClient._call

    class LostApplication(BaseException):
        pass

    @_cooperative
    def short_first_offer(client, *, ttl_seconds=30):
        if not lost.is_set() and client._live_work_poll is not None:
            return None  # Exercise startup from a real expired offer.
        return (yield from _steps(original_refresh, client,
                                 ttl_seconds=ttl_seconds if lost.is_set() else 1))

    @_cooperative
    def lose_expiry_reply(client, operation, value, **kwargs):
        if operation in {"offer", "renew"} and lost.is_set() and not recovery_finished.is_set():
            during_recovery.append(operation)
        try:
            result = yield from _steps(original_call, client, operation, value, **kwargs)
            if operation == "recover_poll":
                offset[0] += 60
                yield from _delay(0.2)
                recovery_finished.set()
            return result
        except QueueConflictError:
            if operation == "poll" and not lost.is_set():
                lost.set()
                raise LostApplication() from None
            raise

    monkeypatch.setattr(LocalDaemonAgentHttpClient, "refresh_resource_offer", short_first_offer)
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "_call", lose_expiry_reply)
    epoch = work.daemon._epoch
    first = work.start_agent()
    assert lost.wait(15)
    first.thread.join(timeout=10)
    assert not first.thread.is_alive()
    assert len(first.errors) == 1 and isinstance(first.errors[0], LostApplication)
    root = work.service_config.client.agent_root
    assert root is not None
    with sqlite3.connect(root / "control.sqlite") as conn:
        session_id, revision, sequence, state = conn.execute(
            "SELECT session_id, availability_revision, sequence, state "
            "FROM agent_poll_state_local"
        ).fetchone()
    assert state == "PENDING"
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute(
            "SELECT active, result_json FROM agent_poll_state"
        ).fetchone() == (0, None)
    assert work.launches() == ()

    # A changed request is not authoritative evidence for consuming this intent.
    probe = LocalDaemonAgentHttpClient(work.service_config.client)
    try:
        for override in ({"wait_timeout_ms": 1000}, {"availability_revision": "other"}):
            with pytest.raises(QueueConflictError) as error:
                probe._call("poll", {
                    "session_id": session_id,
                    "availability_revision": revision,
                    "sequence": sequence,
                    "wait_timeout_ms": 5000,
                    **override,
                })
            assert type(error.value) is QueueConflictError
        with sqlite3.connect(root / "control.sqlite") as conn:
            assert conn.execute("SELECT state FROM agent_poll_state_local").fetchone()[0] == "PENDING"
    finally:
        probe.close()

    work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    ).submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
    second = work.start_agent()
    deadline = monotonic() + 45
    while not work.released():
        assert monotonic() < deadline, (
            "same-epoch pending poll blocked agent recovery", second.errors,
            [(launch.assignment_id, work.supervisor.query(launch).state.value)
             for launch in work.launches()],
            [stage.status.value for stage in work.authority.open_run(work.run_uri).stages],
        )
        assert not second.errors
        sleep(0.05)
    assert recovery_finished.is_set() and during_recovery == []
    assert work.daemon._epoch == epoch
    assert all(stage.status is StageStatus.SUCCEEDED for stage in work.authority.open_run(work.run_uri).stages)
    assert not second.errors
    assert len(work.launches()) == 1
    with sqlite3.connect(work.daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0] == 1
    with sqlite3.connect(root / "control.sqlite") as conn:
        assert conn.execute("SELECT sequence FROM agent_poll_state_local").fetchone()[0] > sequence
