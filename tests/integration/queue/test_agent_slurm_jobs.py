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


@pytest.mark.parametrize(("restart_with_job", "observation_policy", "batching", "start_held"), [
    (False, False, False, False), (True, False, False, False), (True, True, False, False),
    (True, True, True, False), (True, False, False, True),
])
def test_outbound_service_settles_slurm_while_drained(
    tmp_path: Path, monkeypatch, restart_with_job: bool, observation_policy: bool, batching: bool, start_held: bool,
):
    from loom.queue._slurm_admission import SlurmAdmissionPolicy
    from loom.queue._slurm_observation import SlurmObservationPolicy
    from loom.queue.service_upgrade import inspect_service_settlement

    credentials = mutual_tls_credentials(tmp_path / "tls")
    runner = FakeSlurmCommandRunner(starting_job_id=6100)
    profile = _profile(
        runner,
        max_outstanding=None if restart_with_job else 1,
        containment_helper=_positive_containment_helper(),
        capability_path=tmp_path / "capability",
    )
    if batching:
        from loom.pipeline.executors.slurm.commands import SlurmCommandPolicy, SlurmCommandResult
        from loom.pipeline.executors.slurm.history import SlurmHistoryPolicy
        from loom.timestamps import utc_timestamp

        runner.command_policy = SlurmCommandPolicy(10, 60, 10)
        profile = replace(profile, cluster="cluster-a", accounting_history=SlurmHistoryPolicy(1000))
        identities = {}
        def accounting(**selection):
            names = selection.get("job_names", [selection.get("job_name")])
            lines = []
            for name in names:
                if name not in identities:
                    identities[name] = (6100 + len(identities), utc_timestamp()[:-1])
                job_id, submitted = identities[name]
                lines.append(f"{job_id}|{name}|1000|cluster-a|{submitted}|{job_id}|s{job_id}|RUNNING\n")
            return SlurmCommandResult("sacct", ("sacct",), 0, stdout="".join(lines))
        original_batch = runner.discover_named_operations
        def batch(**selection):
            original_batch(**selection)
            return accounting(**selection)
        monkeypatch.setattr(runner, "discover_named_operations", batch)
        monkeypatch.setattr(runner, "discover_named_operation", accounting)
    capabilities = (SLURM_SUBMISSION_CAPABILITY,)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=None,
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=None,
        cpu_capacity=0,
        slurm_profiles=(profile,),
        slurm_admission=SlurmAdmissionPolicy(8) if restart_with_job else None,
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
                    ("drain", "resume"),
                    ("agent-a",),
                ),
            ),
        ),
    )
    run_uri = _persist_rejected_slurm_run(config.run_store_root / "one", profile)
    held_uri = (
        _persist_rejected_slurm_run(config.run_store_root / "held", profile)
        if restart_with_job else None
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
                ): "credential"
            },
        ),
    )
    server.start()
    agent_config = AgentTlsClientConfig(
        slurm_submit_interval_seconds=1.0 if restart_with_job else None,
        slurm_observation_policy=(SlurmObservationPolicy(300, 8, 4, 10) if batching else
                                  SlurmObservationPolicy(300) if observation_policy else None),
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
    drained_progress = Event()
    retries = []
    original_steps = deployment._steps

    def observed_steps(function, *args, **kwargs):
        if function.__name__ == "drive_slurm_jobs":
            agent = function.__self__
            assert agent._slurm_agent.submit_interval_seconds == agent_config.slurm_submit_interval_seconds
            assert agent._slurm_agent.observation_policy == agent_config.slurm_observation_policy
            if agent._drained and not agent._restart_with_retained_work:
                drained_progress.set()
        try:
            result = yield from original_steps(function, *args, **kwargs)
            if (
                not restart_with_job
                and function.__name__ == "drive_slurm_jobs"
                and any(call[0] == "sbatch" for call in runner.calls)
            ):
                # Receive drain between the scheduler step and the next poll.
                # Application belongs to the next manager boundary; waiting
                # here for its effect would prevent that boundary from running.
                while (
                    not function.__self__._service_control_due
                    and not function.__self__._drained
                    and not stop.is_set()
                ):
                    yield from deployment._delay(0.01)
            return result
        except QueueConflictError as error:
            retries.append((function.__name__, str(error)))
            raise

    monkeypatch.setattr(deployment, "_steps", observed_steps)

    def serve():
        try:
            deployment.run_outbound_agent_service(service, stop=stop, start_held=start_held)
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
        pytest.fail(f"retained SLURM service progress timed out: {retries}")

    def control(kind, operation_id, session_id, *, hold=None):
        return daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR, "operator")
        ).control_agent(AgentControl(
            operation_id, kind, "agent-a", session_id, "config-1", None, False,
            "settle retained scheduler work", startup_hold_id=hold,
        ))

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
                # Retain a second assignment before it reaches sbatch, then
                # restart drained. Observation/release must still progress.
                client.submit(LocalDaemonAdmissionRequest("held", held_uri))
                held = eventually(lambda: execution.slurm_assignments.list_run_unreleased(held_uri))[0]
                if start_held:
                    # This queued command has never reached the agent. A held
                    # restart must not interpret its later delivery as permission.
                    control(AgentControlKind.RESUME, "old-resume", agent.active_session().session_id)
                else:
                    control(AgentControlKind.DRAIN, "before-restart", agent.active_session().session_id)
                    agent.poll_control(agent.active_session().session_id)
                    def retain_held():
                        agent.drive_slurm_jobs()
                        return agent._slurm_agent.journal.find(held.assignment.operation_id)

                    eventually(retain_held)
                    assert agent._slurm_agent.journal.read(held.assignment.operation_id).state.value == "intent"
                with pytest.raises(QueueConflictError, match="retained"):
                    agent.shutdown_clean()
            # Exercise session epoch recovery before the serial driver too.
            daemon.stop()
            daemon.start(start_held=start_held)
            execution = daemon._execution
            assert execution is not None
        thread.start()
        if not restart_with_job:
            client.submit(LocalDaemonAdmissionRequest("job", run_uri))
        eventually(lambda: any(call[0] == "sbatch" for call in runner.calls))
        record = eventually(lambda: execution.slurm_assignments.list_run_unreleased(run_uri))[0]
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
        if start_held:
            def old_resume_refused():
                with sqlite3.connect(tmp_path / "agent" / "control.sqlite") as conn:
                    row = conn.execute("SELECT effect_json, acknowledged FROM agent_controls_local WHERE operation_id='old-resume'").fetchone()
                    return row is not None and row[0] is not None and json.loads(row[0])["code"] == "startup_hold" and row[1] == 1
            eventually(old_resume_refused)
        control(AgentControlKind.DRAIN, "drain", session_id)

        def drained():
            with sqlite3.connect(tmp_path / "agent" / "control.sqlite") as conn:
                state = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'availability_state'"
                ).fetchone() == ("drained",)
                applied = conn.execute(
                    "SELECT acknowledged FROM agent_controls_local WHERE operation_id='drain'"
                ).fetchone() == (1,)
                return state and applied

        eventually(drained)
        agent_settlement = inspect_service_settlement(
            agent_config.agent_root, expected_root_id=record.assignment.agent_root_id,
            include_pending_poll=False,
        )
        assert agent_settlement.availability == "available", agent_settlement.to_dict()
        assert "slurm_submission_or_release" in agent_settlement.value["wait_reasons"]
        coordinator_settlement = inspect_service_settlement(
            config.coordinator_root, expected_root_id=daemon.status().coordinator_id,
        )
        assert coordinator_settlement.availability == "available", coordinator_settlement.to_dict()
        assert "slurm_assignment_or_release" in coordinator_settlement.value["wait_reasons"]
        if not restart_with_job:
            eventually(drained_progress.is_set)
        client.cancel("job")
        eventually(lambda: not execution.slurm_assignments.list_run_unreleased(run_uri))

        def released_locally(operation_id=record.assignment.operation_id):
            with sqlite3.connect(tmp_path / "agent" / "slurm.sqlite") as conn:
                return (
                    conn.execute(
                        "SELECT 1 FROM agent_slurm_operations WHERE operation_id=? "
                        "AND (released=0 OR acknowledged=0)", (operation_id,),
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
        if restart_with_job:
            held_before = execution.slurm_submissions.read(held.assignment.operation_id)
            assert held_before.state.value == "intent"
            from loom.queue.operations import inspect_native_service
            hold = inspect_native_service(agent_config.agent_root).value.get("startup_hold_id")
            assert bool(hold) == start_held
            control(AgentControlKind.RESUME, "resume-held", session_id, hold=hold)
            held_after = eventually(lambda: (
                value if (value := execution.slurm_submissions.read(held.assignment.operation_id)).job_id is not None
                else None
            ))
            assert held_after.request == held_before.request
            assert held_after.job_id is not None
            client.cancel("held")
            eventually(lambda: not execution.slurm_assignments.list_run_unreleased(held_uri))
            eventually(lambda: released_locally(held.assignment.operation_id))
            assert sum(call[0] == "sbatch" for call in runner.calls) == 2
        if batching:
            assert runner.observation_timeouts, "real service never dispatched a batch"

        def settled():
            facts = (
                inspect_service_settlement(
                    agent_config.agent_root, expected_root_id=record.assignment.agent_root_id,
                    include_pending_poll=False,
                ),
                inspect_service_settlement(
                    config.coordinator_root, expected_root_id=daemon.status().coordinator_id,
                ),
            )
            return all(fact.availability == "available" and fact.value["settled"] for fact in facts)

        eventually(settled)
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
