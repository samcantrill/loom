"""The authenticated submit-agent path uses shared reservations, never host GPUs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
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
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.errors import QueueConflictError
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
from tests.integration.queue.test_slurm_ready_stage import (
    _profile,
    _persist_rejected_slurm_run,
    _positive_containment_helper,
)

pytestmark = pytest.mark.integration


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
