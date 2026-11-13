from __future__ import annotations

import json
from dataclasses import replace
import os
import signal
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.queue._coordinator_transport import HttpsControlTransport
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.queue._agent_process_supervisor import _host_boot_evidence, _launch_from_value
from loom.queue._managed_local import (
    _ManagedApplicationSuspended,
    _cancelled_worker_result,
)
from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
    REMOTE_EXECUTION_CAPABILITY,
    REGULAR_FILE_RELAY_CAPABILITY,
)
from loom.queue.local_daemon import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonAdmissionRequest,
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
)
from tests.integration.queue.test_agent_session_transport import (
    _credentials,
    _fingerprint,
    _fresh_remote_agent_root,
    _local_launch_profile,
    _prepare_remote_sleep_run,
    _resident_provider_descriptors,
)


@pytest.mark.parametrize(
    "restart_coordinator,unqualified_result,namespace_marker,missing_started_ack",
    [(False, False, False, False), (True, False, False, False),
     (False, True, False, False), (False, True, True, False),
     (False, True, True, True)],
)
def test_reboot_containment_closes_and_releases_same_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restart_coordinator: bool,
    unqualified_result: bool,
    namespace_marker: bool,
    missing_started_ack: bool,
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
                actions=("recover_unknown", "replace_session", "drain", "resume"),
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
    start_confirmation = Event()
    if missing_started_ack:
        def interrupt_before_confirmation(*args, **kwargs):
            start_confirmation.set()
            raise _ManagedApplicationSuspended("controlled loss before start acknowledgement")

        monkeypatch.setattr(agent, "confirm_started", interrupt_before_confirmation)
    worker = None
    workers: ThreadPoolExecutor | None = None
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
            suspend_requested=release_agent.is_set,
        )
        coordinator.submit(LocalDaemonAdmissionRequest("recovery-item", run_uri))

        deadline = monotonic() + 10
        assignment_row = None
        while monotonic() < deadline:
            if worker.done() and not missing_started_ack:
                worker.result()
            with sqlite3.connect(config.control_database) as conn:
                conn.row_factory = sqlite3.Row
                assignment_row = conn.execute(
                    "SELECT * FROM remote_assignments WHERE run_uri = ? "
                    "AND state = ?",
                    (run_uri, "GRANTED" if missing_started_ack else "RUNNING"),
                ).fetchone()
            if assignment_row is not None and (not missing_started_ack or start_confirmation.is_set()):
                break
            sleep(0.02)
        assert assignment_row is not None
        assignment_id = str(assignment_row["assignment_id"])
        fence = str(assignment_row["fence"])
        snapshot = authority.open_run(run_uri)
        stage = next(item for item in snapshot.stages if item.stage_name == "slow")
        assert stage.status is (StageStatus.SUBMITTED if missing_started_ack else StageStatus.RUNNING)
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
        if missing_started_ack:
            with sqlite3.connect(config.execution_database) as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM coordinator_events WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0] == 0
            operator.control_agent(AgentControl(
                "recovery-drain", AgentControlKind.DRAIN, session.agent_id,
                session.session_id, session.config_revision, None, False,
                "contain the retained startup assignment",
            ))
            assert agent.poll_control(session.session_id) is not None
            with sqlite3.connect(config.control_database) as conn:
                assert conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE session_id = ? AND current = 1",
                    (session.session_id,),
                ).fetchone()[0] == 0
            # Drain is not itself expiry or containment evidence.
            with pytest.raises(CoordinatorClientError, match="conflict"):
                operator.recover_unknown(request)
        # Suspend only this application. End the exact test-owned process group
        # and supervisor before replacing the kernel observation at its owner.
        release_agent.set()
        with pytest.raises(_ManagedApplicationSuspended):
            worker.result(timeout=10)
        root_id = agent.agent_root_id
        assert remote_config.agent_root is not None
        workspace = _ResidentAssignmentWorkspace(remote_config.agent_root, assignment_id)
        encoded_launch = workspace.supervisor_launch_json()
        assert encoded_launch is not None
        launch = _launch_from_value(json.loads(encoded_launch))
        supervisor = agent._supervisor
        assert supervisor is not None
        running = supervisor.query(launch)
        assert running.process_id is not None
        pidfd = os.pidfd_open(running.process_id)
        try:
            os.killpg(running.process_id, signal.SIGKILL)
            import select

            assert select.select([pidfd], [], [], 5)[0]
        finally:
            os.close(pidfd)
        if unqualified_result:
            result = replace(
                _cancelled_worker_result(workspace.worker_request()),
                status=StageStatus.SUCCEEDED,
            )
            (workspace.root / "worker-result.json").write_text(
                json.dumps(result.to_dict())
            )
        # Reboot recovery requires an unclean owner loss. Orderly shutdown now
        # refuses unsettled receipts, even after this fixture killed the root.
        service_fd = os.pidfd_open(supervisor.service_process_id)
        try:
            signal.pidfd_send_signal(service_fd, signal.SIGKILL)
            assert select.select([service_fd], [], [], 5)[0]
        finally:
            os.close(service_fd)
        agent.close()
        from loom.queue.errors import QueueServiceError

        with pytest.raises(QueueServiceError, match="requires clean shutdown"):
            LocalDaemonAgentHttpClient(remote_config)
        observed = _host_boot_evidence()
        monkeypatch.setattr(
            "loom.queue._agent_process_supervisor._host_boot_evidence",
            lambda: {**observed, "boot": "controlled-next-boot"},
        )
        proof = LocalDaemonAgentHttpClient.recover_reboot(remote_config, "reboot-1")
        assert proof["state"] == "contained"
        assert proof == LocalDaemonAgentHttpClient.recover_reboot(
            remote_config, "reboot-1"
        )
        agent = LocalDaemonAgentHttpClient(remote_config)
        assert agent.agent_root_id == root_id
        if namespace_marker:
            # Kernel containment is established by this fixture above. Exercise
            # the distinct exact-launch marker consumed after namespace recovery;
            # real namespace proof/receipt production has its own OS acceptance.
            assert agent._supervisor is not None
            agent._supervisor.reboot_generations = ()
            agent._supervisor.operator_contained_launches = (launch.launch_operation_id,)
        active_session = agent.active_session()
        assert active_session is not None
        assert active_session.session_id == session.session_id
        if restart_coordinator:
            daemon.stop()
            daemon.start()
        assert agent.resume_retained_work() == ()
        assert agent._restart_with_retained_work
        execution_journal = agent._execution_journal
        assert execution_journal is not None
        assert len(execution_journal.retained_claim_commands()) == 1
        coordinator_now[0] = "2030-01-01T00:00:31+00:00"
        if missing_started_ack:
            with pytest.raises(CoordinatorClientError, match="conflict"):
                operator.recover_unknown(replace(request, process_execution_id="wrong-root"))
            with sqlite3.connect(config.control_database) as conn:
                assert conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[0] == 0
        assert operator.recover_unknown(request)["state"] == "pending"
        original_call = agent._call
        lost = []

        def lose_release(operation, value, **kwargs):
            result = original_call(operation, value, **kwargs)
            if operation == "release" and not lost:
                lost.append(True)
                raise QueueServiceError("controlled lost release reply")
            return result

        monkeypatch.setattr(agent, "_call", lose_release)
        deadline = monotonic() + 10
        while not lost and monotonic() < deadline:
            try:
                agent.resume_retained_work()
            except QueueServiceError as exc:
                assert str(exc) == "controlled lost release reply"
            if not lost:
                sleep(0.02)
        assert lost
        receipt = operator.recover_unknown(request)
        assert receipt["state"] == "closed"
        assert authority.open_run(run_uri).stages[0].status is StageStatus.CANCELLED
        assert agent._require_journal().unresolved_assignment_references()
        agent.resume_retained_work()
        assert not agent._restart_with_retained_work
        assert not execution_journal.retained_claim_commands()
        settled_result = execution_journal.read_result(assignment_id)
        assert settled_result is not None
        assert settled_result.status is not StageStatus.SUCCEEDED
        assert not agent._require_journal().unresolved_assignment_references()
        active_session = agent.active_session()
        assert active_session is not None
        assert active_session.session_id == session.session_id
        if missing_started_ack:
            operator.control_agent(AgentControl(
                "recovery-resume", AgentControlKind.RESUME, session.agent_id,
                session.session_id, session.config_revision, None, False,
                "recovery completed",
            ))
            assert agent.poll_control(session.session_id) is not None
        # Match agent-serve: retained cleanup precedes session reconciliation,
        # and only the reconciled epoch can advertise fresh capacity.
        handshake = agent.handshake()
        current = agent.active_session()
        assert current is not None
        if current.coordinator_epoch != handshake["coordinator_epoch"]:
            agent.reconcile(
                current.session_id,
                str(handshake["coordinator_epoch"]),
                idempotency_key="reboot-capacity-reconcile",
            )
        agent.refresh_resource_offer(ttl_seconds=30)
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT state FROM remote_assignments WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
                == "RELEASED"
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM session_replacements").fetchone()[0]
                == 0
            )
        assert operator.recover_unknown(request)["state"] == "closed"
    finally:
        release_agent.set()
        if workers is not None:
            workers.shutdown(wait=True)
        if agent._supervisor is not None:
            agent._supervisor.shutdown_for_test()
        agent.close()
        operator.close()
        server.stop()
        daemon.stop()
