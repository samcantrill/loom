"""Remote assignment, resource selection, and result transfer over HTTP."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
from collections.abc import Mapping
from threading import Event
from time import monotonic, sleep
from typing import Any, cast
from types import SimpleNamespace

import pytest

from loom.coordinator import CoordinatorClient
import loom.queue.agent_session_transport as agent_session_transport
import loom.queue.local_daemon_execution as local_daemon_execution
from loom.pipeline import PipelineSpec
from loom.queue._managed_local import (
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    GpuResourceProvider,
    SQLiteAgentJournal,
    _configured_provider_descriptor,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import CpuResourcePlanner
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    AgentResourceProvider,
    ConfiguredGpuDevice,
    ExecutionRequirement,
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    prepare_managed_local_runtime_record,
)
from loom.queue._remote_stage_execution import (
    AgentResourceInventory,
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
    _RemoteExecutionReport,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _decode,
    _decode_run_inspection_response,
    _resident_provider_descriptors,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentProviderDescriptor,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSession,
    AgentTransferAuthorizationStaleError,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.serialization import PlainData, json_dumps_pretty
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.agent_sessions import (
    _shutdown_detached_remote_supervisors as _shutdown_detached_remote_supervisors,
    _execute_available_assignment,
    _failure_report,
    _fresh_remote_agent_root,
    _local_launch_profile,
    _nested_report_detail,
    _policy,
    _prepare_gpu_environment_run,
    _prepare_remote_producer_run,
    _slurm_bootstrap_profile,
    _sqlite_dump,
    native_control_endpoint as native_control_endpoint,
)
from tests.support.agent_gpu_occupancy import exercise_gpu_occupancy


@pytest.mark.parametrize(
    ("ceiling", "cpu", "memory_gib", "gpu", "expected"),
    [
        (1, 8, 8, False, 1),
        (2, 8, 8, False, 2),
        (6, 1, 8, False, 1),
        (6, 8, 1, False, 1),
        (6, 8, 8, True, 5),
    ],
)
def test_remote_candidate_ceiling_and_reflected_remaining_resources(
    tmp_path: Path, ceiling: int, cpu: int, memory_gib: int, gpu: bool, expected: int
) -> None:
    """Targeted work counts before grant; remaining reports are not charged twice."""
    descriptor = ResidentProfileDescriptor(
        "resident", "1", "project-1", "environment-1", "executor-1"
    )
    devices = (
        tuple(
            ResidentGpuDevice(
                GpuDeviceDescriptor(f"gpu-{index}", "model", 1024**3),
                f"GPU-private-{index}",
            )
            for index in range(4)
        )
        if gpu
        else ()
    )
    profile = ResidentExecutionProfile(
        descriptor,
        tmp_path,
        Path(sys.executable),
        cpu_capacity=cpu,
        memory_capacity_bytes=memory_gib * 1024**3,
        gpu_devices=devices,
    )
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "credential",
                "principal",
                "agent-a",
                ("default",),
                capabilities,
                gpu_devices=tuple(item.descriptor for item in devices),
            ),
        )
    )
    store = LocalRunStore(tmp_path / "runs")
    runs = [
        _prepare_remote_producer_run(
            store,
            run_name=f"run-{index}",
            machine_id="agent-a",
            value=index,
            requirement=ExecutionRequirement(
                "project-1", "environment-1", "executor-1"
            ),
            resource_entries={
                "cpu": {"kind": "cpu", "amount": 1, "unit": "count"},
                "memory": {"kind": "memory", "amount": 1024**3, "unit": "B"},
                **(
                    {
                        "gpu": {
                            "kind": "gpu",
                            "amount": 1,
                            "unit": "count",
                            "attributes": {"allocation_mode": "exclusive"},
                        }
                    }
                    if gpu and index < 5
                    else {}
                ),
            },
        )
        for index in range(6 if gpu else 3)
    ]
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        store.root,
        None,
        cpu_capacity=0,
        agent_policy=policy,
        remote_profiles=(descriptor,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        view = daemon.agent_view(
            LocalDaemonPrincipal("principal", LocalDaemonRole.AGENT, "credential")
        )
        hello = view.handshake()
        session = view.register(
            AgentRegistration(
                "register",
                str(hello["coordinator_id"]),
                str(hello["coordinator_epoch"]),
                "agent-root",
                "config",
                "inventory",
                "availability-0",
                ("default",),
                capabilities,
                retirement_verifier="01" * 32,
            )
        )
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        for index, (run_uri, _) in enumerate(runs):
            coordinator.submit(LocalDaemonAdmissionRequest(f"item-{index}", run_uri))
        execution = daemon._execution
        assert execution is not None
        claims = []
        claimed_devices = set()
        requests: list[dict[str, Any]] = []
        for index in range(expected + 1):
            offer = AgentOffer(
                session.session_id,
                session.coordinator_epoch,
                "config",
                "inventory",
                f"availability-{index}",
                cpu - len(claims),
                (memory_gib - len(claims)) * 1024**3,
                30,
                _resident_provider_descriptors(profile, "agent-a"),
                resident_profiles=(descriptor,),
                reflected_claim_ids=tuple(claims),
                max_concurrent_assignments=ceiling,
                gpu_devices=tuple(item.descriptor for item in devices),
                gpu_atoms=tuple(
                    item.descriptor.capacity_atom()
                    for item in devices
                    if item.descriptor.device_id not in claimed_devices
                ),
            )
            view.publish_offer(
                offer,
                idempotency_key=f"offer-{index}",
                expected_availability_revision=None
                if index == 0
                else f"availability-{index - 1}",
            )
            if len(claims) >= ceiling:
                assert execution._remote_candidates() == {}
            deadline = monotonic() + 5
            while True:
                daemon.reconcile_once()
                with sqlite3.connect(config.control_database) as conn:
                    requests = [
                        json.loads(row[0])
                        for row in conn.execute("SELECT request_json FROM agent_deliveries")
                    ]
                if len(requests) >= min(index + 1, expected):
                    break
                assert monotonic() < deadline, "asynchronous preparation did not dispatch"
                sleep(0.01)
            assert len(requests) == min(index + 1, expected)
            # A target absent from the current report withholds its whole candidate.
            if index < expected:
                assert execution._remote_candidates() == {}
                delivery = view.wait_for_work(
                    session.session_id,
                    offer.availability_revision,
                    sequence=index + 1,
                    wait_timeout_ms=1,
                )
                assert delivery["result"] == "assignment"
                request = next(
                    request for request in requests if request["claim_id"] not in claims
                )
                view.accept_assignment(
                    session.session_id,
                    request["assignment_id"],
                    request_digest=hashlib.sha256(
                        json.dumps(
                            request, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                )
            claims = [request["claim_id"] for request in requests]
            claimed_devices = {
                atom["local_capacity_key"].removeprefix("agent-a:")
                for request in requests
                for claim in request["claims"]
                if claim["resource_kind"] == "gpu"
                for atom in claim["atoms"]
            }
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM remote_assignments WHERE state != 'RELEASED'"
                ).fetchone()[0]
                == expected
            )
        if gpu:
            assert claimed_devices == {f"gpu-{index}" for index in range(4)}
            assert (
                sum(
                    any(claim["resource_kind"] == "gpu" for claim in request["claims"])
                    for request in requests
                )
                == 4
            )
    finally:
        daemon.stop()


@pytest.mark.parametrize("interruption", ["withdrawn_offer", "stale_decision", "lost_bind_reply"])
def test_rejected_remote_target_unbinds_attempt_and_releases_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    """Definite refusals and lost replies recover the exact pre-delivery reservation."""
    from loom.pipeline.stores.authority import PreparedBindingState
    from tests.unit.loom.queue.test_agent_sessions import _config, _policy, _view

    descriptor = ResidentProfileDescriptor(
        "resident", "1", "project-1", "environment-1", "executor-1"
    )
    profile = ResidentExecutionProfile(descriptor, tmp_path, Path(sys.executable))
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = _policy()
    policy = replace(
        policy, agents=(replace(policy.agents[0], capabilities=capabilities),)
    )
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_remote_producer_run(
        store,
        run_name="rejected",
        machine_id="agent-a",
        value=1,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    config = replace(_config(tmp_path, policy), remote_profiles=(descriptor,))
    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    rejected = []
    original_target = local_daemon_execution._target_remote_delivery

    def reject_target(*args, **kwargs):
        rejected.append(kwargs["request"])
        raise QueueConflictError("agent resident assignment ceiling is exhausted")

    if interruption == "withdrawn_offer":
        monkeypatch.setattr(local_daemon_execution, "_target_remote_delivery", reject_target)
    else:
        from loom.pipeline.reliability import ReliabilityPolicy
        from loom.pipeline.stores.read_models import ReliabilityPolicyFact, ReliabilityPolicyScope
        from loom.queue._managed_local import ManagedLocalError

        scoped = local_daemon_execution._ScopedCoordinatorAuthority
        original_bind = scoped.bind_prepared_attempt
        def interrupt_bind(owner, uri, **identity):
            if not rejected:
                rejected.append(identity)
                if interruption == "stale_decision":
                    authority.write_reliability_policy_fact(uri, ReliabilityPolicyFact(
                        run_uri=uri, scope=ReliabilityPolicyScope.RUN, policy=ReliabilityPolicy(),
                        recorded_at="2026-08-30T00:00:00Z",
                    ))
                else:
                    original_bind(owner, uri, **identity)
                    raise ManagedLocalError("authority bind reply lost")
            return original_bind(owner, uri, **identity)
        monkeypatch.setattr(scoped, "bind_prepared_attempt", interrupt_bind)
    try:
        view = _view(daemon)
        hello = view.handshake()
        session = view.register(
            AgentRegistration(
                "register",
                str(hello["coordinator_id"]),
                str(hello["coordinator_epoch"]),
                "agent-root",
                "config",
                "inventory",
                "availability",
                ("default",),
                capabilities,
                retirement_verifier="01" * 32,
            )
        )
        view.publish_offer(
            AgentOffer(
                session.session_id,
                session.coordinator_epoch,
                "config",
                "inventory",
                "availability",
                1,
                0,
                30,
                _resident_provider_descriptors(profile, "agent-a"),
                resident_profiles=(descriptor,),
                max_concurrent_assignments=2,
            ),
            idempotency_key="offer",
        )
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        admission = client.submit(LocalDaemonAdmissionRequest("item", run_uri))
        deadline = monotonic() + 5
        while not rejected:
            daemon.reconcile_once()
            assert monotonic() < deadline, "prepared target was not attempted"
            sleep(0.01)
        assert daemon._execution is not None
        if interruption == "withdrawn_offer":
            with sqlite3.connect(config.control_database) as conn:
                assert (
                    conn.execute("SELECT COUNT(*) FROM agent_deliveries").fetchone()[0] == 0
                )
                assert (
                    conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0]
                    == 0
                )
            for request in rejected:
                assert (
                    daemon._execution.coordinator.state(request.assignment_id) == "released"
                )
            from loom.pipeline.stores.sqlite_authority import _authority_database_path

            with sqlite3.connect(_authority_database_path(run_uri)) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM managed_attempt_bindings"
                    ).fetchone()[0]
                    == 0
                )
                assert conn.execute(
                    "SELECT COUNT(*) FROM managed_attempt_unbind_receipts"
                ).fetchone()[0] == len(rejected)
        else:
            identity = rejected[0]
            first_id = identity["assignment_id"]
            assert identity["expected_revision"] is not None
            if interruption == "stale_decision":
                assert daemon._execution.coordinator.state(first_id) == "released"
                assert authority.read_prepared_binding(
                    run_uri, assignment_id=first_id, attempt_id=identity["attempt_id"],
                ).state is PreparedBindingState.ABSENT
        committed = []

        def deliver_then_lose_reply(*args, **kwargs):
            original_target(*args, **kwargs)
            committed.append(kwargs["request"])
            raise QueueServiceError("lost committed target reply")

        if interruption == "withdrawn_offer":
            monkeypatch.setattr(local_daemon_execution, "_target_remote_delivery", deliver_then_lose_reply)
        deadline = monotonic() + 10
        while True:
            daemon.reconcile_once()
            with sqlite3.connect(config.control_database) as conn:
                row = conn.execute("SELECT assignment_id FROM remote_assignments").fetchone()
            if row is not None:
                break
            assert monotonic() < deadline, "reopened attempt did not receive a delivery"
            sleep(0.01)
        if interruption == "withdrawn_offer":
            [delivered] = committed
            assert client.admission(admission.admission_id).admission.state is LocalDaemonAdmissionState.ACTIVE
            assert row[0] == delivered.assignment_id
            assert daemon._execution.coordinator.state(delivered.assignment_id) == "bound"
            with sqlite3.connect(_authority_database_path(run_uri)) as conn:
                assert conn.execute("SELECT assignment_id, attempt_id FROM managed_attempt_bindings").fetchall() == [
                    (delivered.assignment_id, delivered.attempt_id),
                ]
            poll = view.wait_for_work(session.session_id, "availability", sequence=1, wait_timeout_ms=1)
            assert poll["result"] == "assignment"
            assert cast(Mapping[str, object], poll["request"])["assignment_id"] == delivered.assignment_id
        summaries = cast(list[dict], daemon._execution._scheduling_waits.summaries(run_uri))
        by_assignment = {item["assignment_id"]: item for item in summaries}
        first_id = rejected[0].assignment_id if interruption == "withdrawn_offer" else rejected[0]["assignment_id"]
        assert first_id != row[0]
        assert daemon._execution.coordinator.state(first_id) == "released"
        assert by_assignment[first_id]["projection_revision"] < by_assignment[row[0]]["projection_revision"]
        assert by_assignment[first_id]["attempt_id"] == by_assignment[row[0]]["attempt_id"]
        if interruption == "lost_bind_reply":
            assert authority.read_prepared_binding(
                run_uri, assignment_id=first_id, attempt_id=rejected[0]["attempt_id"],
            ).state is PreparedBindingState.UNBOUND
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    ("recovery", "ceiling"),
    [
        ("normal", 1),
        ("normal", 2),
        ("release_restart", 1),
        ("reconcile_before_accepted_replay", 1),
        ("reconcile_before_unaccepted_replay", 1),
        ("legacy_renewal", 1),
    ],
)
def test_repeated_capacity_release_publishes_fresh_offer(
    tmp_path, monkeypatch, recovery, ceiling
):
    """Identical restored capacity cannot renew a consumed offer after release."""
    credentials = _credentials(tmp_path / "tls")
    first_descriptor = ResidentProfileDescriptor(
        "resident-a", "revision-a", "project-a", "environment-a", "executor-a"
    )
    second_descriptor = ResidentProfileDescriptor(
        "resident-b", "revision-b", "project-b", "environment-b", "executor-b"
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
    prepared = [
        _prepare_remote_producer_run(
            runs, run_name=f"repeat-{index}", machine_id="agent-a", value=index,
            requirement=ExecutionRequirement("project-a", "environment-a", "executor-a"),
        ) for index in range(3)
    ]
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        runs.root,
        _local_launch_profile(),
        agent_policy=policy,
        remote_profiles=(first_descriptor, second_descriptor),
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
    project_root = Path(__file__).resolve().parents[3]
    profiles = (
        ResidentExecutionProfile(first_descriptor, project_root, Path(sys.executable)),
        ResidentExecutionProfile(second_descriptor, project_root, Path(sys.executable)),
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        profiles,
        max_concurrent_assignments=ceiling,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    from loom.queue.agent_session_transport import _RemoteAgentJournal

    try:
        hello = agent.handshake()
        session = agent.register(AgentRegistration(
            "register-repeat", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]),
            agent.agent_root_id, "config-1", "inventory-1", "availability-1",
            ("default",), capabilities,
        ))
        coordinator = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        completed = _RemoteAgentJournal.complete_assignment_release
        for index, (run_uri, authority) in enumerate(prepared):
            agent.refresh_resource_offer()
            with sqlite3.connect(config.control_database) as conn:
                wire = json.loads(
                    conn.execute(
                        "SELECT offer_json FROM agent_offers WHERE current = 1"
                    ).fetchone()[0]
                )
            assert wire.get("max_concurrent_assignments", 1) == ceiling
            assert ("max_concurrent_assignments" in wire) == (ceiling != 1)
            current = agent.active_session()
            assert current is not None
            coordinator.submit(LocalDaemonAdmissionRequest(f"repeat-{index}", run_uri))
            if index == 1 and recovery in {"release_restart", "legacy_renewal"}:
                def prior_release(journal, released, assignment_id):
                    if recovery == "release_restart":
                        raise RuntimeError("release acknowledgement interrupted")
                    # The pre-correction producer persisted release without fencing its offer.
                    journal.persist_reconciled_session(released)
                    journal.resolve_assignment_reference(released.session_id, assignment_id)
                monkeypatch.setattr(_RemoteAgentJournal, "complete_assignment_release", prior_release)
            def execute():
                assert current is not None
                return agent.execute_one(current.session_id, current.availability_revision,
                    sequence=agent.next_poll_sequence(current.session_id), wait_timeout_ms=5000)
            if index == 1 and recovery.startswith("reconcile_before_"):
                exchange = agent_session_transport._exchange_agent_request
                attempts = []
                accepted = recovery == "reconcile_before_accepted_replay"

                def interrupt_once(config, operation, body, *args, **kwargs):
                    if operation != "release":
                        return exchange(config, operation, body, *args, **kwargs)
                    proof = json.loads(body)["provider_release_proof"]
                    del proof["retirement_secret"]
                    if not attempts and not accepted:
                        attempts.append(proof)
                        raise RuntimeError("interrupted release")
                    try:
                        result = exchange(config, operation, body, *args, **kwargs)
                    except agent_session_transport._AgentReleaseEpochRejected:
                        attempts.append(proof)
                        raise
                    attempts.append(proof)
                    if len(attempts) == 1:
                        result.connection.close()
                        raise RuntimeError("interrupted release")
                    return result

                with monkeypatch.context() as patch:
                    patch.setattr(agent_session_transport, "_exchange_agent_request", interrupt_once)
                    with pytest.raises(RuntimeError, match="interrupted release"):
                        execute()
                    agent.close()
                    daemon.stop()
                    daemon.start()
                    agent = LocalDaemonAgentHttpClient(remote_config)
                    epoch = str(agent.handshake()["coordinator_epoch"])
                    assert epoch != current.coordinator_epoch
                    # The service negotiates the exact pre/post-release availability
                    # from the durable execution journal during epoch reconciliation.
                    agent._service_progress = True
                    agent.reconcile(current.session_id, epoch, idempotency_key=f"while-release:{epoch}")
                    agent._service_progress = False
                    assert agent.resume_retained_work()[0]["state"] == "RELEASED"
                    assert attempts[1] == attempts[0]
                    if accepted:
                        assert len(attempts) == 2
                    else:
                        assert attempts[2:] == [{**attempts[0], "coordinator_epoch": epoch}]
                    recovered = agent.active_session()
                    assert recovered is not None
                    assert recovered.coordinator_epoch == epoch
                    assert recovered.availability_revision == attempts[0]["released_availability_revision"]
                    assert agent._require_journal().next_offer_renewal(current.session_id) is None
                    with sqlite3.connect(config.control_database) as conn:
                        stored = conn.execute("SELECT state, provider_release_proof_json FROM remote_assignments "
                                              "WHERE assignment_id=?", (attempts[0]["assignment_id"],)).fetchone()
                    assert stored[0] == "RELEASED" and json.loads(stored[1]) == attempts[-1]
            elif index == 1 and recovery == "release_restart":
                with pytest.raises(RuntimeError, match="acknowledgement interrupted"):
                    execute()
                monkeypatch.setattr(_RemoteAgentJournal, "complete_assignment_release", completed)
                agent.close()
                daemon.stop()
                daemon.start()
                agent = LocalDaemonAgentHttpClient(remote_config)
                # Match outbound startup: settle retained cleanup first, then
                # handshake/reconcile the session before publishing fresh capacity.
                assert agent.resume_retained_work()[0]["state"] == "RELEASED"
                recovered = agent.active_session()
                assert recovered is not None
                epoch = str(agent.handshake()["coordinator_epoch"])
                assert epoch != current.coordinator_epoch
                recovered = agent.reconcile(recovered.session_id, epoch,
                    idempotency_key=f"release-restart:{epoch}")
                assert recovered.coordinator_epoch == epoch
            else:
                assert execute()["state"] == "RELEASED"
            if index == 1 and recovery == "legacy_renewal":
                monkeypatch.setattr(_RemoteAgentJournal, "complete_assignment_release", completed)
                with pytest.raises(QueueConflictError):
                    agent.refresh_resource_offer()
                assert agent._require_journal().pending_resource_mutation(current.session_id) is not None
                agent.close()
                agent = LocalDaemonAgentHttpClient(remote_config)
                assert agent.resume_retained_work() == ()
                # Reconciliation resolves the definite renewal rejection before republishing.
                agent.refresh_resource_offer()
            assert coordinator.wait(f"repeat-{index}", timeout_seconds=10).state is LocalDaemonAdmissionState.SUCCEEDED
            assert authority.open_run(run_uri).status is RunStatus.SUCCEEDED
            # Service reconnect reconstructs idle providers. Their availability
            # revision may repeat; these are supported observations, not forged IDs.
            agent.close()
            agent = LocalDaemonAgentHttpClient(remote_config)
            assert agent.resume_retained_work() == ()
        with sqlite3.connect(config.control_database) as conn:
            release_revisions = [row[0] for row in conn.execute("SELECT next_availability_revision FROM remote_assignments")]
            assert len(release_revisions) == 3 and len(set(release_revisions)) == 1
            assert conn.execute("SELECT COUNT(*) FROM remote_assignments WHERE state = 'RELEASED'").fetchone()[0] == 3
        assert not agent._require_journal().unresolved_assignment_references()
        assert agent._require_journal().next_offer_renewal(session.session_id) is None
        agent.refresh_resource_offer()
        with sqlite3.connect(config.control_database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM agent_offers WHERE current = 1").fetchone()[0] == 1
        # Replaying an acknowledged old release cannot consume the new offer.
        last = agent.active_session()
        assert last is not None
        with sqlite3.connect(config.control_database) as conn:
            assignment_id = conn.execute("SELECT assignment_id FROM remote_assignments LIMIT 1").fetchone()[0]
        agent._require_journal().complete_assignment_release(last, assignment_id)
        assert agent._require_journal().next_offer_renewal(session.session_id) is not None
        with sqlite3.connect(cast(Path, remote_config.agent_root) / "supervisor" / "supervisor.sqlite") as conn:
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 3
    finally:
        assert agent._supervisor is not None
        agent._supervisor.shutdown_for_test()
        agent.close()
        server.stop()
        daemon.stop()


def test_one_supervisor_routes_selected_work_through_two_bound_profiles(
    tmp_path: Path,
) -> None:
    """Each supported advertised profile reaches its exact durable launch."""

    credentials = _credentials(tmp_path / "tls")
    first_descriptor = ResidentProfileDescriptor(
        "resident-a", "revision-a", "project-a", "environment-a", "executor-a"
    )
    second_descriptor = ResidentProfileDescriptor(
        "resident-b", "revision-b", "project-b", "environment-b", "executor-b"
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
    first_run, first_authority = _prepare_remote_producer_run(
        runs,
        run_name="profile-a-run",
        machine_id="agent-a",
        value=1,
        requirement=ExecutionRequirement("project-a", "environment-a", "executor-a"),
    )
    second_run, second_authority = _prepare_remote_producer_run(
        runs,
        run_name="profile-b-run",
        machine_id="agent-a",
        value=2,
        requirement=ExecutionRequirement("project-b", "environment-b", "executor-b"),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        runs.root,
        _local_launch_profile(),
        agent_policy=policy,
        remote_profiles=(first_descriptor, second_descriptor),
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
    project_root = Path(__file__).resolve().parents[3]
    profiles = (
        ResidentExecutionProfile(first_descriptor, project_root, Path(sys.executable)),
        ResidentExecutionProfile(second_descriptor, project_root, Path(sys.executable)),
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path),
        profiles,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-two-profiles",
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
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )

        def execute_selected(
            profile: ResidentExecutionProfile, run_uri: str, suffix: str
        ) -> None:
            current = agent._require_journal().session(session.session_id)  # noqa: SLF001
            agent.publish_offer(
                AgentOffer(
                    current.session_id,
                    current.coordinator_epoch,
                    current.config_revision,
                    current.inventory_revision,
                    current.availability_revision,
                    1,
                    0,
                    30,
                    _resident_provider_descriptors(profile, current.agent_id),
                    resident_profiles=(profile.descriptor,),
                ),
                idempotency_key=f"offer-{suffix}",
            )
            with ThreadPoolExecutor(max_workers=1) as workers:
                execution = workers.submit(
                    agent.execute_one,
                    current.session_id,
                    current.availability_revision,
                    sequence=1 if suffix == "a" else 2,
                    wait_timeout_ms=5_000,
                )
                coordinator.submit(
                    LocalDaemonAdmissionRequest(f"item-{suffix}", run_uri)
                )
                assert execution.result(timeout=20)["state"] == "RELEASED"
            assert (
                coordinator.wait(f"item-{suffix}", timeout_seconds=10).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )

        execute_selected(profiles[0], first_run, "a")
        execute_selected(profiles[1], second_run, "b")
        assert first_authority.open_run(first_run).status is RunStatus.SUCCEEDED
        assert second_authority.open_run(second_run).status is RunStatus.SUCCEEDED
        agent_root = cast(Path, remote_config.agent_root)
        with sqlite3.connect(agent_root / "supervisor" / "supervisor.sqlite") as conn:
            rows = tuple(
                conn.execute("SELECT launch_json FROM launches ORDER BY operation_id")
            )
        launches = tuple(json.loads(str(row[0])) for row in rows)
        from loom.queue._agent_process_supervisor import _launch_from_value

        routed = {
            launch.profile.profile_id: launch.profile.fingerprint
            for launch in map(_launch_from_value, launches)
        }
        assert routed == {
            profile.descriptor.profile_id: profile.launch_profile.fingerprint
            for profile in profiles
        }
    finally:
        assert agent._supervisor is not None  # noqa: SLF001
        agent._supervisor.shutdown_for_test()  # noqa: SLF001
        agent.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize(
    ("account_for", "sequential"), [("all", False), ([], False), ([], True)]
)
def test_two_remote_agents_execute_two_globally_selected_runs(
    tmp_path: Path,
    account_for: str | list[str],
    sequential: bool,
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
                "credential-a", "principal-a", "agent-a", ("default",), capabilities
            ),
            AgentPrincipalPolicy(
                "credential-b", "principal-b", "agent-b", ("default",), capabilities
            ),
        )
    )
    run_root = tmp_path / "runs"
    store = LocalRunStore(run_root)
    run_a, authority_a = _prepare_remote_producer_run(
        store,
        run_name="remote-a",
        account_for=account_for,
        sequential=sequential,
        machine_id="agent-a",
        value=1,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    run_b, authority_b = _prepare_remote_producer_run(
        store,
        run_name="remote-b",
        account_for=account_for,
        sequential=sequential,
        machine_id="agent-b",
        value=2,
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        run_root,
        _local_launch_profile(),
        cpu_capacity=2,
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
                _fingerprint(credentials["agent"].with_suffix(".crt")): (
                    "credential-a"
                ),
                _fingerprint(credentials["other"].with_suffix(".crt")): (
                    "credential-b"
                ),
            },
        ),
    )
    server.start()
    project_root = Path(__file__).resolve().parents[3]
    profile = ResidentExecutionProfile(
        descriptor,
        project_root,
        Path(sys.executable),
    )
    remote_a_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path, "remote-owner-a"),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_a_config)
    agent_a = LocalDaemonAgentHttpClient(remote_a_config)
    remote_b_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["other"].with_suffix(".crt"),
        credentials["other"].with_suffix(".key"),
        _fresh_remote_agent_root(tmp_path, "remote-owner-b"),
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_b_config)
    agent_b = LocalDaemonAgentHttpClient(remote_b_config)

    def register(client: LocalDaemonAgentHttpClient, suffix: str):
        handshake = client.handshake()
        session = client.register(
            AgentRegistration(
                f"register-{suffix}",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                client.agent_root_id,
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            )
        )
        client.publish_offer(
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
            idempotency_key=f"offer-{suffix}",
        )
        return session

    def execute_pipeline(client: LocalDaemonAgentHttpClient, session: AgentSession):
        from loom.queue.agent_sessions import _session_from_value

        results = []
        for sequence in range(1, 3 if sequential else 2):
            if sequence > 1:
                client.publish_offer(
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
                    idempotency_key=f"followup-{session.session_id}",
                )
            result = client.execute_one(
                session.session_id,
                session.availability_revision,
                sequence=sequence,
                wait_timeout_ms=5_000,
            )
            assert result["state"] == "RELEASED", result
            results.append(result)
            session = _session_from_value(
                cast(Mapping[str, PlainData], result["session"])
            )
        return results

    try:
        session_a = register(agent_a, "a")
        session_b = register(agent_b, "b")
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            execution_a = workers.submit(
                execute_pipeline,
                agent_a,
                session_a,
            )
            execution_b = workers.submit(
                execute_pipeline,
                agent_b,
                session_b,
            )
            coordinator.submit(LocalDaemonAdmissionRequest("item-a", run_a))
            coordinator.submit(LocalDaemonAdmissionRequest("item-b", run_b))
            result_a = execution_a.result(timeout=30)
            result_b = execution_b.result(timeout=30)
        completed_a = coordinator.wait("item-a", timeout_seconds=10)
        completed_b = coordinator.wait("item-b", timeout_seconds=10)

        assert len(result_a) == len(result_b) == (2 if sequential else 1)
        assert completed_a.state is LocalDaemonAdmissionState.SUCCEEDED
        assert completed_b.state is LocalDaemonAdmissionState.SUCCEEDED
        for snapshot in (authority_a.open_run(run_a), authority_b.open_run(run_b)):
            assert snapshot.status is RunStatus.SUCCEEDED
            assert len(snapshot.stages) == (2 if sequential else 1)
            for stage in snapshot.stages:
                assert stage.status is StageStatus.SUCCEEDED
                output = stage.artifact_facts[0].artifact
                assert Path(output.uri.removeprefix("file://")).is_file()
        with sqlite3.connect(config.execution_database) as conn:
            assignments = tuple(
                conn.execute(
                    "SELECT agent_id, state FROM coordinator_assignments "
                    "ORDER BY agent_id"
                )
            )
            if account_for == []:
                assert (
                    conn.execute("SELECT COUNT(*) FROM coordinator_atoms").fetchone()[0]
                    == 0
                )
        assert assignments == tuple(
            (agent_id, "released")
            for agent_id in ("agent-a", "agent-b")
            for _ in range(2 if sequential else 1)
        )
    finally:
        agent_a.close()
        agent_b.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("scenario", [
    "execution", "cancel-pregrant", "restart-before-coordinator-release",
    "slow-local-observation", "lost-committed-grant", "cancel-before-bind", "restart-after-committed-bind",
])
def test_same_run_local_and_remote_stages_overlap(tmp_path: Path, monkeypatch, scenario: str) -> None:
    slow_offer = scenario == "slow-local-observation"
    cancel_pregrant = scenario not in {"execution", "slow-local-observation"}
    binding_pause = scenario in {"cancel-before-bind", "restart-after-committed-bind"}
    expects_abort = cancel_pregrant and not binding_pause and scenario != "lost-committed-grant"
    bound_identity = {}
    unbind_attempted = Event()
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
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_mixed_local_remote_sleep_run(store)
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        store.root,
        _local_launch_profile(),
        cpu_capacity=1,
        agent_policy=policy,
        remote_profiles=(descriptor,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    grant_entered, allow_grant = Event(), Event()
    abort_entered, allow_abort = Event(), Event()
    offer_entered, allow_offer = Event(), Event()
    if slow_offer:
        observe = AtomResourceProvider.observe

        def pause_provider(provider, request):
            if request.operation_id.startswith("candidate-observe-") and request.agent_id == config.machine_id:
                offer_entered.set()
                assert allow_offer.wait(25)
            return observe(provider, request)

        monkeypatch.setattr(AtomResourceProvider, "observe", pause_provider)
    scoped = local_daemon_execution._ScopedCoordinatorAuthority
    unbind = scoped.unbind_prepared_attempt
    if cancel_pregrant:
        from threading import current_thread
        bind = scoped.bind_prepared_attempt
        grant = scoped.grant_prepared_attempt
        abort = AtomResourceProvider.abort

        def hold_local_grant(owner, uri, **kwargs):
            if current_thread().name.startswith("loom-local-assignment") and not grant_entered.is_set():
                if scenario == "lost-committed-grant":
                    grant(owner, uri, **kwargs)
                grant_entered.set()
                assert allow_grant.wait(40)
                if scenario == "lost-committed-grant":
                    raise OSError("authority committed the local grant before the reply was lost")
            return grant(owner, uri, **kwargs)

        def hold_abort(provider, command):
            if command.assignment.agent_id == config.machine_id:
                abort_entered.set()
                assert allow_abort.wait(40)
            return abort(provider, command)

        if binding_pause:
            def hold_local_binding(owner, uri, **kwargs):
                if current_thread().name.startswith("loom-local-assignment") and not grant_entered.is_set():
                    bound_identity.update((name, kwargs[name]) for name in ("assignment_id", "attempt_id"))
                    if scenario == "restart-after-committed-bind":
                        bind(owner, uri, **kwargs)
                    grant_entered.set()
                    assert allow_grant.wait(40)
                    if scenario == "restart-after-committed-bind":
                        raise OSError("authority committed the local bind before the reply was lost")
                return bind(owner, uri, **kwargs)

            def interrupt_unbind(owner, uri, **kwargs):
                if scenario == "restart-after-committed-bind" and kwargs == bound_identity:
                    unbind_attempted.set()
                    raise OSError("authority unavailable until restart")
                return unbind(owner, uri, **kwargs)

            monkeypatch.setattr(scoped, "bind_prepared_attempt", hold_local_binding)
            monkeypatch.setattr(scoped, "unbind_prepared_attempt", interrupt_unbind)
        else:
            monkeypatch.setattr(scoped, "grant_prepared_attempt", hold_local_grant)
        monkeypatch.setattr(AtomResourceProvider, "abort", hold_abort)
    daemon.start()
    release_attempted = Event()
    if scenario == "restart-before-coordinator-release":
        def interrupt_release(assignment_id):
            release_attempted.set()
            raise OSError("execution-store release unavailable until restart")

        execution = daemon._execution
        assert execution is not None
        monkeypatch.setattr(execution.coordinator, "cancellation_release_pregrant", interrupt_release)
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
    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-mixed-run",
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
            idempotency_key="offer-mixed-run",
        )
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        if expects_abort:
            call = agent._call

            def wait_for_local_abort(operation, payload, **kwargs):
                response = call(operation, payload, **kwargs)
                if operation == "assignment_control" and response.get("control") is not None:
                    assert abort_entered.wait(30)
                return response

            monkeypatch.setattr(agent, "_call", wait_for_local_abort)
        with ThreadPoolExecutor(max_workers=2) as workers:
            remote = workers.submit(
                _execute_available_assignment,
                agent,
                session.session_id,
                session.availability_revision,
            )
            coordinator.submit(LocalDaemonAdmissionRequest("mixed-item", run_uri))
            deadline = monotonic() + 30
            active_agent_ids: set[str] = set()
            while monotonic() < deadline:
                with sqlite3.connect(config.execution_database) as conn:
                    active_agent_ids = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT agent_id FROM coordinator_assignments "
                            "WHERE run_uri = ? AND state IN "
                            "('reserved','bound','accepted','granted','running','unknown')",
                            (run_uri,),
                        )
                    }
                    if slow_offer and offer_entered.is_set() and not allow_offer.is_set():
                        remote_running = conn.execute(
                            "SELECT 1 FROM coordinator_assignments WHERE run_uri=? AND agent_id='agent-a' AND state='running'",
                            (run_uri,),
                        ).fetchone()
                        if remote_running is not None:
                            assert active_agent_ids == {"agent-a"}
                            allow_offer.set()
                if active_agent_ids == {"machine-A", "agent-a"}:
                    break
                sleep(0.01)
            if slow_offer:
                assert offer_entered.is_set() and allow_offer.is_set()
            assert active_agent_ids == {"machine-A", "agent-a"}
            if cancel_pregrant:
                try:
                    assert grant_entered.wait(10)
                    with sqlite3.connect(config.control_database) as conn:
                        deadline = monotonic() + 20
                        while monotonic() < deadline and not conn.execute(
                            "SELECT 1 FROM remote_assignments WHERE run_uri=? AND state='RUNNING'", (run_uri,)
                        ).fetchone():
                            sleep(0.01)
                        assert conn.execute("SELECT 1 FROM remote_assignments WHERE run_uri=? AND state='RUNNING'", (run_uri,)).fetchone()
                    coordinator.cancel("mixed-item")
                    with sqlite3.connect(config.control_database) as conn:
                        deadline = monotonic() + 15
                        while monotonic() < deadline and not conn.execute("SELECT 1 FROM remote_assignment_controls").fetchone():
                            sleep(0.01)
                        assert conn.execute("SELECT COUNT(*) FROM remote_assignment_controls").fetchone() == (1,)
                    if binding_pause:
                        assert remote.result(timeout=20).get("state") == "RELEASED"
                        assert coordinator.cancel("mixed-item").state is LocalDaemonAdmissionState.CANCELLING
                        with sqlite3.connect(config.agent_journal) as conn:
                            assert conn.execute("SELECT COUNT(*) FROM assignments").fetchone() == (0,)
                    allow_grant.set()
                    if expects_abort:
                        assert abort_entered.wait(20)
                        assert remote.result(timeout=20).get("state") == "RELEASED"
                        workers.submit(daemon.reconcile_once).result(timeout=5)
                        # The pending diagnostic is part of current progress.
                        # Repeating the public control must preserve it and its revision.
                        settling = coordinator.cancel("mixed-item")
                        assert settling.state is LocalDaemonAdmissionState.CANCELLING
                        assert settling.blocked_reason
                        assert coordinator.cancel("mixed-item") == settling
                        with pytest.raises(TimeoutError):
                            coordinator.wait("mixed-item", timeout_seconds=0.1)
                        assert authority.open_run(run_uri).status is RunStatus.RUNNING
                finally:
                    allow_grant.set()
                    allow_abort.set()
            result = remote.result(timeout=90)
            assert result.get("state") == "RELEASED", result
        if scenario == "restart-before-coordinator-release":
            assert release_attempted.wait(10)
            with sqlite3.connect(config.agent_journal) as conn:
                assert conn.execute(
                    "SELECT state, declined, grant_fence, process_execution_id FROM assignments"
                ).fetchall() == [("released", 1, None, None)]
            with sqlite3.connect(config.execution_database) as conn:
                assert conn.execute(
                    "SELECT state FROM coordinator_assignments WHERE agent_id=?", (config.machine_id,)
                ).fetchone() == ("accepted",)
        if scenario == "restart-after-committed-bind":
            assert unbind_attempted.wait(20)
            with sqlite3.connect(config.execution_database) as conn:
                assert conn.execute(
                    "SELECT state FROM coordinator_assignments WHERE assignment_id=?",
                    (bound_identity["assignment_id"],),
                ).fetchone() == ("reserved",)
        if scenario in {"restart-before-coordinator-release", "restart-after-committed-bind"}:
            daemon.stop()
            if scenario == "restart-after-committed-bind":
                monkeypatch.setattr(scoped, "unbind_prepared_attempt", unbind)
            daemon = LocalDaemon(config)
            daemon.start()
            coordinator = daemon.client_view(LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT))
        assert coordinator.wait("mixed-item", timeout_seconds=90).state is (
            LocalDaemonAdmissionState.CANCELLED if cancel_pregrant else LocalDaemonAdmissionState.SUCCEEDED
        )
        assert authority.open_run(run_uri).status is (RunStatus.CANCELLED if cancel_pregrant else RunStatus.SUCCEEDED)
        if scenario == "lost-committed-grant":
            assert not abort_entered.is_set()
            with sqlite3.connect(config.agent_journal) as conn:
                assert conn.execute(
                    "SELECT state, grant_fence IS NOT NULL, process_execution_id FROM assignments"
                ).fetchall() == [("released", 1, None)]
        if binding_pause:
            authority.bind_prepared_attempt(run_uri, **bound_identity)
            with pytest.raises(ValueError, match="not bound"):
                authority.grant_prepared_attempt(run_uri, **bound_identity)
            with sqlite3.connect(config.agent_journal) as conn:
                assert conn.execute("SELECT COUNT(*) FROM assignments").fetchone() == (0,)
        if cancel_pregrant:
            with sqlite3.connect(config.execution_database) as conn:
                assert conn.execute(
                    "SELECT state FROM coordinator_assignments WHERE run_uri=?", (run_uri,)
                ).fetchall() == [("released",), ("released",)]
    finally:
        allow_offer.set()
        allow_grant.set()
        allow_abort.set()
        agent.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("enforce_gpu", [False, True])
def test_gpu_model_preference_selects_exact_private_local_or_remote_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enforce_gpu: bool,
) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    credentials = _credentials(tmp_path / "tls")
    profile_descriptor = ResidentProfileDescriptor(
        "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
    )
    local_gpu = GpuDeviceDescriptor("local-safe", "small", 80 * 1024**3)
    remote_gpu = GpuDeviceDescriptor("remote-safe", "large", 80 * 1024**3)
    remote_busy_gpu = GpuDeviceDescriptor("remote-busy", "large", 80 * 1024**3)
    local_binding = "local-private-binding"
    remote_binding = "remote-private-binding"
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "credential-a",
                "principal-a",
                "agent-a",
                ("default",),
                capabilities,
                (remote_busy_gpu, remote_gpu),
            ),
        )
    )
    run_root = tmp_path / "runs"
    store = LocalRunStore(run_root)
    remote_run, remote_authority = _prepare_gpu_environment_run(
        store,
        run_name="remote-model-preferred",
        enforce_gpu=enforce_gpu,
        preferred_models=("large", "small"),
        include_cpu_preprocess=True,
        capture_requirement=ExecutionRequirement(
            "project-1", "environment-1", "executor-1"
        ),
    )
    local_run, local_authority = _prepare_gpu_environment_run(
        store,
        run_name="local-model-preferred",
        enforce_gpu=enforce_gpu,
        preferred_models=("small", "large"),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        run_root,
        _local_launch_profile(),
        machine_id="machine-A",
        gpu_devices=(ConfiguredGpuDevice(local_gpu, local_binding),),
        agent_policy=policy,
        remote_profiles=(profile_descriptor,),
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
            {_fingerprint(credentials["agent"].with_suffix(".crt")): ("credential-a")},
        ),
    )
    server.start()
    remote_root = _fresh_remote_agent_root(tmp_path)
    profile = ResidentExecutionProfile(
        profile_descriptor,
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
        gpu_devices=(
            ResidentGpuDevice(remote_busy_gpu, "remote-busy-private-binding"),
            ResidentGpuDevice(remote_gpu, remote_binding),
        ),
    )
    provider_members: dict[str, tuple[AgentResourceProvider, ...]] = {}

    def provider_factory(
        agent_id: str, resident_profile: ResidentExecutionProfile | AgentResourceInventory
    ) -> tuple[AgentResourceProvider, ...]:
        configured = provider_members.get(agent_id)
        if configured is not None:
            return configured
        cpu_planner = CpuResourcePlanner()
        cpu_atoms = tuple(
            atom
            for atom in resident_profile.capacity_atoms(agent_id)
            if atom.owner_resource_kind == "cpu"
        )
        gpu_planner = GpuResourcePlanner()
        gpu_atom = remote_gpu.capacity_atom(f"{agent_id}:{remote_gpu.device_id}")
        configured = (
            AtomResourceProvider(
                _configured_provider_descriptor("cpu", cpu_atoms),
                cpu_planner.claim_contracts,
                cpu_atoms,
            ),
            GpuResourceProvider(
                gpu_planner.claim_contracts,
                (gpu_atom,),
                bindings={gpu_atom.local_capacity_key: remote_binding},
            ),
        )
        provider_members[agent_id] = configured
        return configured

    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        remote_root,
        (profile,),
        agent_resource_provider_factory=provider_factory,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    released_claims: list[tuple[str, str, tuple[str, ...], str]] = []
    original_release = GpuResourceProvider.release

    def record_release(
        provider: GpuResourceProvider, command: ClaimCommand
    ) -> ClaimResult:
        released_claims.append(
            (
                command.assignment.agent_id,
                command.claim.fingerprint,
                tuple(atom.local_capacity_key for atom in command.claim.atoms),
                command.provider_descriptor.configuration_fingerprint,
            )
        )
        return original_release(provider, command)

    monkeypatch.setattr(GpuResourceProvider, "release", record_release)

    def offer_for(session_value: Mapping[str, object]) -> AgentOffer:
        members = provider_factory(str(session_value["agent_id"]), profile)
        return AgentOffer(
            str(session_value["session_id"]),
            str(session_value["coordinator_epoch"]),
            str(session_value["config_revision"]),
            str(session_value["inventory_revision"]),
            str(session_value["availability_revision"]),
            1,
            0,
            30,
            tuple(
                AgentProviderDescriptor(member.descriptor, member.claim_contracts)
                for member in members
            ),
            resident_profiles=(profile_descriptor,),
            gpu_devices=(remote_busy_gpu, remote_gpu),
            # The first configured device is externally occupied. Inventory
            # remains complete while only the manageable device is available.
            gpu_atoms=(remote_gpu.capacity_atom(),),
        )

    try:
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-gpu-1",
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
        agent.publish_offer(offer_for(session.value()), idempotency_key="offer-gpu-1")
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )

        coordinator.submit(LocalDaemonAdmissionRequest("gpu-remote-item", remote_run))
        deadline = monotonic() + 5
        while monotonic() < deadline:
            preprocess = next(
                (
                    stage
                    for stage in remote_authority.open_run(remote_run).stages
                    if stage.stage_name == "preprocess"
                ),
                None,
            )
            if preprocess is None:
                sleep(0.01)
                continue
            if preprocess.status is StageStatus.SUCCEEDED:
                break
            if preprocess.status in {StageStatus.FAILED, StageStatus.CANCELLED}:
                pytest.fail(f"CPU preprocess terminated as {preprocess.status.value}")
            sleep(0.01)
        else:
            pytest.fail("CPU preprocess did not complete")
        with ThreadPoolExecutor(max_workers=1) as workers:
            remote_execution = workers.submit(
                agent.execute_one,
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=5_000,
            )
            remote_result = remote_execution.result(timeout=20)
        remote_completed = coordinator.wait("gpu-remote-item", timeout_seconds=10)
        assert remote_result["state"] == "RELEASED"
        assert remote_completed.state is LocalDaemonAdmissionState.SUCCEEDED

        next_session = cast(Mapping[str, object], remote_result["session"])
        agent.publish_offer(offer_for(next_session), idempotency_key="offer-gpu-2")
        coordinator.submit(LocalDaemonAdmissionRequest("gpu-local-item", local_run))
        local_completed = coordinator.wait("gpu-local-item", timeout_seconds=10)
        assert local_completed.state is LocalDaemonAdmissionState.SUCCEEDED

        remote_snapshot = remote_authority.open_run(remote_run)
        local_snapshot = local_authority.open_run(local_run)
        assert all(
            stage.status is StageStatus.SUCCEEDED for stage in remote_snapshot.stages
        )
        assert local_snapshot.stages[0].status is StageStatus.SUCCEEDED
        remote_capture = next(
            stage for stage in remote_snapshot.stages if stage.stage_name == "capture"
        )
        remote_preprocess = next(
            stage
            for stage in remote_snapshot.stages
            if stage.stage_name == "preprocess"
        )
        remote_output = cast(
            Mapping[str, object],
            LocalArtifactStore(store.local_artifact_root(remote_run)).load(
                remote_capture.artifact_facts[0].artifact
            ),
        )
        preprocess_output = cast(
            Mapping[str, object],
            LocalArtifactStore(store.local_artifact_root(remote_run)).load(
                remote_preprocess.artifact_facts[0].artifact
            ),
        )
        local_output = cast(
            Mapping[str, object],
            LocalArtifactStore(store.local_artifact_root(local_run)).load(
                local_snapshot.stages[0].artifact_facts[0].artifact
            ),
        )
        assert remote_output["value"] == (remote_binding if enforce_gpu else None)
        assert local_output["value"] == (local_binding if enforce_gpu else None)
        assert preprocess_output["value"] is None
        assert preprocess_output["pid"] != os.getpid()
        assert remote_output["pid"] != os.getpid()
        assert local_output["pid"] != os.getpid()

        for run_uri in (remote_run, local_run):
            result = store.read_stage_worker_result(run_uri, "capture", attempt=1)
            assert result is not None
            metadata = result["executor_metadata"]
            assert isinstance(metadata, dict)
            controls = metadata["resource_controls"]
            assert isinstance(controls, list)
            assert {
                "resource": "gpu",
                "owner": "managed_provider",
                "mechanism": "provider_environment_binding" if enforce_gpu else None,
                "disposition": "applied" if enforce_gpu else "not_requested",
            } in controls
            assert local_binding not in json.dumps(controls)
            assert remote_binding not in json.dumps(controls)

        with sqlite3.connect(config.execution_database) as conn:
            assignments = set(
                conn.execute(
                    "SELECT a.run_uri, w.stage_name, a.agent_id "
                    "FROM coordinator_assignments a "
                    "JOIN stage_work w ON w.stage_work_id = a.stage_work_id "
                    "WHERE a.run_uri IN (?, ?)",
                    (remote_run, local_run),
                )
            )
            remote_assignment_id, receipt_json = cast(
                tuple[str, str],
                conn.execute(
                    "SELECT a.assignment_id, a.receipt_json "
                    "FROM coordinator_assignments a "
                    "JOIN stage_work w ON w.stage_work_id = a.stage_work_id "
                    "WHERE a.run_uri = ? AND w.stage_name = 'capture'",
                    (remote_run,),
                ).fetchone(),
            )
        assert assignments == {
            (remote_run, "preprocess", "machine-A"),
            (remote_run, "capture", "agent-a"),
            (local_run, "capture", "machine-A"),
        }

        with sqlite3.connect(remote_root / "journal.sqlite") as conn:
            state, claims_json = cast(
                tuple[str, str],
                conn.execute(
                    "SELECT state, claims_json FROM assignments ORDER BY assignment_id"
                ).fetchone(),
            )
        assert state == "released"
        claims_value = cast(dict[str, object], json.loads(claims_json))
        commands = cast(list[dict[str, object]], claims_value["commands"])
        gpu_command = next(item for item in commands if item["resource_kind"] == "gpu")
        assert (
            cast(list[dict[str, object]], gpu_command["atoms"])[0]["local_capacity_key"]
            == "agent-a:remote-safe"
        )
        remote_release = next(item for item in released_claims if item[0] == "agent-a")
        assert gpu_command["claim_fingerprint"] == remote_release[1]
        assert remote_release[2] == ("agent-a:remote-safe",)
        receipt = cast(dict[str, object], json.loads(receipt_json))
        receipt_provider = next(
            item
            for item in cast(list[dict[str, object]], receipt["provider_descriptors"])
            if item["kind"] == "gpu"
        )
        receipt_planner = next(
            item
            for item in cast(list[dict[str, object]], receipt["component_descriptors"])
            if item["kind"] == "gpu"
        )
        with sqlite3.connect(
            remote_root / "assignments" / remote_assignment_id / "resident.sqlite"
        ) as conn:
            delivered = cast(
                dict[str, object],
                json.loads(
                    cast(
                        str,
                        conn.execute(
                            "SELECT value_json FROM request WHERE singleton = 1"
                        ).fetchone()[0],
                    )
                ),
            )
        delivered_provider = next(
            item
            for item in cast(list[dict[str, object]], delivered["provider_descriptors"])
            if item["kind"] == "gpu"
        )
        assert receipt_provider != receipt_planner
        assert delivered_provider == receipt_provider
        assert gpu_command["provider_descriptor"] == receipt_provider
        assert remote_release[3] == receipt_provider["configuration_fingerprint"]
        assert remote_binding not in claims_json
        assert "remote-busy-private-binding" not in claims_json

        retained = SQLiteAgentJournal(
            remote_root / "journal.sqlite", _allow_initialize=False
        )
        retained._open_existing()
        assert retained.retained_claim_commands() == ()
        protected_dump = "\n".join(
            (
                *_sqlite_dump(config.control_database),
                *_sqlite_dump(config.execution_database),
                *_sqlite_dump(config.agent_journal),
                *_sqlite_dump(remote_root / "journal.sqlite"),
            )
        )
        assert local_binding not in protected_dump
        assert remote_binding not in protected_dump
        assert "remote-busy-private-binding" not in protected_dump
    finally:
        agent.close()
        server.stop()
        daemon.stop()


def test_gpu_model_fallback_uses_daemon_accepted_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    now = ["2026-08-24T00:00:00Z"]
    run_root = tmp_path / "runs"
    store = LocalRunStore(run_root)
    run_uri, authority = _prepare_gpu_environment_run(
        store,
        run_name="fallback-after-wait",
        preferred_models=("unavailable-model",),
        fallback_after_seconds=2,
        target="machine-A",
    )
    descriptor = GpuDeviceDescriptor("local-safe", "small", 80 * 1024**3)
    binding = "local-private-binding"
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent",
        run_root,
        _local_launch_profile(),
        machine_id="machine-A",
        gpu_devices=(ConfiguredGpuDevice(descriptor, binding),),
        poll_interval_seconds=0.01,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    client = daemon.client_view(
        LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
    )
    try:
        client.submit(LocalDaemonAdmissionRequest("fallback-item", run_uri))
        deadline = monotonic() + 5
        while monotonic() < deadline:
            admission = next(
                item
                for item in client.admissions().admissions
                if item.queue_item_id == "fallback-item"
            )
            if admission.state is LocalDaemonAdmissionState.WAITING:
                break
            sleep(0.01)
        else:
            pytest.fail("fallback run did not reach its preferred-only wait")

        assert authority.open_run(run_uri).stages[0].status is StageStatus.PENDING
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 0
            )
            record = cast(
                tuple[str],
                conn.execute("SELECT record_json FROM stage_work").fetchone(),
            )
        assert json.loads(record[0])["ready_at"] == 1_787_529_600

        now[0] = "2026-08-24T00:00:03Z"
        completed = client.wait("fallback-item", timeout_seconds=10)
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        snapshot = authority.open_run(run_uri)
        output = cast(
            Mapping[str, object],
            LocalArtifactStore(store.local_artifact_root(run_uri)).load(
                snapshot.stages[0].artifact_facts[0].artifact
            ),
        )
        assert output["value"] == binding

        with sqlite3.connect(config.execution_database) as conn:
            receipt = cast(
                tuple[str],
                conn.execute(
                    "SELECT receipt_json FROM coordinator_assignments"
                ).fetchone(),
            )
        receipt_value = cast(Mapping[str, object], json.loads(receipt[0]))
        assert receipt_value["fallback_eligible"] is True
        assert receipt_value["as_of"] == now[0]
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    "details",
    [
        {"threshold": 0.5, "": None, "key-" * 50: "path evidence"},
        {"items": [0.5] * 256},
        {str(index): 0.5 for index in range(256)},
        _nested_report_detail(511),
    ],
    ids=["plain-types", "list-limit", "object-limit", "depth-limit"],
)
def test_report_failure_decoder_preserves_bounded_plain_data_and_codec_round_trip(
    details: Mapping[str, PlainData],
) -> None:
    report = _failure_report(details)
    encoded = json.dumps({"report": report.to_dict()}).encode()
    decoded = _decode(encoded, failure_report=True)
    replayed = _RemoteExecutionReport.from_dict(decoded["report"])
    assert json.dumps({"report": replayed.to_dict()}).encode() == encoded
    with pytest.raises(QueueServiceError):
        _decode(encoded)
    with pytest.raises(QueueServiceError):
        _decode_run_inspection_response(encoded)


@pytest.mark.parametrize(
    ("details", "message"),
    [
        (_nested_report_detail(512), "maximum depth 512"),
        ({"items": [0.5] * 257}, "maximum 256 items"),
        ({str(index): 0.5 for index in range(257)}, "maximum 256 entries"),
        ({"traceback": "x" * 65_536}, "maximum 65536 bytes"),
    ],
    ids=["depth-overflow", "list-overflow", "object-overflow", "byte-overflow"],
)
def test_report_failure_decoder_rejects_genuine_overflow(
    details: Mapping[str, PlainData], message: str
) -> None:
    encoded = json.dumps({"report": _failure_report(details).to_dict()}).encode()
    with pytest.raises(QueueServiceError, match=message):
        _decode(encoded, failure_report=True)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_report_failure_decoder_rejects_nonfinite_numbers(number: str) -> None:
    encoded = (
        '{"report":{"schema_version":6,"failure":{"details":{"x":' + number + "}}}}"
    ).encode()
    with pytest.raises(QueueServiceError, match="JSON.*(invalid|non-finite)"):
        _decode(encoded, failure_report=True)


def test_failure_report_exception_cannot_widen_surrounding_or_retired_fields() -> None:
    value: dict[str, Any] = {"report": _failure_report({"threshold": 0.5}).to_dict()}
    for misplaced in (
        {"failure": value["report"]["failure"]},
        {**value, "authorization_revision": 0.5},
        {**value, "unknown": _nested_report_detail(9)},
        {**value, "": "invalid envelope key"},
        {"report": {**value["report"], "schema_version": 1}},
        {"report": {**value["report"], "schema_version": 6.0}},
    ):
        with pytest.raises(QueueServiceError):
            _decode(json.dumps(misplaced).encode(), failure_report=True)
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(
            b'{"report":{"schema_version":6,"failure":{"x":1,"x":2}}}',
            failure_report=True,
        )


@pytest.mark.parametrize("output_kind", ["relay", "shared"])
def test_report_metadata_preserves_plain_values(output_kind) -> None:
    metadata = {
        "request": {"resolved_runtime": {"reliability": {
            "timeout": {"enabled": True, "duration_seconds": 3600.5},
        }}},
        "observations": [None, True, 2, 0.25, "ready", {"ratio": 0.75}],
        "nested": _nested_report_detail(5),
    }
    report = replace(_failure_report({}), output_kind=output_kind,
                     executor_metadata=metadata)
    encoded = json.dumps({"report": report.to_dict()}).encode()
    decoded = _decode(encoded, failure_report=True)
    replayed = _RemoteExecutionReport.from_dict(decoded["report"])
    assert replayed.to_dict()["executor_metadata"] == metadata
    assert json.dumps({"report": replayed.to_dict()}).encode() == encoded
    with pytest.raises(QueueServiceError):
        _decode(encoded)


def test_report_metadata_preserves_generated_container_command() -> None:
    from loom.pipeline.executors.apptainer import build_apptainer_exec_command
    from loom.pipeline.executors.containers import (
        ContainerEnvironment, ContainerMount, ContainerOptions,
    )

    command = build_apptainer_exec_command(
        container_options=ContainerOptions(
            image="workload.sif",
            mounts=tuple(
                ContainerMount(f"/host/input-{index}", f"/inputs/{index}", "ro")
                for index in range(16)
            ),
            environment=ContainerEnvironment(
                variables={f"WORKER_{index}": "private-value" for index in range(16)},
            ),
        ),
        worker_command=("python", "-m", "loom"),
        host_environment={},
    )
    argv = command.to_dict()["redacted_argv"]
    assert isinstance(argv, list) and len(argv) > 64
    assert "private-value" not in repr(argv)
    report = replace(_successful_output_report({}), output_kind="shared",
                     executor_metadata={"command": argv})
    value = {"report": report.to_dict()}
    for envelope in (value, {"evidence": {"result_operation": "report", **value}}):
        encoded = json.dumps(envelope).encode()
        assert _decode(encoded, failure_report=True) == envelope
    decoded = _decode(json.dumps(value).encode(), failure_report=True)
    assert _RemoteExecutionReport.from_dict(decoded["report"]).to_dict() == report.to_dict()
    with pytest.raises(QueueServiceError, match="collection is too large"):
        _decode(json.dumps(value).encode())
    oversized = replace(report, executor_metadata={"command": ["x" * 65_536]})
    with pytest.raises(QueueServiceError, match="maximum 65536 bytes"):
        _decode(json.dumps({"report": oversized.to_dict()}).encode(), failure_report=True)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_report_metadata_rejects_nonfinite_numbers(number: str) -> None:
    report = replace(_failure_report({}), output_kind="shared",
                     executor_metadata={"duration_seconds": "NUMBER"})
    encoded = json.dumps({"report": report.to_dict()}).replace('"NUMBER"', number)
    with pytest.raises(QueueServiceError, match="JSON.*invalid"):
        _decode(encoded.encode(), failure_report=True)


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (_nested_report_detail(7), "too deeply nested"),
        ({"values": [0.5] * 65}, "collection is too large"),
        ({str(index): 0.5 for index in range(65)}, "object is too large"),
        ({"": 0.5}, "object key is invalid"),
        ({"key" * 54: 0.5}, "object key is invalid"),
        ({"text": "x" * 65_536}, "maximum 65536 bytes"),
    ],
)
def test_report_metadata_preserves_existing_transport_bounds(metadata, message):
    report = replace(_failure_report({}), output_kind="shared",
                     executor_metadata=metadata)
    with pytest.raises(QueueServiceError, match=message):
        _decode(json.dumps({"report": report.to_dict()}).encode(), failure_report=True)


def test_report_metadata_plain_values_do_not_widen_retired_or_envelope_fields():
    report = replace(_failure_report({}), output_kind="shared",
                     executor_metadata={"duration_seconds": 3600.5}).to_dict()
    for schema_version in (1, 2, 3, 4, 5):
        with pytest.raises(QueueServiceError):
            _decode(json.dumps({"report": {**report, "schema_version": schema_version}}).encode(),
                    failure_report=True)
    with pytest.raises(QueueServiceError):
        _decode(json.dumps({"report": report, "authorization_revision": 0.5}).encode(),
                failure_report=True)


@pytest.mark.parametrize("output_kind", ["relay", "shared"])
def test_report_output_metadata_round_trip(output_kind):
    metadata = {"metric_value": 0.1803790032863617,
                "observations": [None, True, 2, 0.25, "ready", {"ratio": 0.75}]}
    report = replace(_successful_output_report(metadata), output_kind=output_kind)
    encoded = json.dumps({"report": report.to_dict()}).encode()
    decoded = _decode(encoded, failure_report=True)
    replayed = _RemoteExecutionReport.from_dict(decoded["report"])
    assert replayed.outputs[0].to_dict()["metadata"] == metadata
    assert json.dumps({"report": replayed.to_dict()}).encode() == encoded
    with pytest.raises(QueueServiceError):
        _decode(encoded)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_report_output_metadata_rejects_nonfinite(number):
    report = _successful_output_report({"metric_value": "NUMBER"}).to_dict()
    raw = json.dumps({"report": report}).replace('"NUMBER"', number).encode()
    with pytest.raises(QueueServiceError, match="JSON.*invalid"):
        _decode(raw, failure_report=True)


@pytest.mark.parametrize("metadata, message", [
    (_nested_report_detail(5), "too deeply nested"),
    ({"values": [0.5] * 65_536}, "maximum 65536 bytes"),
    ({"": 0.5}, "object key is invalid"),
])
def test_report_output_metadata_preserves_wire_bounds(metadata, message):
    report = _successful_output_report(metadata).to_dict()
    with pytest.raises(QueueServiceError, match=message):
        _decode(json.dumps({"report": report}).encode(), failure_report=True)


@pytest.mark.parametrize("output_kind", ["relay", "shared"])
def test_report_output_inventory_metadata_uses_message_byte_budget(output_kind):
    metadata = {"field_keys": [f"field_{index}" for index in range(84)],
                "counts": {f"field_{index}": index for index in range(84)}}
    report = replace(_successful_output_report(metadata), output_kind=output_kind)
    raw = json.dumps({"report": report.to_dict()}).encode()
    decoded = _decode(raw, failure_report=True)
    replayed = _RemoteExecutionReport.from_dict(decoded["report"])
    assert replayed.outputs[0].to_dict()["metadata"] == metadata
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(raw)
    envelope = {"report": report.to_dict(), "control_values": list(range(65))}
    with pytest.raises(QueueServiceError, match="collection is too large"):
        _decode(json.dumps(envelope).encode(), failure_report=True)


def test_report_output_metadata_does_not_widen_control_fields():
    report = cast(dict[str, Any], _successful_output_report({"metric_value": 0.25}).to_dict())
    report["outputs"][0]["size_bytes"] = 1.5
    with pytest.raises(QueueServiceError):
        _decode(json.dumps({"report": report}).encode(), failure_report=True)


def test_protocol_codec_rejects_duplicate_nonfinite_deep_and_oversized_json() -> None:
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":1,"value":2}')
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":NaN}')
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(b'{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":1}}}}}}}}}')
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(b"{" + b" " * 65_536 + b"}")
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(b'{"nested":' * 1500 + b"0" + b"}" * 1500)
    with pytest.raises(QueueServiceError, match="JSON value is invalid"):
        _decode(b'{"value":0.5}')


def test_run_inspection_response_decoder_preserves_phase_one_limits() -> None:
    records = [{"index": index} for index in range(256)]
    encoded = json.dumps({"ok": True, "result": {"records": records}}).encode()

    assert _decode_run_inspection_response(encoded) == {
        "ok": True,
        "result": {"records": records},
    }
    with pytest.raises(QueueServiceError, match="collection is too large"):
        _decode_run_inspection_response(
            json.dumps(
                {"ok": True, "result": {"records": records + [{"index": 256}]}}
            ).encode()
        )
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode_run_inspection_response(b'{"ok":true,"ok":false}')
    with pytest.raises(QueueServiceError, match="too large"):
        _decode_run_inspection_response(b"{" + b" " * 1_048_576 + b"}")


@pytest.mark.parametrize("with_local_agent", (False, True))
def test_loopback_remote_agent_declines_then_executes_and_commits_real_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_local_agent: bool,
) -> None:
    observed = []

    def record(value, *, qualification):
        observed.extend(value["spans"])

    monkeypatch.setattr("loom.queue._phase_diagnostics.diagnostics.submit", record)
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
    run_root = tmp_path / "runs"
    store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "remote-run")
    store.create_run(run_uri)
    pipeline_config = {
        "name": "remote-real-process",
        "stages": [
            {
                "name": "build",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {"value": 42},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": "agent-a"},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            },
            {
                "name": "consume",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.TextConsumerStage"
                    )
                },
                "depends_on": ["build"],
                "inputs": {"data": "build.data"},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": "agent-a"},
                "outputs": {"text": {"artifact_type": "text", "codec_key": "text.v1"}},
            },
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {
                "build": {"executor": "local"},
                "consume": {"executor": "local"},
            },
        },
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements={
            stage_name: ExecutionRequirement("project-1", "environment-1", "executor-1")
            for stage_name in spec.stage_names
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)

    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent" if with_local_agent else None,
        run_root,
        _local_launch_profile() if with_local_agent else None,
        cpu_capacity=1 if with_local_agent else 0,
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
    remote_root = _fresh_remote_agent_root(tmp_path)
    profile = ResidentExecutionProfile(
        descriptor,
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    remote_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        remote_root,
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(remote_config)
    agent = LocalDaemonAgentHttpClient(remote_config)
    try:
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        admission = coordinator.submit(
            LocalDaemonAdmissionRequest("remote-item", run_uri)
        )
        detail = coordinator.admission(admission.admission_id)
        assert detail.admission.run_uri == run_uri
        assert detail.authority["availability"] == "available"
        local_execution = detail.owners["execution"]
        assert isinstance(local_execution, Mapping)
        assert local_execution["availability"] == (
            "available" if with_local_agent else "unavailable"
        )
        with pytest.raises(TimeoutError):
            coordinator.wait("remote-item", timeout_seconds=0.05)
        assert daemon.status().service_health == "healthy"
        assert daemon.status().running_assignments == 0
        if not with_local_agent:
            assert not (tmp_path / "coordinator-agent").exists()
            assert config.agent_resource_providers == ()
            assert daemon._execution is not None
            assert daemon._execution.supervisor is None
        handshake = agent.handshake()
        session = agent.register(
            AgentRegistration(
                "register-remote-1",
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
        original_target_delivery = local_daemon_execution._target_remote_delivery
        stale_target_once = False

        def lose_first_target_race(*args: object, **kwargs: object) -> None:
            nonlocal stale_target_once
            if not stale_target_once:
                stale_target_once = True
                raise QueueConflictError("simulated stale target selection")
            original_target_delivery(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            local_daemon_execution,
            "_target_remote_delivery",
            lose_first_target_race,
        )
        original_prepare = AtomResourceProvider.prepare
        declined_once = False

        def decline_first_claim(
            provider: AtomResourceProvider, command: ClaimCommand
        ) -> ClaimResult:
            nonlocal declined_once
            if not declined_once:
                declined_once = True
                return ClaimResult(
                    ClaimOutcome.DECLINED,
                    command.operation_id,
                    command.claim.fingerprint,
                    "simulated physical capacity race",
                )
            return original_prepare(provider, command)

        monkeypatch.setattr(AtomResourceProvider, "prepare", decline_first_claim)
        original_read_input = agent.read_input_chunk
        stale_transfer_once = False

        def expire_first_input_authorization(*args: object, **kwargs: object):
            nonlocal stale_transfer_once
            if not stale_transfer_once:
                stale_transfer_once = True
                raise AgentTransferAuthorizationStaleError(
                    "simulated expired transfer authorization"
                )
            return original_read_input(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(agent, "read_input_chunk", expire_first_input_authorization)
        execution_owner = daemon._execution
        assert execution_owner is not None
        execution_type = type(execution_owner)
        original_remote_commit = execution_type.remote_commit
        authority_outage_once = False

        def commit_after_authority_outage(
            owner: object, *args: object, **kwargs: object
        ) -> None:
            nonlocal authority_outage_once
            if not authority_outage_once:
                authority_outage_once = True
                raise RuntimeError("simulated authority outage before terminal commit")
            original_remote_commit(owner, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            execution_type,
            "remote_commit",
            commit_after_authority_outage,
        )
        original_accept = agent.accept_assignment
        accepted_fences: dict[str, str] = {}

        def remember_grant(*args: object, **kwargs: object):
            result = original_accept(*args, **kwargs)  # type: ignore[arg-type]
            assignment_id = str(args[1])
            accepted_fences[assignment_id] = str(result["fence"])
            return result

        monkeypatch.setattr(agent, "accept_assignment", remember_grant)
        original_upload = agent.upload_output_chunk
        partial_commit_blocked = False

        def reject_commit_before_complete_output(*args: object, **kwargs: object):
            nonlocal partial_commit_blocked
            assignment_id = str(args[1])
            if not partial_commit_blocked:
                with pytest.raises(QueueConflictError):
                    agent.commit_result(
                        str(args[0]),
                        assignment_id,
                        fence=accepted_fences[assignment_id],
                    )
                partial_commit_blocked = True
            return original_upload(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            agent,
            "upload_output_chunk",
            reject_commit_before_complete_output,
        )
        original_confirm = agent.confirm_started
        original_epoch = session.coordinator_epoch
        restarted = False

        def confirm_across_restart(*args: object, **kwargs: object):
            nonlocal restarted
            if not restarted:
                restarted = True
                daemon.stop()
                daemon.start()
                raise QueueConflictError(
                    "simulated stale start response after coordinator restart"
                )
            return original_confirm(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(agent, "confirm_started", confirm_across_restart)
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
            idempotency_key="offer-remote-1",
        )
        with ThreadPoolExecutor(max_workers=1) as workers:
            execution = workers.submit(
                _execute_available_assignment,
                agent,
                session.session_id,
                session.availability_revision,
            )
            declined = execution.result(timeout=40)
            next_session = cast(Mapping[str, object], declined["session"])
            next_availability = str(next_session["availability_revision"])
            agent.publish_offer(
                AgentOffer(
                    str(next_session["session_id"]),
                    str(next_session["coordinator_epoch"]),
                    str(next_session["config_revision"]),
                    str(next_session["inventory_revision"]),
                    next_availability,
                    1,
                    0,
                    30,
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-2",
            )
            execution = workers.submit(
                _execute_available_assignment,
                agent,
                session.session_id,
                next_availability,
            )
            first = execution.result(timeout=40)
            next_session = cast(Mapping[str, object], first["session"])
            next_availability = str(next_session["availability_revision"])
            agent.publish_offer(
                AgentOffer(
                    str(next_session["session_id"]),
                    str(next_session["coordinator_epoch"]),
                    str(next_session["config_revision"]),
                    str(next_session["inventory_revision"]),
                    next_availability,
                    1,
                    0,
                    30,
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-3",
            )
            execution = workers.submit(
                _execute_available_assignment,
                agent,
                session.session_id,
                next_availability,
            )
            second = execution.result(timeout=40)
        completed = coordinator.wait("remote-item", timeout_seconds=10)

        assert declined["state"] == "DECLINED"
        assert stale_target_once
        assert declined_once
        assert stale_transfer_once
        assert authority_outage_once
        assert partial_commit_blocked
        assert first["state"] == "RELEASED"
        assert second["state"] == "RELEASED"
        boundaries = {"assignment_received", "stage_run_entered", "stage_run_returned",
                      "terminal_acknowledged", "assignment_released"}
        for assignment in (first, second):
            spans = [span for span in observed if span["action"] in boundaries
                     and span["attributes"]["assignment_id"] == assignment["assignment_id"]]
            assert [span["action"] for span in spans] == [
                "assignment_received", "stage_run_entered", "stage_run_returned",
                "terminal_acknowledged", "assignment_released",
            ]
            assert spans[1]["attributes"]["process_id"] != os.getpid()
            assert spans[1]["attributes"]["attempt_id"] == spans[0]["attributes"]["attempt_id"]
        assert restarted
        assert daemon.status().coordinator_epoch != original_epoch
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        detail = coordinator.admission(admission.admission_id)
        assert detail.admission.state is LocalDaemonAdmissionState.SUCCEEDED
        assert detail.authority["state"] == RunStatus.SUCCEEDED.value
        assignments_view = detail.owners["assignment"]
        assert isinstance(assignments_view, Mapping)
        assert assignments_view["availability"] == "available"
        assert assignments_view["state"] == "populated"
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.SUCCEEDED
        assert [stage.status for stage in snapshot.stages] == [
            StageStatus.SUCCEEDED,
            StageStatus.SUCCEEDED,
        ]
        assert [
            tuple(attempt.attempt for attempt in stage.attempts)
            for stage in snapshot.stages
        ] == [
            (1,),
            (1,),
        ]
        for stage in snapshot.stages:
            output = stage.artifact_facts[0].artifact
            assert Path(output.uri.removeprefix("file://")).is_file()
            assert str(remote_root) not in output.uri
        with sqlite3.connect(config.execution_database) as conn:
            assignments = tuple(
                conn.execute(
                    "SELECT agent_id, state FROM coordinator_assignments "
                    "ORDER BY assignment_id"
                )
            )
        assert assignments == (("agent-a", "released"),) * 4
        with sqlite3.connect(config.control_database) as conn:
            input_transfers = tuple(
                conn.execute(
                    "SELECT finalized, private_path FROM remote_transfers "
                    "WHERE direction = 'input'"
                )
            )
        assert len(input_transfers) == 1
        assert input_transfers[0][0] == 1
        assert str(config.coordinator_root) in str(input_transfers[0][1])
    finally:
        agent.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize(
    ("role", "operation", "certificate"),
    [("agent", "output_manifest", "agent"), ("slurm_bootstrap", "report", "other")],
)
def test_loopback_report_routes_preserve_near_limit_failure_and_strict_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    operation: str,
    certificate: str,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=_policy(),
        slurm_profiles=(_slurm_bootstrap_profile(tmp_path),),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    received: list[dict[str, PlainData]] = []

    def declare_outputs(*_args, report: _RemoteExecutionReport, **_kwargs):
        received.append(report.to_dict())
        return {"accepted": True}

    def declare_report(_assignment, _incarnation, _fence, report):
        received.append(_RemoteExecutionReport.from_dict(report).to_dict())

    monkeypatch.setattr(
        daemon,
        "agent_view",
        lambda _principal: SimpleNamespace(declare_outputs=declare_outputs),
    )
    monkeypatch.setattr(
        daemon,
        "slurm_bootstrap_view",
        lambda _principal: SimpleNamespace(declare_report=declare_report),
    )
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
                ): "slurm-credential",
            },
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials[certificate].with_suffix(".crt"),
            credentials[certificate].with_suffix(".key"),
        )
    )
    report = replace(
        _failure_report(_nested_report_detail(511)),
        executor_metadata={"duration_seconds": 3600.5},
    ).to_dict()
    envelope: dict[str, PlainData] = {
        "assignment_id": "assignment-1",
        "fence": "fence-1",
        "report": report,
        **(
            {
                "session_id": "session-1",
                "authorization_id": "authorization-1",
                "authorization_revision": 1,
            }
            if role == "agent"
            else {"incarnation": "incarnation-1"}
        ),
    }
    try:
        client._call(operation, envelope, role=role)
        assert json.dumps(received) == json.dumps([report])
        assert client._connection is not None
        overflow_items: list[PlainData] = [0.5] * 257
        oversized = {
            **envelope,
            "report": _failure_report({"items": overflow_items}).to_dict(),
        }
        with monkeypatch.context() as outbound:

            def must_not_send(*_args, **_kwargs):
                pytest.fail("invalid outbound report must fail before HTTP submission")

            outbound.setattr(client._connection, "request", must_not_send)
            with pytest.raises(QueueServiceError, match="maximum 256 items"):
                client._call(operation, oversized, role=role)

        # Bypass the client validator to exercise the independently bounded server.
        for rejected in (oversized, {**envelope, "unexpected": "field"}):
            client._call(operation, envelope, role=role)
            connection = client._connection
            assert connection is not None
            connection.request(
                "POST",
                f"/v1/{role}/{operation}",
                body=json.dumps(rejected).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            assert response.status == 403
            assert json.loads(response.read())["error"] == "agent_protocol_rejected"
            client._close_connection()
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client._call(operation, envelope, role="client")
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client._call("event", envelope, role=role)
        assert len(received) == 3
    finally:
        client.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("remote", (False, True))
def test_external_gpu_occupancy_drives_real_local_and_remote_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: bool
) -> None:
    exercise_gpu_occupancy(tmp_path, monkeypatch, remote)


def test_slurm_relay_preserves_existing_failure_depth_and_outer_bounds():
    from loom.queue.agent_session_transport import _decode

    report = replace(
        _failure_report(_nested_report_detail(511)),
        executor_metadata={"duration_seconds": 3600.5},
    ).to_dict()
    request = {
        "session_id": "session",
        "coordinator_epoch": "epoch",
        "cursor": None,
        "evidence": {"result_operation": "report", "report": report},
    }
    _decode(json.dumps(request).encode(), failure_report=True)
    with pytest.raises(QueueServiceError, match="too deeply nested"):
        _decode(
            json.dumps({**request, "unexpected": _nested_report_detail(20)}).encode(),
            failure_report=True,
        )
    items: list[PlainData] = [0] * 257
    request["evidence"]["report"] = _failure_report({"items": items}).to_dict()
    with pytest.raises(QueueServiceError, match="maximum 256"):
        _decode(json.dumps(request).encode(), failure_report=True)


def test_shared_result_schema_preserves_existing_failure_envelope_bounds():
    from dataclasses import replace
    report = replace(_failure_report({"metric": 0.5, "nested": _nested_report_detail(20)}),
                     output_kind="shared", executor_metadata={})
    value = {"report": report.to_dict()}
    decoded = _decode(json.dumps(value).encode(), failure_report=True)
    assert _RemoteExecutionReport.from_dict(decoded["report"]) == report
    with pytest.raises(QueueServiceError):
        _decode(json.dumps({**value, "authorization_revision": 0.5}).encode(), failure_report=True)


def test_native_https_bulk_saturation_preserves_control_capacity(native_control_endpoint, monkeypatch):
    from threading import Lock

    daemon, server, connection_path, credentials = native_control_endpoint
    config = AgentTlsClientConfig(
        f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key"),
    )
    client = CoordinatorClient.from_connection_file(connection_path)
    worker = LocalDaemonAgentHttpClient(config)
    entered, release = Event(), Event()
    guard = Lock()
    active = maximum = 0
    original = agent_session_transport._dispatch

    def blocked_dispatch(view, operation, payload):
        nonlocal active, maximum
        if operation != "output_manifest":
            return original(view, operation, payload)
        with guard:
            active += 1
            maximum = max(maximum, active)
            if active == 4:
                entered.set()
        try:
            assert release.wait(15)
            return {"state": "prepared"}
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(agent_session_transport, "_dispatch", blocked_dispatch)
    exchange = agent_session_transport._exchange_agent_request
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(exchange, config, "output_manifest", b"{}", "agent", None, False)
                       for _ in range(4)]
            try:
                assert entered.wait(8)
                with pytest.raises(agent_session_transport._IndeterminateAgentProtocolError, match="capacity"):
                    exchange(config, "output_manifest", b"{}", "agent", None, False)
                assert client.status().coordinator_id == daemon._coordinator_id
                assert worker.handshake()["coordinator_id"] == daemon._coordinator_id
                assert maximum == 4 and active == 4
                # A rejected caller cannot free slots still executing on the server.
                with pytest.raises(agent_session_transport._IndeterminateAgentProtocolError, match="capacity"):
                    exchange(config, "output_manifest", b"{}", "agent", None, False)
            finally:
                release.set()
            for future in futures:
                future.result(10)
        exchange(config, "output_manifest", b"{}", "agent", None, False)
    finally:
        release.set()
        client.close()
        worker.close()


def _prepare_mixed_local_remote_sleep_run(
    store: LocalRunStore,
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / "mixed-local-remote")
    store.create_run(run_uri)
    pipeline_config = {
        "name": "mixed-local-remote",
        "stages": [
            {
                "name": stage_name,
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {"seconds": 20},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": target},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
            for stage_name, target in (
                ("local", "machine-A"),
                ("remote", "agent-a"),
            )
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {
                "local": {"executor": "local"},
                "remote": {"executor": "local"},
            },
        },
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements={
            "local": ExecutionRequirement(
                "test-project", "test-environment", "test-executor"
            ),
            "remote": ExecutionRequirement("project-1", "environment-1", "executor-1"),
        },
        options={
            "run_uri": run_uri,
            "executor": "local",
            "execution": {"settings": {"max_parallel_stages": 2}},
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


def _successful_output_report(metadata):
    from loom.queue._remote_stage_execution import _RemoteOutputArtifact
    output = _RemoteOutputArtifact(
        transfer_id="output-1", logical_name="selected", digest="a" * 64,
        size_bytes=1, artifact_id="fit/selected", artifact_type="checkpoint",
        codec_key=None, artifact_schema_version=1, fingerprint=None,
        producer_stage="build", created_at="2020-01-01T00:00:01Z", metadata=metadata,
    )
    return replace(_failure_report({}), status=StageStatus.SUCCEEDED,
                   failure=None, failure_type=None, message=None, outputs=(output,))
