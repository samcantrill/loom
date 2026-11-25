"""Agent restart, lost reply replay, and guarded session replacement over HTTP."""

from __future__ import annotations

from contextlib import suppress
import json
from multiprocessing import get_context
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import socket
import sqlite3
import sys
from collections.abc import Mapping
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClientError
import loom.queue.agent_session_transport as agent_session_transport
import loom.queue.deployment as queue_deployment
from loom.pipeline.execution.models import ExecutionFailure
from loom.queue._managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    GpuResourceProvider,
    ManagedAssignment,
    ManagedOfferSnapshot,
    SQLiteAgentJournal,
)
from loom.pipeline.runtime import CpuResourcePlanner
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    LocalRunStore,
)
from loom.queue import (
    ExecutionRequirement,
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
    SessionReplacementRequest,
)
from loom.queue._agent_process_supervisor import (
    ResidentWorkerLaunch,
    SupervisorReceipt,
    SupervisorLaunchState,
)
from loom.queue._remote_stage_execution import (
    AgentResourceInventory,
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _RemoteAgentJournal,
    _resident_provider_descriptors,
)
from loom.queue.deployment import (
    OutboundAgentRegistrationConfig,
    OutboundAgentServiceConfig,
    run_outbound_agent_service,
)
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSessionState,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.scheduling import (
    ExactQuantity,
    FifoSchedulingPolicy,
    PolicyDecisionState,
    ResolvedResourceRequest,
    ResourceClaim,
    SchedulingKernel,
    ValidatedResourceEntryView,
    WorkItem,
    WorkSearchState,
)
from loom.serialization import PlainData
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.stage29_composition import ResidentProviderFactory
from tests.support.agent_sessions import (
    _shutdown_detached_remote_supervisors as _shutdown_detached_remote_supervisors,
    _execute_available_assignment,
    _fresh_remote_agent_root,
    _local_launch_profile,
    _policy,
    _prepare_remote_producer_run,
    _prepare_remote_sleep_run,
    _reconcile_remote_agent_application,
    _supervisor_process_ids,
)


