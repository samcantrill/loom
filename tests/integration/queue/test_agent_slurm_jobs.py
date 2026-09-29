"""The authenticated submit-agent path uses shared reservations, never host GPUs."""

from __future__ import annotations

from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from threading import Event, Thread
import time

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonAdmissionRequest,
)
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    SLURM_SUBMISSION_CAPABILITY,
    AgentControl,
    AgentControlKind,
    TransportPrincipalPolicy,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.errors import QueueConflictError
import loom.queue.deployment as deployment
from loom.queue.deployment import (
    OutboundAgentRegistrationConfig,
    OutboundAgentServiceConfig,
)
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
from tests.integration.queue.test_slurm_ready_stage import (
    _profile,
    _persist_rejected_slurm_run,
    _positive_containment_helper,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("restart_with_job", [False, True])
def test_outbound_service_settles_slurm_while_drained(
    tmp_path: Path, monkeypatch, restart_with_job: bool
):
    credentials = mutual_tls_credentials(tmp_path / "tls")
    runner = FakeSlurmCommandRunner(starting_job_id=6100)
    profile = _profile(
        runner,
        containment_helper=_positive_containment_helper(),
        capability_path=tmp_path / "capability",
    )
    capabilities = (SLURM_SUBMISSION_CAPABILITY,)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=None,
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=None,
        cpu_capacity=0,
        slurm_profiles=(profile,),
        agent_policy=AgentPolicyConfig(
            agents=(
                AgentPrincipalPolicy(
                    "credential",
                    "principal",
                    "agent-a",
                    ("default",),
                    capabilities,
                    external_slurm_profiles=(
                        (profile.profile_id, profile.configuration_fingerprint),
                    ),
                ),
            ),
            principals=(
                TransportPrincipalPolicy(
                    "operator",
                    "operator",
                    "operator",
                    ("drain",),
                    ("agent-a",),
                ),
            ),
        ),
    )
    run_uri = _persist_rejected_slurm_run(config.run_store_root / "one", profile)
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
                ): "credential"
            },
        ),
    )
    server.start()
    agent_config = AgentTlsClientConfig(
        url=f"https://localhost:{server.port}",
        server_ca_path=credentials["ca"].with_suffix(".crt"),
        certificate_path=credentials["agent"].with_suffix(".crt"),
        private_key_path=credentials["agent"].with_suffix(".key"),
        agent_root=tmp_path / "agent",
        slurm_profiles=(profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(agent_config)
    stop, failures = Event(), []
    service = OutboundAgentServiceConfig(
        agent_config,
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
    monkeypatch.setattr(deployment, "_OUTBOUND_POLL_WAIT_MS", 100)

    def serve():
        try:
            deployment.run_outbound_agent_service(service, stop=stop)
        except BaseException as error:
            failures.append(error)

    def eventually(check):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert not failures
            result = check()
            if result:
                return result
            time.sleep(0.02)
        pytest.fail("retained SLURM service progress timed out")

    thread = Thread(target=serve)
    client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
    execution = daemon._execution
    assert execution is not None
    try:
        if restart_with_job:
            # Produce retained ownership through the supported direct client,
            # then hand the same root/session/job to the actual service.
            with closing(LocalDaemonAgentHttpClient(agent_config)) as agent:
                handshake = agent.handshake()
                agent.register(
                    AgentRegistration(
                        "register",
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
                agent.resume_retained_work()
                agent.refresh_resource_offer()
                client.submit(LocalDaemonAdmissionRequest("job", run_uri))
                eventually(execution.slurm_assignments.list_unreleased)
                agent.drive_slurm_jobs()
                assert agent._has_retained_agent_work()
                with pytest.raises(QueueConflictError, match="retained"):
                    agent.shutdown_clean()
            # Exercise session epoch recovery before the serial driver too.
            daemon.stop()
            daemon.start()
            execution = daemon._execution
            assert execution is not None
        thread.start()
        if not restart_with_job:
            client.submit(LocalDaemonAdmissionRequest("job", run_uri))
        eventually(lambda: any(call[0] == "sbatch" for call in runner.calls))
        record = eventually(execution.slurm_assignments.list_unreleased)[0]
        job_id = eventually(
            lambda: (
                execution.slurm_submissions.read(record.assignment.operation_id).job_id
            )
        )
        with sqlite3.connect(tmp_path / "agent" / "control.sqlite") as conn:
            session_id = json.loads(
                conn.execute("SELECT value_json FROM agent_sessions_local").fetchone()[
                    0
                ]
            )["session_id"]
        daemon.operator_view(
            LocalDaemonPrincipal(
                "operator",
                LocalDaemonRole.OPERATOR,
                "operator",
            )
        ).control_agent(
            AgentControl(
                "drain",
                AgentControlKind.DRAIN,
                "agent-a",
                session_id,
                "config-1",
                None,
                False,
                "settle retained scheduler job",
            )
        )

        def drained():
            with sqlite3.connect(tmp_path / "agent" / "control.sqlite") as conn:
                return conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'availability_state'"
                ).fetchone() == ("drained",)

        eventually(drained)
        client.cancel("job")
        eventually(lambda: not execution.slurm_assignments.list_run_unreleased(run_uri))

        def released_locally():
            with sqlite3.connect(tmp_path / "agent" / "slurm.sqlite") as conn:
                return (
                    conn.execute(
                        "SELECT 1 FROM agent_slurm_operations WHERE released=0 OR acknowledged=0"
                    ).fetchone()
                    is None
                )

        eventually(released_locally)
        assert (
            execution.slurm_submissions.read(record.assignment.operation_id).job_id
            == job_id
        )
        assert sum(call[0] == "sbatch" for call in runner.calls) == 1
        assert any(call[0] == "scancel" and job_id in call[1] for call in runner.calls)
    finally:
        stop.set()
        if thread.ident is not None:
            thread.join(15)
        server.stop()
        daemon.stop()
        assert not thread.is_alive()
        assert not failures
        # This fixture owns only the manager thread; the scheduler is simulated
        # and a SLURM-only agent must never start a resident supervisor.
        assert not (tmp_path / "agent" / "supervisor").exists()


def test_two_authenticated_submit_agents_share_quota_and_recover_cancel(tmp_path: Path):
    credentials = mutual_tls_credentials(tmp_path / "tls")
    runner = FakeSlurmCommandRunner(starting_job_id=5100)
    profile = _profile(
        runner,
        containment_helper=_positive_containment_helper(),
        capability_path=tmp_path / "capability",
    )
    permitted = ((profile.profile_id, profile.configuration_fingerprint),)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=None,
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=None,
        cpu_capacity=0,
        slurm_profiles=(profile,),
        agent_policy=AgentPolicyConfig(
            agents=tuple(
                AgentPrincipalPolicy(
                    name + "-credential",
                    name + "-principal",
                    name,
                    ("default",),
                    (SLURM_SUBMISSION_CAPABILITY,),
                    external_slurm_profiles=permitted,
                )
                for name in ("agent-a", "agent-b")
            )
        ),
    )
    first = _persist_rejected_slurm_run(config.run_store_root / "one", profile)
    second = _persist_rejected_slurm_run(config.run_store_root / "two", profile)
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
                certificate_fingerprint(credentials[cert].with_suffix(".crt")): name
                + "-credential"
                for cert, name in (("agent", "agent-a"), ("other", "agent-b"))
            },
        ),
    )
    server.start()
    agents = []
    configs = []
    try:
        for cert, name in (("agent", "agent-a"), ("other", "agent-b")):
            agent_config = AgentTlsClientConfig(
                url=f"https://localhost:{server.port}",
                server_ca_path=credentials["ca"].with_suffix(".crt"),
                certificate_path=credentials[cert].with_suffix(".crt"),
                private_key_path=credentials[cert].with_suffix(".key"),
                agent_root=tmp_path / name,
                slurm_profiles=(profile,),
            )
            LocalDaemonAgentHttpClient.initialize_agent_root(agent_config)
            agent = LocalDaemonAgentHttpClient(agent_config)
            handshake = agent.handshake()
            session = agent.register(
                AgentRegistration(
                    "register-" + name,
                    str(handshake["coordinator_id"]),
                    str(handshake["coordinator_epoch"]),
                    agent.agent_root_id,
                    "config-1",
                    "inventory-1",
                    "availability-1",
                    ("default",),
                    (SLURM_SUBMISSION_CAPABILITY,),
                )
            )
            agent.resume_retained_work()
            agent.refresh_resource_offer()
            offer = agent._require_journal().current_resource_offer(session.session_id)
            assert offer is not None
            unauthorized = replace(
                offer,
                availability_revision="unauthorized",
                external_slurm_profiles=(
                    ("other-profile", profile.configuration_fingerprint),
                ),
            )
            with pytest.raises(QueueConflictError, match="protocol conflict"):
                agent._call(
                    "offer",
                    {
                        "offer": unauthorized.value(),
                        "idempotency_key": "unauthorized-" + name,
                        "expected_availability_revision": offer.availability_revision,
                    },
                )
            assert not agent_config.resident_profiles
            assert agent_config.agent_root is not None
            assert not (agent_config.agent_root / "supervisor").exists()
            agents.append(agent)
            configs.append(agent_config)
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("first", first))
        client.submit(LocalDaemonAdmissionRequest("second", second))
        execution = daemon._execution
        assert execution is not None
        deadline = time.monotonic() + 10
        while (
            not execution.slurm_assignments.list_unreleased()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        records = execution.slurm_assignments.list_unreleased()
        assert len(records) == 1
        assert records[0].assignment.agent_id == "agent-a"
        assert not any(call[0] == "sbatch" for call in runner.calls)
        for agent in agents:
            agent.drive_slurm_jobs()
        assert sum(call[0] == "sbatch" for call in runner.calls) == 1
        assert len(execution.slurm_assignments.list_unreleased()) == 1
        with pytest.raises(QueueConflictError, match="retained"):
            agents[0].shutdown_clean()
        operation_id = records[0].assignment.operation_id
        accepted_sequence, accepted_evidence = (
            execution.slurm_assignments.agent_evidence(
                records[0].assignment.assignment_id
            )
        )
        assert accepted_evidence is not None
        with pytest.raises(QueueConflictError, match="protocol conflict"):
            session_b = agents[1].active_session()
            agents[1]._call(
                "slurm_work",
                {
                    "session_id": session_b.session_id,
                    "coordinator_epoch": session_b.coordinator_epoch,
                    "cursor": None,
                    "evidence": dict(accepted_evidence),
                },
            )
        invalid_release = {
            **accepted_evidence,
            "sequence": accepted_sequence + 1,
            "provider_released": True,
            "release": {"state": "CONTAINED", "echo": {}},
        }
        with pytest.raises(QueueConflictError, match="exact containment"):
            execution.acknowledge_slurm_agent(
                records[0].assignment.agent_id,
                records[0].assignment.agent_root_id,
                invalid_release,
            )
        assert (
            execution.slurm_assignments.agent_evidence(
                records[0].assignment.assignment_id
            )[0]
            == accepted_sequence
        )
        first_handle = execution.slurm_submissions.read(operation_id).job_id
        agents[0].close()
        agents[0] = LocalDaemonAgentHttpClient(configs[0])
        agents[0].resume_retained_work()
        agents[0].drive_slurm_jobs()
        assert execution.slurm_submissions.read(operation_id).job_id == first_handle
        assert sum(call[0] == "sbatch" for call in runner.calls) == 1
        # Coordinator-only and joint restarts retain the original agent/root,
        # attempt and submission identities despite a new process epoch.
        for joint in (False, True):
            if joint:
                agents[0].close()
            daemon.stop()
            daemon.start()
            execution = daemon._execution
            assert execution is not None
            if joint:
                agents[0] = LocalDaemonAgentHttpClient(configs[0])
                agents[0].resume_retained_work()
            for agent in agents:
                session = agent.active_session()
                handshake = agent.handshake()
                agent.reconcile(
                    session.session_id,
                    str(handshake["coordinator_epoch"]),
                    idempotency_key="reconcile-"
                    + handshake["coordinator_epoch"]
                    + session.agent_id,
                )
                agent.drive_slurm_jobs()
            assert execution.slurm_submissions.read(operation_id).job_id == first_handle
            assert sum(call[0] == "sbatch" for call in runner.calls) == 1
        client.cancel("first")
        deadline = time.monotonic() + 10
        while (
            execution.slurm_assignments.list_run_unreleased(first)
            and time.monotonic() < deadline
        ):
            agents[0].drive_slurm_jobs()
            time.sleep(0.02)
        assert not execution.slurm_assignments.list_run_unreleased(first)
        assert any(
            call[0] == "scancel" and first_handle in call[1] for call in runner.calls
        )
        client.cancel("second")
        for agent in agents:
            agent.drive_slurm_jobs()
    finally:
        for agent in agents:
            agent.close()
        server.stop()
        daemon.stop()