@pytest.mark.parametrize("cancel_before_grant", (False, True))
@pytest.mark.parametrize("with_local_agent", (False, True))
def test_outbound_service_retries_lost_pregrant_control_response_before_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_before_grant: bool,
    with_local_agent: bool,
) -> None:
    credentials = _credentials(tmp_path / "tls")
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
        ),
        principals=(TransportPrincipalPolicy(
            "operator", "operator", "operator", ("drain",), ("agent-a",),
        ),),
    )
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_producer_run(
        store,
        run_name="idle-renewal-run",
        machine_id="agent-a",
        value=7,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    daemon_config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent" if with_local_agent else None,
        store.root,
        _local_launch_profile() if with_local_agent else None,
        cpu_capacity=1 if with_local_agent else 0,
        agent_policy=policy,
        remote_profiles=(descriptor,),
    )
    LocalDaemon.initialize(daemon_config)
    daemon = LocalDaemon(daemon_config)
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
                _fingerprint(credentials["agent"].with_suffix(".crt")): (
                    "agent-credential"
                )
            },
        ),
    )
    server.start()
    profile = ResidentExecutionProfile(
        descriptor,
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    provider_factory = ResidentProviderFactory(capacity=1)
    client_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        (profile,),
        agent_resource_provider_factory=provider_factory,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
    original_client_init = LocalDaemonAgentHttpClient.__init__
    client_incarnations = 0

    def record_client_incarnation(
        client: LocalDaemonAgentHttpClient, *args: Any, **kwargs: Any
    ) -> None:
        nonlocal client_incarnations
        original_client_init(client, *args, **kwargs)
        client_incarnations += 1

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "__init__", record_client_incarnation
    )
    monkeypatch.setattr(queue_deployment, "_OUTBOUND_OFFER_TTL_SECONDS", 1)
    monkeypatch.setattr(queue_deployment, "_OUTBOUND_POLL_WAIT_MS", 100)
    original_complete = _RemoteAgentJournal.complete_offer_renewal
    lost_response = Event()
    renewal_replayed = Event()

    def lose_first_renewal_response(
        journal: _RemoteAgentJournal, renewal: object, result: object
    ) -> None:
        if not lost_response.is_set():
            lost_response.set()
            raise QueueServiceError("simulated lost renewal response")
        original_complete(journal, renewal, result)  # type: ignore[arg-type]
        renewal_replayed.set()

    monkeypatch.setattr(
        _RemoteAgentJournal,
        "complete_offer_renewal",
        lose_first_renewal_response,
    )
    original_dispatch = agent_session_transport._dispatch
    lost_control_response = Event()

    def lose_delivered_control_response(
        view: object, operation: str, value: Mapping[str, object]
    ) -> Mapping[str, PlainData]:
        result = original_dispatch(view, operation, value)
        if (
            operation in {"assignment_control", "control_wait"}
            and isinstance(result, Mapping)
            and (result.get("assignment_control" if operation == "control_wait" else "control")
                 is not None) is cancel_before_grant
            and not lost_control_response.is_set()
        ):
            lost_control_response.set()
            raise ConnectionError("simulated lost pre-grant control response")
        return result

    monkeypatch.setattr(
        agent_session_transport, "_dispatch", lose_delivered_control_response
    )
    service = OutboundAgentServiceConfig(
        client_config,
        OutboundAgentRegistrationConfig(
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            capabilities,
        ),
        0.01,
        tmp_path / "agent.yaml",
        "0" * 64,
        "1" * 64,
    )
    stop = Event()
    release_pregrant_poll = Event()
    failure: list[BaseException] = []

    def serve() -> None:
        try:
            run_outbound_agent_service(service, stop=stop)
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    thread = Thread(target=serve)
    thread.start()
    try:
        deadline = monotonic() + 10
        active = 0
        while monotonic() < deadline:
            with sqlite3.connect(daemon_config.control_database) as conn:
                active = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM agent_offers WHERE current = 1"
                    ).fetchone()[0]
                )
            if active:
                break
            sleep(0.02)
        assert active == 1
        # The accepted offer survives the injected lost reply, while an empty
        # supervisor may stop during reconnect. Observe the completed replay
        # before asserting the new incarnation's live process owner.
        assert renewal_replayed.wait(10)
        assert len(_supervisor_process_ids(cast(Path, client_config.agent_root))) == 1

        # Keep the production service idle through more than three complete
        # lease periods. The first accepted renewal response is deliberately
        # lost, so the durable agent intent must replay that exact sequence.
        idle_until = monotonic() + 3.2
        while monotonic() < idle_until:
            assert thread.is_alive(), failure
            sleep(0.02)
        assert lost_response.is_set()
        with sqlite3.connect(daemon_config.control_database) as conn:
            renewal = conn.execute(
                "SELECT sequence FROM agent_offer_renewals"
            ).fetchone()
            current = conn.execute(
                "SELECT COUNT(*) FROM agent_offers WHERE current = 1"
            ).fetchone()
        assert renewal is not None and int(renewal[0]) >= 3
        assert current is not None and int(current[0]) == 1

        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        first_pregrant_poll = Event()
        original_pregrant_poll = (
            LocalDaemonAgentHttpClient._cancel_pregrant_if_requested
        )
        pregrant_polls = 0

        from loom.queue._agent_progress import _cooperative, _steps, _delay

        @_cooperative
        def pause_after_first_pregrant_poll(
            client: LocalDaemonAgentHttpClient, *args: Any, **kwargs: Any
        ):
            nonlocal pregrant_polls
            result = yield from _steps(original_pregrant_poll, client, *args, **kwargs)
            pregrant_polls += 1
            if cancel_before_grant and pregrant_polls == 1:
                first_pregrant_poll.set()
                deadline = monotonic() + 10
                while not release_pregrant_poll.is_set():
                    assert monotonic() < deadline
                    yield from _delay(0.01)
            return result

        monkeypatch.setattr(
            LocalDaemonAgentHttpClient,
            "_cancel_pregrant_if_requested",
            pause_after_first_pregrant_poll,
        )
        if not cancel_before_grant:
            # The negotiated quiet control request may wait for five seconds.
            # Establish the actual lost reply before allowing the job to start.
            assert lost_control_response.wait(10)
        coordinator.submit(LocalDaemonAdmissionRequest("idle-renewal-item", run_uri))
        if cancel_before_grant:
            assert first_pregrant_poll.wait(10)
            coordinator.cancel("idle-renewal-item")
            deadline = monotonic() + 10
            control = None
            while monotonic() < deadline:
                with sqlite3.connect(daemon_config.control_database) as conn:
                    control = conn.execute(
                        "SELECT result_code, acknowledged, state "
                        "FROM remote_assignment_controls"
                    ).fetchone()
                if control is not None:
                    break
                sleep(0.02)
            assert control is not None
            assert lost_control_response.wait(10)
            release_pregrant_poll.set()
            assert (
                coordinator.wait("idle-renewal-item", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            assert authority.open_run(run_uri).status is RunStatus.CANCELLED
            with sqlite3.connect(daemon_config.control_database) as conn:
                control = conn.execute(
                    "SELECT result_code, acknowledged, state "
                    "FROM remote_assignment_controls"
                ).fetchone()
            assert control == ("never_started", 1, "applied")
            with sqlite3.connect(
                cast(Path, client_config.agent_root)
                / "supervisor"
                / "supervisor.sqlite"
            ) as conn:
                assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0
        else:
            assert (
                coordinator.wait("idle-renewal-item", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert authority.open_run(run_uri).status is RunStatus.SUCCEEDED
        assert lost_control_response.is_set()
        # One composition at most per client incarnation, never one
        # reconstruction per offer. Additional transport reconnects are valid.
        assert 1 <= provider_factory.calls <= client_incarnations
        # Stopping an active long poll intentionally preserves its uncertain
        # owner. Drain and settle before requiring a clean supervisor shutdown.
        with sqlite3.connect(daemon_config.control_database) as conn:
            current_session = conn.execute(
                "SELECT session_id, config_revision FROM agent_sessions WHERE state = 'ACTIVE'"
            ).fetchone()
        assert current_session is not None
        operator = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        )
        operator.control_agent(AgentControl(
            "pregrant-test-drain", AgentControlKind.DRAIN, "agent-a",
            current_session[0], current_session[1], None, False,
            "settle the completed service before clean shutdown",
        ))
        deadline = monotonic() + 10
        while True:
            with sqlite3.connect(cast(Path, client_config.agent_root) / "control.sqlite") as conn:
                unresolved = conn.execute(
                    "SELECT COUNT(*) FROM agent_session_references "
                    "WHERE reference_kind = 'delivery' AND resolved = 0"
                ).fetchone()[0]
                pending_poll = conn.execute(
                    "SELECT COUNT(*) FROM agent_poll_state_local "
                    "WHERE state IN ('PENDING', 'FENCED') AND result_json IS NULL"
                ).fetchone()[0]
            if operator.observe_control("pregrant-test-drain")["acknowledged"] and not unresolved and not pending_poll:
                break
            assert monotonic() < deadline
            sleep(0.01)
    finally:
        release_pregrant_poll.set()
        stop.set()
        thread.join(timeout=7)
        server.stop()
        daemon.stop()
    assert not thread.is_alive()
    assert failure == []
    deadline = monotonic() + 2
    while (
        _supervisor_process_ids(cast(Path, client_config.agent_root))
        and monotonic() < deadline
    ):
        sleep(0.01)
    assert _supervisor_process_ids(cast(Path, client_config.agent_root)) == ()


def test_assignment_retry_exhaustion_preserves_the_indeterminate_pregrant_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared pre-grant retry owner never converts exhaustion to a grant."""

    client = object.__new__(LocalDaemonAgentHttpClient)
    attempts = 0
    clock_values = iter((0.0, 0.0, 1.0))

    def indeterminate_operation() -> None:
        nonlocal attempts
        attempts += 1
        raise agent_session_transport._IndeterminateAgentProtocolError(  # noqa: SLF001
            "lost control response"
        )

    monkeypatch.setattr(
        agent_session_transport, "_ASSIGNMENT_RECONCILIATION_SECONDS", 1
    )
    monkeypatch.setattr(
        agent_session_transport, "monotonic", lambda: next(clock_values)
    )
    monkeypatch.setattr(
        client,
        "handshake",
        lambda: (_ for _ in ()).throw(
            agent_session_transport._IndeterminateAgentProtocolError("unavailable")
        ),
    )
    monkeypatch.setattr("loom.queue._agent_progress.sleep", lambda _seconds: None)

    with pytest.raises(agent_session_transport._IndeterminateAgentProtocolError):
        client._assignment_call("session-1", "assignment-1", indeterminate_operation)  # noqa: SLF001
    assert attempts == 2


def test_outbound_service_stop_during_initial_close_cleans_its_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    client_config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
    service = OutboundAgentServiceConfig(
        client_config,
        OutboundAgentRegistrationConfig(
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            ("python",),
        ),
        0.01,
        tmp_path / "agent.yaml",
        "0" * 64,
        "1" * 64,
    )
    stop = Event()
    original_close = LocalDaemonAgentHttpClient.close
    closed = 0

    def fail_handshake(_client: LocalDaemonAgentHttpClient) -> Mapping[str, object]:
        raise QueueServiceError("expected reconnect")

    def stop_during_close(client: LocalDaemonAgentHttpClient) -> None:
        nonlocal closed
        closed += 1
        stop.set()
        original_close(client)

    monkeypatch.setattr(LocalDaemonAgentHttpClient, "handshake", fail_handshake)
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "close", stop_during_close)

    run_outbound_agent_service(service, stop=stop)

    assert closed == 1
    assert _supervisor_process_ids(cast(Path, client_config.agent_root)) == ()


def test_outbound_deployment_fingerprint_rejection_starts_no_supervisor(
    tmp_path: Path,
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
        deployment_configuration_fingerprint="a" * 64,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)

    with pytest.raises(QueueServiceError, match="remote agent binding is invalid"):
        LocalDaemonAgentHttpClient(
            replace(config, deployment_configuration_fingerprint="b" * 64)
        )

    assert _supervisor_process_ids(cast(Path, config.agent_root)) == ()


def test_unavailable_outbound_execution_journal_rejects_before_starting_supervisor(
    tmp_path: Path,
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    (cast(Path, config.agent_root) / "journal.sqlite").unlink()

    with pytest.raises(QueueServiceError, match="execution journal is unavailable"):
        LocalDaemonAgentHttpClient(config)

    assert _supervisor_process_ids(cast(Path, config.agent_root)) == ()


def test_outbound_rejection_preserves_a_preexisting_supervisor(
    tmp_path: Path,
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
        deployment_configuration_fingerprint="a" * 64,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    supervisor = client._supervisor  # noqa: SLF001
    assert supervisor is not None
    status = supervisor.status()
    process_id = status["service_process_id"]
    assert isinstance(process_id, int)
    client.close()
    try:
        with pytest.raises(QueueServiceError, match="remote agent binding is invalid"):
            LocalDaemonAgentHttpClient(
                replace(config, deployment_configuration_fingerprint="b" * 64)
            )

        assert supervisor.status() == status
        assert _supervisor_process_ids(cast(Path, config.agent_root)) == (process_id,)
    finally:
        supervisor.shutdown_clean()


def test_remote_clean_shutdown_joins_terminal_work_until_journal_reconciles(
    tmp_path: Path,
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    supervisor = client._supervisor  # noqa: SLF001
    assert supervisor is not None
    first_epoch = supervisor.continuity_epoch
    workspace = tmp_path / "terminal-workspace"
    workspace.mkdir()
    launch = ResidentWorkerLaunch(
        supervisor_id=supervisor.supervisor_id,
        continuity_epoch=first_epoch,
        agent_id=client.agent_root_id,
        session_id="session-A",
        assignment_id="assignment-A",
        process_execution_id="process-A",
        execution_fence="fence-A",
        launch_operation_id="launch-A",
        bundle_digest="a" * 64,
        workspace_root=workspace,
        profile=profile.launch_profile,
        environment={},
    )
    restarted: LocalDaemonAgentHttpClient | None = None
    client_closed = False
    try:
        supervisor.launch(launch)
        with pytest.raises(QueueConflictError, match="non-quiescent"):
            client.shutdown_clean()
        assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED

        client._require_journal().retain_assignment_reference(  # noqa: SLF001
            "session-A", "assignment-A"
        )
        with pytest.raises(QueueConflictError, match="retained work"):
            client.shutdown_clean()

        # Simulate the role application exiting while the independent process
        # owner remains available for an exact restart join.
        client.close()
        client_closed = True
        joined = LocalDaemonAgentHttpClient(config)
        try:
            assert joined._supervisor is not None  # noqa: SLF001
            assert joined._supervisor.continuity_epoch == first_epoch  # noqa: SLF001
            joined._require_journal().resolve_assignment_reference(  # noqa: SLF001
                "session-A", "assignment-A"
            )
            joined.shutdown_clean()
        finally:
            joined.close()

        restarted = LocalDaemonAgentHttpClient(config)
        assert restarted._supervisor is not None  # noqa: SLF001
        assert restarted._supervisor.continuity_epoch != first_epoch  # noqa: SLF001
        restarted.shutdown_clean()
    finally:
        if restarted is not None:
            restarted.close()
        if not client_closed:
            client.close()
    assert _supervisor_process_ids(cast(Path, config.agent_root)) == ()


def test_remote_guarded_recovery_persists_supervisor_receipt_before_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
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
        ),
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator",
                "operator",
                actions=("recover_unknown", "replace_session"),
                agent_ids=("agent-a",),
            ),
        ),
    )
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_sleep_run(
        store, run_name="remote-recovery", machine_id="agent-a"
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        store.root,
        _local_launch_profile(),
        agent_policy=policy,
        remote_profiles=(descriptor,),
    )
    LocalDaemon.initialize(config)
    coordinator_now = ["2030-01-01T00:00:00+00:00"]
    daemon = LocalDaemon(config, clock=lambda: coordinator_now[0])
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
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential",
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "operator-credential",
            },
        ),
    )
    server.start()
    profile = ResidentExecutionProfile(
        descriptor, Path(__file__).resolve().parents[3], Path(sys.executable)
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    from loom.coordinator import CoordinatorOperatorClient
    from loom.queue._coordinator_transport import HttpsControlTransport

    operator = CoordinatorOperatorClient(
        HttpsControlTransport(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
            role="operator",
        ),
        expected_coordinator_id=daemon.status().coordinator_id,
    )
    release_agent = Event()
    evidence_acknowledged = Event()
    acknowledgement_failures: list[BaseException] = []
    worker = None
    workers: ThreadPoolExecutor | None = None
    successor_agent: LocalDaemonAgentHttpClient | None = None
    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-recovery",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                agent.agent_root_id,
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            )
        )
        agent.publish_offer(
            AgentOffer(
                session.session_id,
                session.coordinator_epoch,
                session.config_revision,
                session.inventory_revision,
                session.availability_revision,
                1,
                0,
                30,
                _resident_provider_descriptors(profile, session.agent_id),
                resident_profiles=(descriptor,),
            ),
            idempotency_key="offer-recovery",
        )
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        workers = ThreadPoolExecutor(max_workers=1)
        worker = workers.submit(
            agent.execute_one,
            session.session_id,
            session.availability_revision,
            sequence=1,
            wait_timeout_ms=5_000,
        )
        coordinator.submit(LocalDaemonAdmissionRequest("recovery-item", run_uri))

        deadline = monotonic() + 10
        assignment_row = None
        while monotonic() < deadline:
            if worker.done():
                worker.result()
            with sqlite3.connect(config.control_database) as conn:
                conn.row_factory = sqlite3.Row
                assignment_row = conn.execute(
                    "SELECT * FROM remote_assignments WHERE run_uri = ? "
                    "AND state = 'RUNNING'",
                    (run_uri,),
                ).fetchone()
            if assignment_row is not None:
                break
            sleep(0.02)
        assert assignment_row is not None
        assignment_id = str(assignment_row["assignment_id"])
        fence = str(assignment_row["fence"])
        snapshot = authority.open_run(run_uri)
        stage = next(item for item in snapshot.stages if item.stage_name == "slow")
        assert stage.status is StageStatus.RUNNING
        attempt = next(
            item
            for item in stage.attempts
            if item.attempt_id == str(assignment_row["attempt_id"])
        )
        request = RecoverUnknownAssignment(
            recovery_id="remote-recovery-1",
            run_uri=run_uri,
            stage_name="slow",
            attempt=int(assignment_row["attempt"]),
            stage_work_id=str(assignment_row["stage_work_id"]),
            assignment_id=assignment_id,
            process_execution_id=f"{assignment_id}:root",
            execution_fence=fence,
            target=ManagedRecoveryTarget(session.agent_id, session.session_id),
            expected_state_version=attempt.revision.sequence,
            requested_outcome="cancelled",
            consider_retry=True,
            reason="remote containment integration proof",
        )
        original_ack = agent._acknowledge_assignment_control  # noqa: SLF001

        def acknowledge_then_pause(*args: object, **kwargs: object) -> None:
            try:
                original_ack(*args, **kwargs)  # type: ignore[arg-type]
            except BaseException as exc:
                acknowledgement_failures.append(exc)
                raise
            finally:
                evidence_acknowledged.set()
            if not release_agent.wait(10):
                raise AssertionError("recovery close did not consume remote evidence")

        monkeypatch.setattr(
            agent, "_acknowledge_assignment_control", acknowledge_then_pause
        )
        active_request = replace(
            request,
            recovery_id="remote-active-recovery",
            reason="must not close a currently observed remote process",
        )
        with pytest.raises(CoordinatorClientError) as active:
            operator.recover_unknown(active_request)
        assert active.value.code == "conflict"
        assert active.value.mutation_outcome == "not_applied"
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM remote_assignment_controls "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
                == 0
            )
        assert not daemon._recovery_fences_ordinary_terminal(  # noqa: SLF001
            assignment_id
        )

        # The exact offer expiry is the coordinator-owned fact that turns the
        # still-retained process outcome from actively observed into unknown.
        coordinator_now[0] = "2030-01-01T00:00:31+00:00"
        pending = operator.recover_unknown(request)
        assert pending["state"] == "pending"
        assert evidence_acknowledged.wait(10)
        assert acknowledgement_failures == [], [
            repr(item.__cause__) for item in acknowledgement_failures
        ]

        deadline = monotonic() + 10
        receipt = operator.recover_unknown(request)
        while receipt["state"] == "pending" and monotonic() < deadline:
            sleep(0.02)
            receipt = operator.recover_unknown(request)
        assert receipt["state"] == "closed"
        evidence = cast(Mapping[str, object], receipt["evidence"])
        assert evidence["kind"] == "managed_supervisor"
        assert evidence["assignment_id"] == assignment_id
        assert evidence["execution_fence"] == fence
        with sqlite3.connect(config.control_database) as conn:
            control = conn.execute(
                "SELECT result_code, evidence_json FROM remote_assignment_controls "
                "WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        assert control is not None
        assert control[0] == "contained"
        assert control[1] is not None
        assert authority.open_run(run_uri).stages[0].status is StageStatus.CANCELLED
        assert coordinator.wait("recovery-item", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.CANCELLED
        )
        assert authority.open_run(run_uri).status is RunStatus.CANCELLED
        assert agent._call("recovery_release_ready", {
            "session_id": session.session_id,
            "assignment_id": assignment_id,
            "fence": fence,
        }) == {"ready": True}
        release_agent.set()
        with pytest.raises(QueueConflictError):
            worker.result(timeout=10)
        assert (
            len(
                SQLiteAgentJournal(
                    cast(Path, remote_config.agent_root) / "journal.sqlite",
                    _allow_initialize=False,
                ).retained_claim_commands()
            )
            == 1
        )
        replacement = operator.replace_agent_session(
            SessionReplacementRequest(
                "replace-remote-agent", session.agent_id, "old agent root was lost"
            )
        )
        assert replacement["state"] == "decision"
        assert replacement["readiness"] == "withheld"
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.publish_offer(
                AgentOffer(
                    session.session_id,
                    session.coordinator_epoch,
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                    0,
                    0,
                    30,
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="stale-old-observation",
            )

        successor_config = replace(
            remote_config,
            agent_root=_fresh_remote_agent_root(tmp_path, "replacement-owner"),
        )
        LocalDaemonAgentHttpClient.initialize_agent_root(successor_config)
        successor_agent = LocalDaemonAgentHttpClient(successor_config)
        successor_handshake = successor_agent.handshake()
        successor = successor_agent.register(
            AgentRegistration(
                "register-replacement-successor",
                str(successor_handshake["coordinator_id"]),
                str(successor_handshake["coordinator_epoch"]),
                successor_agent.agent_root_id,
                "config-2",
                "inventory-2",
                "availability-2",
                ("default",),
                capabilities,
            )
        )
        assert successor.session_id != session.session_id
        successor_agent.publish_offer(
            AgentOffer(
                successor.session_id,
                successor.coordinator_epoch,
                successor.config_revision,
                successor.inventory_revision,
                successor.availability_revision,
                1,
                0,
                30,
                _resident_provider_descriptors(profile, successor.agent_id),
                resident_profiles=(descriptor,),
            ),
            idempotency_key="replacement-successor-observation",
        )
        candidates = daemon._execution._remote_candidates()  # type: ignore[union-attr]  # noqa: SLF001
        successor_target = next(
            target
            for _candidate, target in candidates.values()
            if target.agent_id == successor.agent_id
        )
        assert successor_target.session_id == successor.session_id
        assert successor_target.availability_atoms == ()
        kernel = SchedulingKernel(
            planners={"cpu": CpuResourcePlanner()}, policy=FifoSchedulingPolicy()
        )
        replacement_work = WorkItem(
            "replacement-work",
            1,
            {
                "cpu": ResolvedResourceRequest(
                    "cpu", ValidatedResourceEntryView("cpu", ExactQuantity(1), "count")
                )
            },
        )
        withheld_candidate = next(
            candidate
            for candidate, target in candidates.values()
            if target.agent_id == successor.agent_id
        )
        withheld_decision = kernel.decide(
            work=(replacement_work,), candidates=(withheld_candidate,), as_of=1
        )
        assert withheld_decision.state is PolicyDecisionState.WAIT
        assert withheld_decision.work_evaluations[0].state is WorkSearchState.COMPLETE
        withheld_snapshot = ManagedOfferSnapshot(
            agent_id=successor_target.agent_id,
            session_id=successor_target.session_id,
            offer_revision=successor_target.offer_id,
            snapshot_revision=(successor_target.scheduling_availability_revision),
            inventory_revision=successor_target.inventory_revision,
            availability_revision=(successor_target.scheduling_availability_revision),
            component_descriptors=(CpuResourcePlanner().descriptor,),
            provider_descriptors=successor_target.offer.provider_descriptors,
            atoms=successor_target.availability_atoms,
            reflected_claim_ids=successor_target.reflected_claim_ids,
        )
        daemon._execution.coordinator.publish_offer(withheld_snapshot)  # type: ignore[union-attr]  # noqa: SLF001
        replacement_status = operator.replace_agent_session(
            SessionReplacementRequest(
                "replace-remote-agent", session.agent_id, "old agent root was lost"
            )
        )
        assert replacement_status["readiness"] == "ready"
        with pytest.raises(
            QueueServiceError, match="remote agent session evidence is unavailable"
        ):
            successor_agent.release_contained_assignment(
                session.session_id, assignment_id, fence=fence
            )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent._call(  # noqa: SLF001 - hard-cut wire rejection proof
                "release",
                {
                    "session_id": session.session_id,
                    "assignment_id": assignment_id,
                    "fence": fence,
                    "availability_revision": "unsafe-unproven-release",
                },
            )
        proof_seen_before_capacity_release: list[str] = []
        original_recovered_release = (
            daemon._execution.remote_release_recovered  # type: ignore[union-attr]
        )

        def release_only_after_durable_proof(
            recovery_request: RecoverUnknownAssignment,
        ) -> None:
            with sqlite3.connect(config.control_database) as conn:
                proof_row = conn.execute(
                    "SELECT provider_release_proof_json FROM remote_assignments "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()
            assert proof_row is not None and proof_row[0] is not None
            assert "retirement_secret" not in str(proof_row[0])
            proof_seen_before_capacity_release.append(str(proof_row[0]))
            original_recovered_release(recovery_request)

        monkeypatch.setattr(
            daemon._execution,  # type: ignore[union-attr]
            "remote_release_recovered",
            release_only_after_durable_proof,
        )
        released_old = agent.release_contained_assignment(
            session.session_id,
            assignment_id,
            fence=fence,
        )
        assert released_old.state is AgentSessionState.REPLACED
        assert len(proof_seen_before_capacity_release) == 1
        old_execution_journal = SQLiteAgentJournal(
            cast(Path, remote_config.agent_root) / "journal.sqlite",
            _allow_initialize=False,
        )
        assert old_execution_journal.retained_claim_commands() == ()
        with sqlite3.connect(config.control_database) as conn:
            retained_proof = conn.execute(
                "SELECT provider_release_proof_json FROM remote_assignments "
                "WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        assert retained_proof is not None
        assert retained_proof[0] is not None
        assert "retirement_secret" not in str(retained_proof[0])
        candidates = daemon._execution._remote_candidates()  # type: ignore[union-attr]  # noqa: SLF001
        released_target = next(
            target
            for _candidate, target in candidates.values()
            if target.agent_id == successor.agent_id
        )
        assert released_target.availability_revision == (
            successor_target.availability_revision
        )
        assert released_target.offer_id != successor_target.offer_id
        assert released_target.scheduling_availability_revision != (
            successor_target.scheduling_availability_revision
        )
        assert len(released_target.availability_atoms) == 1
        assert released_target.availability_atoms[0].amount.fraction == 1
        released_candidate = next(
            candidate
            for candidate, target in candidates.values()
            if target.agent_id == successor.agent_id
        )
        released_decision = kernel.decide(
            work=(replacement_work,), candidates=(released_candidate,), as_of=1
        )
        assert released_decision.state is PolicyDecisionState.SELECT
        assert released_decision.candidate_id == released_candidate.candidate_id
        assert released_decision.stage_work_id == replacement_work.stage_work_id
        assert released_decision.selected is not None
        assert released_decision.selected.claims[0].atoms[0].amount == ExactQuantity(1)
        released_snapshot = ManagedOfferSnapshot(
            agent_id=released_target.agent_id,
            session_id=released_target.session_id,
            offer_revision=released_target.offer_id,
            snapshot_revision=released_target.scheduling_availability_revision,
            inventory_revision=released_target.inventory_revision,
            availability_revision=released_target.scheduling_availability_revision,
            component_descriptors=(CpuResourcePlanner().descriptor,),
            provider_descriptors=released_target.offer.provider_descriptors,
            atoms=released_target.availability_atoms,
            reflected_claim_ids=released_target.reflected_claim_ids,
        )
        daemon._execution.coordinator.publish_offer(released_snapshot)  # type: ignore[union-attr]  # noqa: SLF001
        replacement_status = operator.replace_agent_session(
            SessionReplacementRequest(
                "replace-remote-agent", session.agent_id, "old agent root was lost"
            )
        )
        assert replacement_status["owner_counts"]["contained"] == 0  # type: ignore[index]
        assert replacement_status["owner_counts"]["released"] == 1  # type: ignore[index]
    finally:
        release_agent.set()
        if worker is not None and not worker.done():
            with suppress(Exception):
                worker.result(timeout=10)
        if workers is not None:
            workers.shutdown(wait=True)
        supervisor = agent._supervisor  # noqa: SLF001
        if supervisor is not None:
            supervisor.shutdown_for_test()
        if successor_agent is not None:
            successor_supervisor = successor_agent._supervisor  # noqa: SLF001
            if successor_supervisor is not None:
                successor_supervisor.shutdown_for_test()
            successor_agent.close()
        operator.close()
        agent.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("gpu", (False, True))
def test_restarted_agent_with_retained_claim_exposes_no_capacity(
    tmp_path: Path,
    gpu: bool,
) -> None:
    from loom.queue.gpu.occupancy import GpuOccupancyPolicy

    agent_root = _fresh_remote_agent_root(tmp_path)
    project_root = tmp_path / "resident-project"
    project_root.mkdir()
    descriptor = ResidentProfileDescriptor(
        "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
    )
    profile = ResidentExecutionProfile(
        descriptor,
        project_root,
        Path(sys.executable),
        gpu_devices=(
            ResidentGpuDevice(
                GpuDeviceDescriptor("gpu-0", "model", 1024), "GPU-private"
            ),
        )
        if gpu
        else (),
    )
    remote_config = AgentTlsClientConfig(
        "https://localhost:1",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root,
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    assignment = ManagedAssignment(
        "assignment-1",
        "loom-agent:assignment-1",
        "stage-work-1",
        "build",
        1,
        "attempt-1",
        "agent-a",
        "session-1",
        "offer-1",
        "claim-1",
    )
    planner = GpuResourcePlanner() if gpu else CpuResourcePlanner()
    kind = "gpu" if gpu else "cpu"
    atom = next(
        item
        for item in profile.capacity_atoms("agent-a")
        if item.owner_resource_kind == kind
    )
    claim = ResourceClaim(
        kind,
        planner.claim_contracts[0],
        (atom,),
        1,
    )
    provider_descriptor = next(
        item.descriptor
        for item in _resident_provider_descriptors(profile, "agent-a")
        if item.descriptor.kind == kind
    )
    command = ClaimCommand(
        assignment, "assignment-1:prepare:0", claim, provider_descriptor
    )
    execution_journal = SQLiteAgentJournal(
        agent_root / "journal.sqlite", _allow_initialize=False
    )
    execution_journal._open_existing()
    assert (
        execution_journal.persist_request(assignment, {"request": "durable"})
        is AssignmentState.REQUEST_DURABLE
    )
    assert (
        execution_journal.prepare_composite(
            assignment,
            (command,),
            {
                kind: GpuResourceProvider(
                    planner.claim_contracts,
                    (atom,),
                    bindings={atom.local_capacity_key: "GPU-private"},
                )
                if gpu
                else AtomResourceProvider(
                    provider_descriptor,
                    planner.claim_contracts,
                    (atom,),
                )
            },
        )
        is AssignmentState.PREPARED
    )

    # Existing version-12 root and claim survive enabling the default policy.
    with pytest.raises(QueueServiceError, match="changed without reload"):
        LocalDaemonAgentHttpClient(replace(remote_config, max_concurrent_assignments=2))
    assert execution_journal.retained_claim_commands() == (command,)
    restarted = LocalDaemonAgentHttpClient(
        replace(
            remote_config,
            gpu_occupancy_policy=GpuOccupancyPolicy() if gpu else None,
            max_concurrent_assignments=1,
        )
    )
    assert execution_journal.retained_claim_commands() == (command,)
    try:
        offer = AgentOffer(
            "session-1",
            "epoch-1",
            "config-1",
            "inventory-1",
            "availability-1",
            1,
            0,
            30,
            _resident_provider_descriptors(profile, "agent-a"),
            resident_profiles=(descriptor,),
        )
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            restarted.publish_offer(offer, idempotency_key="offer-after-restart")
        with pytest.raises(QueueConflictError, match="cannot poll"):
            restarted.wait_for_work(
                "session-1",
                "availability-1",
                sequence=1,
                wait_timeout_ms=1,
            )
    finally:
        restarted.close()


def test_restarted_agent_with_an_indeterminate_poll_exposes_no_capacity(
    tmp_path: Path,
) -> None:
    agent_root = _fresh_remote_agent_root(tmp_path)
    project_root = tmp_path / "resident-project"
    project_root.mkdir()
    descriptor = ResidentProfileDescriptor(
        "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
    )
    profile = ResidentExecutionProfile(
        descriptor,
        project_root,
        Path(sys.executable),
    )
    remote_config = AgentTlsClientConfig(
        "https://localhost:1",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root,
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    with sqlite3.connect(agent_root / "control.sqlite") as conn:
        conn.execute(
            "INSERT INTO agent_poll_state_local(session_id, availability_revision, "
            "sequence, request_digest, state, result_json) VALUES "
            "('session-1', 'availability-1', 1, 'digest', 'PENDING', NULL)"
        )
        conn.commit()

    restarted = LocalDaemonAgentHttpClient(remote_config)
    try:
        offer = AgentOffer(
            "session-1",
            "epoch-1",
            "config-1",
            "inventory-1",
            "availability-1",
            1,
            0,
            30,
            _resident_provider_descriptors(profile, "agent-a"),
            resident_profiles=(descriptor,),
        )
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            restarted.publish_offer(offer, idempotency_key="offer-after-restart")
        with pytest.raises(QueueConflictError, match="cannot poll"):
            restarted.wait_for_work(
                "session-1",
                "availability-1",
                sequence=1,
                wait_timeout_ms=1,
            )
    finally:
        restarted.close()


@pytest.mark.parametrize(
    ("restart_barrier", "shared_inventory"),
    (
        ("before_workspace", False),
        ("before_supervisor_accept", False),
        ("after_supervisor_accept", False),
        ("before_dispatch_timeout", False),
        ("accepted_reply_timeout", False),
        ("before_result_commit", False),
        ("before_coordinator_release", False),
        ("after_supervisor_accept", True),
        ("failed_before_result_commit", False),
        ("binding_failure_before_result_commit", False),
        ("binding_failure_after_no_start_commit", False),
        ("launch_construction_before_result_commit", False),
        ("legacy_launch_construction", False),
        ("rejection_before_result", False),
        ("missing_claim_before_result_commit", False),
        ("native_failure_before_result_commit", False),
        ("reported_failure_before_result_commit", False),
        ("diagnostic_write", False),
    ),
)
def test_agent_restart_joins_one_supervisor_and_replays_durable_remote_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restart_barrier: str,
    shared_inventory: bool,
) -> None:
    """A fresh application joins one exact operation across every crash barrier."""

    from loom.queue._agent_process_supervisor import _SupervisorCommunicationError

    no_start = restart_barrier in {
        "failed_before_result_commit",
        "binding_failure_before_result_commit",
        "binding_failure_after_no_start_commit",
        "launch_construction_before_result_commit",
        "legacy_launch_construction",
        "rejection_before_result",
        "missing_claim_before_result_commit",
    }
    native_failure = restart_barrier in {
        "native_failure_before_result_commit",
        "diagnostic_write",
    }
    reported_failure = restart_barrier == "reported_failure_before_result_commit"
    credentials = _credentials(tmp_path / "tls")
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
                gpu_devices=(
                    (GpuDeviceDescriptor("GPU-shared", "synthetic", 1024),)
                    if shared_inventory
                    else ()
                ),
            ),
        )
    )
    runs = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_producer_run(
        runs,
        run_name="restart-run",
        account_for=[]
        if restart_barrier == "missing_claim_before_result_commit"
        else "all",
        enforce=("cpu",)
        if no_start and restart_barrier not in {
            "launch_construction_before_result_commit", "legacy_launch_construction",
            "rejection_before_result",
        }
        else (),
        native_failure=native_failure,
        reported_failure=reported_failure,
        machine_id="agent-a",
        value=42,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
        resource_entries=(
            {
                "cpu": {"kind": "cpu", "amount": 1, "unit": "count"},
                "memory": {"kind": "memory", "amount": 128, "unit": "B"},
                "gpu": {
                    "kind": "gpu",
                    "amount": 1,
                    "unit": "count",
                    "attributes": {"allocation_mode": "exclusive"},
                },
            }
            if shared_inventory
            else None
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        runs.root,
        _local_launch_profile(),
        agent_policy=policy,
        remote_profiles=(descriptor,),
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
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential"
            },
        ),
    )
    server.start()
    profile = ResidentExecutionProfile(
        descriptor, Path(__file__).resolve().parents[3], Path(sys.executable)
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        (profile,),
        resource_inventory=(
            AgentResourceInventory(
                cpu_capacity=2,
                memory_capacity_bytes=1024,
                gpu_devices=(
                    ResidentGpuDevice(
                        GpuDeviceDescriptor("GPU-shared", "synthetic", 1024),
                        "GPU-shared",
                    ),
                ),
            )
            if shared_inventory
            else None
        ),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    replacement: LocalDaemonAgentHttpClient | None = None
    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-restart",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                agent.agent_root_id,
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            )
        )
        capacity = remote_config.capacity_profile
        descriptors, atoms, live_claims, statuses = agent._offer_provider_snapshot(
            session_id=session.session_id,
            availability_revision=session.availability_revision,
            capacity_profile=capacity,
        )
        offer = AgentOffer(
            session.session_id,
            session.coordinator_epoch,
            session.config_revision,
            session.inventory_revision,
            session.availability_revision,
            capacity.cpu_capacity,
            capacity.memory_capacity_bytes,
            30,
            descriptors,
            gpu_devices=tuple(item.descriptor for item in capacity.gpu_devices),
            resident_profiles=(descriptor,),
            capacity_atoms=atoms,
            gpu_atoms=tuple(
                atom for atom in atoms if atom.owner_resource_kind == "gpu"
            ),
            reflected_claim_ids=live_claims,
        )
        agent.publish_offer(offer, idempotency_key="offer-restart")
        supervisor = agent._supervisor  # noqa: SLF001 - causal service boundary
        assert supervisor is not None
        execution_owner = daemon._execution
        assert execution_owner is not None
        original_write_failure = execution_owner.run_store.write_stage_failure
        interrupted_write = Event()
        retained_report: str | None = None

        def forbidden_launch(*_args, **_kwargs):
            pytest.fail("failed control setup must not reach the supervisor")

        if no_start:
            monkeypatch.setattr(supervisor, "launch_once", forbidden_launch)
        if restart_barrier in {
            "launch_construction_before_result_commit", "legacy_launch_construction",
            "rejection_before_result",
        }:

            def unavailable_snapshot(*args, **kwargs):
                if restart_barrier != "launch_construction_before_result_commit":
                    # Reproduce the legacy unknown journal without dispatching:
                    # the old constructor exception escaped definite-failure handling.
                    raise RuntimeError("simulated agent application restart")
                raise QueueServiceError("shared snapshot root is not mapped")

            monkeypatch.setattr(
                "loom.queue._agent_assignment.ResidentWorkerLaunch",
                unavailable_snapshot,
            )
        if restart_barrier in {
            "binding_failure_before_result_commit",
            "binding_failure_after_no_start_commit",
        }:
            providers, _journal = agent._runtime_owners(session)

            def unavailable_binding(_command):
                raise OSError("binding unavailable at /worker/configured-binding")

            monkeypatch.setattr(
                providers["cpu"], "worker_environment", unavailable_binding
            )
        if restart_barrier in {
            "before_workspace",
        }:

            def interrupt_delivery(session_id, request, **kwargs):
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(agent, "_execute_delivered_assignment", interrupt_delivery)
        elif restart_barrier in {
            "before_supervisor_accept",
            "after_supervisor_accept",
            "before_dispatch_timeout",
            "accepted_reply_timeout",
        }:
            original_launch = supervisor.launch_once

            def interrupt_launch(value: ResidentWorkerLaunch) -> SupervisorReceipt:
                if restart_barrier == "before_supervisor_accept":
                    raise RuntimeError("simulated agent application restart")
                if restart_barrier == "before_dispatch_timeout":
                    raise _SupervisorCommunicationError(possibly_dispatched=False)
                original_launch(value)
                if restart_barrier == "accepted_reply_timeout":
                    raise _SupervisorCommunicationError(possibly_dispatched=True)
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(supervisor, "launch_once", interrupt_launch)
        elif restart_barrier == "binding_failure_after_no_start_commit":
            assert agent._execution_journal is not None
            original_no_start_commit = agent._execution_journal._set_start_failed

            def interrupt_no_start_commit(*args, **kwargs):
                original_no_start_commit(*args, **kwargs)
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(
                agent._execution_journal, "_set_start_failed", interrupt_no_start_commit
            )
        elif restart_barrier == "diagnostic_write":

            def interrupt_diagnostic_write(*args, **kwargs):
                interrupted_write.set()
                raise OSError("diagnostic persistence interrupted")

            monkeypatch.setattr(
                execution_owner.run_store,
                "write_stage_failure",
                interrupt_diagnostic_write,
            )
            original_commit_result = agent.commit_result

            def interrupt_after_failed_projection(*args, **kwargs):
                try:
                    return original_commit_result(*args, **kwargs)
                except QueueServiceError as exc:
                    assert interrupted_write.is_set()
                    raise RuntimeError("simulated agent application restart") from exc

            monkeypatch.setattr(
                agent, "commit_result", interrupt_after_failed_projection
            )
        elif (
            restart_barrier == "before_result_commit"
            or no_start
            or native_failure
            or reported_failure
        ):

            def interrupt_result(*args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(agent, "commit_result", interrupt_result)
        else:

            def interrupt_release(*args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(agent, "release_assignment", interrupt_release)
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        with ThreadPoolExecutor(max_workers=1) as workers:
            execution = workers.submit(
                _execute_available_assignment,
                agent,
                session.session_id,
                session.availability_revision,
            )
            submitted = coordinator.submit(
                LocalDaemonAdmissionRequest("restart-item", run_uri)
            )
            if restart_barrier == "diagnostic_write":
                with pytest.raises(RuntimeError, match="application restart"):
                    execution.result(timeout=40)
                assert interrupted_write.is_set()
                with sqlite3.connect(config.control_database) as conn:
                    assert (
                        conn.execute("SELECT state FROM remote_assignments").fetchone()[
                            0
                        ]
                        == "RESULT_RETAINED"
                    )
                    retained_report = conn.execute(
                        "SELECT report_json FROM remote_assignments"
                    ).fetchone()[0]
                assert runs.read_stage_failure(run_uri, "build") is None
                assert agent._execution_journal is not None
                assert agent._execution_journal.retained_claim_commands()
                # This direct owner call shares the daemon's mutation boundary.
                with daemon._cycle_lock:
                    reconciled = execution_owner.reconcile_admission(
                        daemon.admission_for_run_uri(run_uri)
                    )
                assert reconciled.state is LocalDaemonAdmissionState.ACTIVE
                monkeypatch.setattr(
                    execution_owner.run_store,
                    "write_stage_failure",
                    original_write_failure,
                )
            elif restart_barrier in {"before_dispatch_timeout", "accepted_reply_timeout"}:
                with pytest.raises(_SupervisorCommunicationError):
                    execution.result(timeout=40)
                assert agent._execution_journal is not None
                assert agent._execution_journal.retained_claim_commands()
            else:
                with pytest.raises(RuntimeError, match="application restart"):
                    execution.result(timeout=40)
        if restart_barrier == "binding_failure_after_no_start_commit":
            assert agent._execution_journal is not None
            retained_commands = agent._execution_journal.retained_claim_commands()
            assert retained_commands
            retained_assignment = retained_commands[0].assignment.assignment_id
            retained = agent._execution_journal.read_result(retained_assignment)
            assert retained is not None
            assert isinstance(retained.failure, ExecutionFailure)
            assert "binding unavailable at /worker/configured-binding" in str(
                retained.failure.details
            )
            assert not tuple(
                cast(Path, remote_config.agent_root).rglob("worker-result.json")
            )
        if shared_inventory:
            assert agent._execution_journal is not None
            assert {
                command.claim.resource_kind
                for command in agent._execution_journal.retained_claim_commands()
            } == {"cpu", "memory", "gpu"}
        supervisor_id = supervisor.supervisor_id
        agent.close()
        replacement = LocalDaemonAgentHttpClient(remote_config)
        replacement_supervisor = replacement._supervisor  # noqa: SLF001
        assert replacement_supervisor is not None
        assert replacement_supervisor.supervisor_id == supervisor_id
        if no_start:
            monkeypatch.setattr(replacement_supervisor, "launch_once", forbidden_launch)
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            replacement.publish_offer(offer, idempotency_key="offer-before-replay")
        if restart_barrier == "rejection_before_result":
            from loom.queue._agent_process_supervisor import AgentProcessSupervisorError

            assert replacement._execution_journal is not None
            original_reject = replacement_supervisor.reject_unstarted_assignment

            def unavailable_rejection(*args, **kwargs):
                raise AgentProcessSupervisorError("managed supervisor operation is invalid")

            monkeypatch.setattr(
                replacement_supervisor, "reject_unstarted_assignment", unavailable_rejection
            )
            with pytest.raises(AgentProcessSupervisorError, match="operation is invalid"):
                replacement.resume_retained_work()
            assert replacement._execution_journal.retained_claim_commands()
            monkeypatch.setattr(
                replacement_supervisor, "reject_unstarted_assignment", original_reject
            )
            original_rejected = replacement._execution_journal.record_supervisor_rejected_start

            def interrupt_rejected(*args, **kwargs):
                raise RuntimeError("interrupted after supervisor rejection")

            monkeypatch.setattr(
                replacement._execution_journal, "record_supervisor_rejected_start",
                interrupt_rejected,
            )
            with pytest.raises(RuntimeError, match="after supervisor rejection"):
                replacement.resume_retained_work()
            assert replacement._execution_journal.retained_claim_commands()
            monkeypatch.setattr(
                replacement._execution_journal, "record_supervisor_rejected_start",
                original_rejected,
            )
        if restart_barrier == "accepted_reply_timeout":
            assert replacement._execution_journal is not None
            claims = replacement._execution_journal.retained_claim_commands()
            original_query = replacement_supervisor.query

            def unavailable_query(_launch):
                raise _SupervisorCommunicationError(possibly_dispatched=False)

            monkeypatch.setattr(replacement_supervisor, "query", unavailable_query)
            with pytest.raises(_SupervisorCommunicationError):
                replacement.resume_retained_work()
            assert replacement._execution_journal.retained_claim_commands() == claims
            monkeypatch.setattr(replacement_supervisor, "query", original_query)
        (replayed,) = replacement.resume_retained_work()
        assert replayed["state"] == "RELEASED"
        assert replacement.resume_retained_work() == ()
        if restart_barrier in {"before_workspace"}:
            with sqlite3.connect(config.control_database) as conn:
                assert conn.execute("SELECT COUNT(*) FROM agent_deliveries").fetchone() == (1,)
        if restart_barrier == "diagnostic_write":
            with sqlite3.connect(config.control_database) as conn:
                assert (
                    conn.execute(
                        "SELECT report_json FROM remote_assignments"
                    ).fetchone()[0]
                    == retained_report
                )
        released = cast(Mapping[str, object], replayed["session"])
        replacement.publish_offer(
            replace(
                offer,
                coordinator_epoch=str(released["coordinator_epoch"]),
                config_revision=str(released["config_revision"]),
                inventory_revision=str(released["inventory_revision"]),
                availability_revision=str(released["availability_revision"]),
            ),
            idempotency_key=f"offer-after-replay:{restart_barrier}",
        )
        with sqlite3.connect(
            cast(Path, remote_config.agent_root) / "supervisor" / "supervisor.sqlite"
        ) as conn:
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == (
                0 if no_start else 1
            )
        assert coordinator.wait("restart-item", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.FAILED
            if no_start or native_failure or reported_failure
            else LocalDaemonAdmissionState.SUCCEEDED
        )
        assert authority.open_run(run_uri).status is (
            RunStatus.FAILED
            if no_start or native_failure or reported_failure
            else RunStatus.SUCCEEDED
        )
        if restart_barrier == "before_result_commit":
            stored_result = runs.read_stage_worker_result(run_uri, "build", attempt=1)
            assert stored_result is not None
            receipt = cast(Mapping[str, Any], stored_result["executor_metadata"])
            assert receipt["execution_kind"] == "resident_stage_worker"
            assert "loom.queue._resident_stage_worker" in receipt["command"]
            assert receipt["request"]["executor_name"] == "local"
            assert str(tmp_path) not in json.dumps(receipt)
        if no_start:
            stored = runs.read_stage_worker_result(run_uri, "build", attempt=1)
            assert stored is not None
            public_request = cast(Mapping[str, Any], stored["executor_metadata"])[
                "request"
            ]
            assert public_request["stage_name"] == "build"
            assert public_request["executor_name"] == "local"
            assert str(tmp_path) not in json.dumps(public_request)
            failure = runs.read_stage_failure(run_uri, "build")
            assert failure is not None
            if restart_barrier == "launch_construction_before_result_commit":
                assert "shared snapshot root is not mapped" in str(failure["message"])
            elif restart_barrier in {"legacy_launch_construction", "rejection_before_result"}:
                assert "durably rejected unstarted assignment" in str(failure["message"])
            else:
                assert "enforce" in str(failure["message"])
            if restart_barrier == "missing_claim_before_result_commit":
                assert "no active claim" in str(failure["message"])
            if restart_barrier in {
                "binding_failure_before_result_commit",
                "binding_failure_after_no_start_commit",
            }:
                assert (
                    "binding unavailable at /worker/configured-binding"
                    in json.dumps(failure)
                )
            with sqlite3.connect(config.execution_database) as conn:
                assert (
                    conn.execute(
                        "SELECT state FROM coordinator_assignments"
                    ).fetchone()[0]
                    == "released"
                )
            assert replacement._execution_journal is not None
            assert replacement._execution_journal.retained_claim_commands() == ()
        if native_failure or reported_failure:
            import io
            from loom.cli.main import main
            from loom.queue import LocalDaemonSocketServer

            failure = runs.read_stage_failure(run_uri, "build")
            assert failure is not None and failure["run_uri"] == run_uri
            if native_failure:
                assert "missing /worker/data/product.json" in json.dumps(failure)
            else:
                assert failure["details"] == {
                    "domain_failure": {"record": {"threshold": 0.5}}
                }
                assert "private-native" not in json.dumps(failure)
            socket_server = LocalDaemonSocketServer(daemon, config.endpoint)
            socket_server.start()
            original_open = Path.open

            def without_worker_files(path: Path, *args, **kwargs):
                if path.is_relative_to(cast(Path, remote_config.agent_root)):
                    raise AssertionError("client inspection must not read worker files")
                return original_open(path, *args, **kwargs)

            try:
                with monkeypatch.context() as inspection_patch:
                    inspection_patch.setattr(Path, "open", without_worker_files)
                    command = [
                        "queue",
                        "daemon-admission",
                        "--endpoint",
                        str(config.endpoint),
                        submitted.admission_id,
                    ]
                    text_output, json_output = io.StringIO(), io.StringIO()
                    errors = io.StringIO()
                    assert main(command, stdout=text_output, stderr=errors) == 0, (
                        errors.getvalue()
                    )
                    assert (
                        main(
                            [*command, "--format", "json"],
                            stdout=json_output,
                            stderr=io.StringIO(),
                        )
                        == 0
                    )
                rendered = text_output.getvalue()
                if native_failure:
                    assert "could not prepare the experiment input" in rendered
                    assert "candidate product path is unusable" in rendered
                    assert (
                        "builtins.FileNotFoundError: missing /worker/data/product.json"
                        in rendered
                    )
                    assert "Prepare the product on the selected worker." in rendered
                else:
                    assert "stage reported a domain failure" in rendered
                    assert "private-native" not in rendered
                view = json.loads(json_output.getvalue())["result"]["owners"][
                    "run_result"
                ]
                assert view["availability"] == "available"
                assert view["failures"] == [failure]
            finally:
                socket_server.stop()
    finally:
        if replacement is not None:
            replacement_supervisor = replacement._supervisor  # noqa: SLF001
            if replacement_supervisor is not None:
                replacement_supervisor.shutdown_for_test()
            replacement.close()
        else:
            agent_supervisor = agent._supervisor  # noqa: SLF001
            if agent_supervisor is not None:
                agent_supervisor.shutdown_for_test()
            agent.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize(
    "restart_barrier",
    (
        "before_supervisor_accept",
        "after_supervisor_accept",
        "before_result_commit",
        "before_coordinator_release",
    ),
)
def test_fresh_agent_processes_replay_one_continuous_supervisor_launch(
    tmp_path: Path, restart_barrier: str
) -> None:
    """A/B use spawned interpreters; only their detached supervisor persists."""

    credentials = _credentials(tmp_path / "tls")
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
    runs = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_producer_run(
        runs,
        run_name="fresh-restart-run",
        machine_id="agent-a",
        value=42,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        runs.root,
        _local_launch_profile(),
        agent_policy=policy,
        remote_profiles=(descriptor,),
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
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential"
            },
        ),
    )
    server.start()
    profile = ResidentExecutionProfile(
        descriptor, Path(__file__).resolve().parents[3], Path(sys.executable)
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    context = get_context("spawn")
    events = context.Queue()
    first = context.Process(
        target=_crash_remote_agent_application,
        args=(remote_config, capabilities, restart_barrier, events),
    )
    second: object | None = None
    try:
        first.start()
        ready = events.get(timeout=20)
        assert ready[0] == "ready", ready
        session = cast(Mapping[str, object], ready[2])
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        coordinator.submit(LocalDaemonAdmissionRequest("fresh-restart-item", run_uri))
        crashed = events.get(timeout=40)
        assert crashed[0] == "crashed", crashed
        assert crashed[3] == ready[3]
        first.join(timeout=20)
        assert first.exitcode == 0

        second = context.Process(
            target=_reconcile_remote_agent_application,
            args=(remote_config, str(session["session_id"]), events),
        )
        second.start()
        replayed = events.get(timeout=20)
        assert replayed[0] == "replayed", replayed
        assert replayed[1] != ready[1]
        assert replayed[2:5] == (True, True, ("RELEASED",))
        assert replayed[5] == ready[3]
        second.join(timeout=20)
        assert second.exitcode == 0
        agent_root = cast(Path, remote_config.agent_root)
        with sqlite3.connect(agent_root / "supervisor" / "supervisor.sqlite") as conn:
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
        assert (
            coordinator.wait("fresh-restart-item", timeout_seconds=10).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        assert authority.open_run(run_uri).status is RunStatus.SUCCEEDED
    finally:
        if first.is_alive():
            first.terminate()
            first.join(timeout=5)
        if second is not None and second.is_alive():
            second.terminate()
            second.join(timeout=5)
        cleanup = LocalDaemonAgentHttpClient(remote_config)
        try:
            assert cleanup._supervisor is not None  # noqa: SLF001
            cleanup._supervisor.shutdown_for_test()  # noqa: SLF001
        finally:
            cleanup.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("transport", ["unix", "https"])
def test_native_control_lost_reply_reconciles_same_id_and_guards_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    """A committed admission survives a dropped reply on either real transport."""
    import loom.queue.local_daemon_transport as unix_transport
    from loom.queue import LocalDaemonSocketServer
    from loom.coordinator import CoordinatorClient

    store = LocalRunStore(tmp_path / "runs")
    run_uri, _authority = _prepare_remote_producer_run(
        store,
        run_name="native-control",
        machine_id="agent-a",
        value=7,
    )
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        store.root,
        None,
        cpu_capacity=0,
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    projection_calls: list[str] = []

    def inspect_run(uri: str) -> Mapping[str, PlainData]:
        projection_calls.append(uri)
        return {"schema_version": 1, "code": "unavailable"}

    dropped = Event()
    if transport == "unix":
        server = LocalDaemonSocketServer(
            daemon, config.endpoint, inspect_run=inspect_run
        )
        server.start()
        client = CoordinatorClient.from_unix_socket(config.endpoint)
        write = unix_transport._write_message

        def drop_unix(
            connection: socket.socket, value: Mapping[str, PlainData]
        ) -> None:
            result = value.get("result")
            if (
                isinstance(result, Mapping)
                and result.get("queue_item_id") == "original-item"
                and not dropped.is_set()
            ):
                dropped.set()
                connection.shutdown(socket.SHUT_RDWR)
                return
            write(connection, value)

        monkeypatch.setattr(unix_transport, "_write_message", drop_unix)
    else:
        credentials = _credentials(tmp_path / "tls")
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    _fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "client-credential"
                },
            ),
            inspect_run=inspect_run,
        )
        server.start()
        connection_path = tmp_path / "client.yaml"
        connection_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "transport": {
                        "kind": "https",
                        "url": f"https://localhost:{server.port}",
                        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                        "certificate_path": str(
                            credentials["other"].with_suffix(".crt")
                        ),
                        "private_key_path": str(
                            credentials["other"].with_suffix(".key")
                        ),
                    },
                }
            )
        )
        connection_path.chmod(0o600)
        client = CoordinatorClient.from_connection_file(connection_path)
        reply = agent_session_transport._Handler._reply

        def drop_http(
            handler: agent_session_transport._Handler,
            status: int,
            value: Mapping[str, object],
        ) -> None:
            result = value.get("result")
            if (
                isinstance(result, Mapping)
                and result.get("queue_item_id") == "original-item"
                and not dropped.is_set()
            ):
                dropped.set()
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            reply(handler, status, value)

        monkeypatch.setattr(agent_session_transport._Handler, "_reply", drop_http)
    try:
        description = client.describe_connection()
        assert description.transport == transport
        assert description.source_modes == ()
        assert description.preparation_profiles == ()
        assert client.status().coordinator_id == daemon._coordinator_id
        assert client.agents().agents == ()
        request = LocalDaemonAdmissionRequest("original-item", run_uri)
        for operation, payload in (
            ("inspect_run", {"run_uri": run_uri}),
            ("admission", {"admission_id": "absent"}),
            ("submit", {"request": request.to_dict()}),
        ):
            with pytest.raises(CoordinatorClientError) as caught:
                # Bypass negotiation so this proves the actual request guard,
                # independently of the already successful handshake.
                client._native_call(
                    operation, payload, "wrong-coordinator", negotiate=False
                )
            assert caught.value.code == "conflict"
            assert (
                caught.value.ids["observed_coordinator_id"]
                == description.coordinator_id
            )
            assert caught.value.mutation_outcome == (
                "not_applied" if operation == "submit" else None
            )
        assert daemon.admissions().admissions == ()
        assert projection_calls == []
        with pytest.raises(CoordinatorClientError) as caught:
            client.inspect_run(run_uri)
        assert caught.value.code == "not_found"
        assert projection_calls == []
        with pytest.raises(CoordinatorClientError) as lost:
            client.submit(request)
        assert dropped.is_set(), (lost.value.code, str(lost.value))
        assert lost.value.mutation_outcome == "unknown"
        assert lost.value.ids["queue_item_id"] == "original-item"
        assert lost.value.ids["run_uri"] == run_uri
        admitted = client.admission_for_queue_item("original-item")
        replay = client.submit(request)
        assert replay.admission_id == admitted.admission_id
        assert replay.intent_digest == admitted.intent_digest
        assert len(client.admissions().admissions) == 1
        detail = client.admission(admitted.admission_id).admission
        assert detail.admission_id == replay.admission_id
        assert detail.intent_digest == replay.intent_digest
        assert detail.revision >= replay.revision
        assert client.inspect_run(run_uri).to_dict() == {
            "schema_version": 1,
            "code": "unavailable",
        }
        changed = client.wait_admission(
            admitted.admission_id, expected_revision=0, timeout_seconds=0
        )
        assert changed.kind.value in {"CHANGED", "TERMINAL"}
        for method, identity in (
            (client.agent, "missing-agent"),
            (client.operation, "missing-operation"),
        ):
            with pytest.raises(CoordinatorClientError) as caught:
                method(identity)
            assert caught.value.code == "not_found"
            assert caught.value.mutation_outcome is None
        cancelled = client.cancel("original-item")
        assert cancelled.cancellation_operation_id is not None
        # Client disconnect does not delete the accepted admission or its intent.
        client.close()
        assert (
            daemon.admission_for_queue_item("original-item").admission_id
            == admitted.admission_id
        )
    finally:
        client.close()
        server.stop()
        daemon.stop()


def _crash_remote_agent_application(
    config: AgentTlsClientConfig,
    capabilities: tuple[str, ...],
    barrier: str,
    events: object,
) -> None:
    """Run application A in a spawned interpreter until one owned crash point."""

    queue = cast(Any, events)
    agent = LocalDaemonAgentHttpClient(config)
    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-fresh-restart",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                agent.agent_root_id,
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            )
        )
        profile = config.resident_profiles[0]
        offer = AgentOffer(
            session.session_id,
            session.coordinator_epoch,
            session.config_revision,
            session.inventory_revision,
            session.availability_revision,
            1,
            0,
            30,
            _resident_provider_descriptors(profile, session.agent_id),
            resident_profiles=(profile.descriptor,),
        )
        agent.publish_offer(offer, idempotency_key="offer-fresh-restart")
        supervisor = agent._supervisor  # noqa: SLF001 - crash barrier evidence
        assert supervisor is not None
        if barrier in {"before_supervisor_accept", "after_supervisor_accept"}:
            original_launch = supervisor.launch_once

            def interrupt_launch(launch: ResidentWorkerLaunch) -> SupervisorReceipt:
                if barrier == "before_supervisor_accept":
                    raise RuntimeError("simulated fresh agent application restart")
                original_launch(launch)
                raise RuntimeError("simulated fresh agent application restart")

            setattr(cast(Any, supervisor), "launch_once", interrupt_launch)
        elif barrier == "before_result_commit":

            def interrupt_result(*args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated fresh agent application restart")

            setattr(cast(Any, agent), "commit_result", interrupt_result)
        else:

            def interrupt_release(*args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated fresh agent application restart")

            setattr(cast(Any, agent), "release_assignment", interrupt_release)
        queue.put(("ready", os.getpid(), session.value(), supervisor.supervisor_id))
        try:
            _execute_available_assignment(
                agent,
                session.session_id,
                session.availability_revision,
            )
        except RuntimeError as exc:
            queue.put(("crashed", os.getpid(), str(exc), supervisor.supervisor_id))
            return
        queue.put(("unexpected_completion", os.getpid()))
    except Exception as exc:  # pragma: no cover - surfaced by the parent assertion
        queue.put(("error", os.getpid(), repr(exc)))
    finally:
        agent.close()
