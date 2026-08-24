"""Real loopback mutual-TLS evidence for the restricted agent protocol."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import ssl
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from time import monotonic, sleep
from typing import cast

import pytest

import loom.queue.local_daemon_execution as local_daemon_execution
from loom.pipeline import PipelineSpec
from loom.pipeline.execution.managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    ManagedAssignment,
    SQLiteAgentJournal,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import CpuResourcePlanner
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    prepare_managed_local_runtime_record,
)
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _decode,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSessionState,
    AgentTransferAuthorizationStaleError,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.scheduling import ResourceClaim
from loom.serialization import PlainData, json_dumps_pretty


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def _credentials(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir()
    _run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-subj",
        "/CN=loom-test-ca",
        "-days",
        "1",
        cwd=tmp_path,
    )
    for name, subject in (
        ("server", "/CN=localhost"),
        ("agent", "/CN=agent"),
        ("other", "/CN=other"),
    ):
        _run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
            "-subj",
            subject,
            cwd=tmp_path,
        )
        extension = (
            "subjectAltName=DNS:localhost"
            if name == "server"
            else "extendedKeyUsage=clientAuth"
        )
        (tmp_path / f"{name}.ext").write_text(extension, encoding="utf-8")
        _run(
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            f"{name}.crt",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            f"{name}.ext",
            cwd=tmp_path,
        )
    return {name: tmp_path / name for name in ("ca", "server", "agent", "other")}


def _fingerprint(certificate: Path) -> str:
    return hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding="utf-8"))
    ).hexdigest()


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                ("python",),
            ),
        )
    )


def _request(handshake: Mapping[str, object], agent_root_id: str) -> AgentRegistration:
    return AgentRegistration(
        idempotency_key="register-1",
        coordinator_id=str(handshake["coordinator_id"]),
        coordinator_epoch=str(handshake["coordinator_epoch"]),
        agent_root_id=agent_root_id,
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision="availability-1",
        declared_pools=("default",),
        declared_capabilities=("python",),
    )


def _remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    root = tmp_path / name / "agent"
    LocalDaemon.initialize_agent_root(root)
    return root


def _prepare_remote_producer_run(
    store: LocalRunStore,
    *,
    run_name: str,
    machine_id: str,
    value: int,
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": "build",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {"value": value},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"build": {"executor": "local"}}},
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
        machine_id=machine_id,
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


def _sqlite_dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def test_restarted_agent_with_retained_claim_exposes_no_capacity(
    tmp_path: Path,
) -> None:
    agent_root = _remote_agent_root(tmp_path)
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
    planner = CpuResourcePlanner()
    atom = profile.capacity_atoms("agent-a")[0]
    claim = ResourceClaim(
        "cpu",
        planner.claim_contracts[0],
        (atom,),
        1,
    )
    command = ClaimCommand(assignment, "assignment-1:prepare:0", claim)
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
                "cpu": AtomResourceProvider(
                    planner.descriptor,
                    planner.claim_contracts,
                    (atom,),
                )
            },
        )
        is AssignmentState.PREPARED
    )

    restarted = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            "https://localhost:1",
            tmp_path / "ca.crt",
            tmp_path / "agent.crt",
            tmp_path / "agent.key",
            agent_root,
            (profile,),
        )
    )
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
            resident_profiles=(descriptor,),
        )
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            restarted.publish_offer(offer, idempotency_key="offer-after-restart")
        with pytest.raises(QueueConflictError, match="cannot poll"):
            restarted.wait_for_work(
                "session-1",
                "availability-1",
                poll_id="poll-after-restart",
                wait_timeout_ms=1,
            )
    finally:
        restarted.close()


def test_restarted_agent_with_an_indeterminate_poll_exposes_no_capacity(
    tmp_path: Path,
) -> None:
    agent_root = _remote_agent_root(tmp_path)
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
    with sqlite3.connect(agent_root / "control.sqlite") as conn:
        conn.execute(
            "INSERT INTO agent_polls_local(session_id, availability_revision, "
            "poll_id, state) VALUES ('session-1', 'availability-1', "
            "'poll-1', 'PENDING')"
        )
        conn.commit()

    restarted = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            "https://localhost:1",
            tmp_path / "ca.crt",
            tmp_path / "agent.crt",
            tmp_path / "agent.key",
            agent_root,
            (profile,),
        )
    )
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
            resident_profiles=(descriptor,),
        )
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            restarted.publish_offer(offer, idempotency_key="offer-after-restart")
        with pytest.raises(QueueConflictError, match="cannot poll"):
            restarted.wait_for_work(
                "session-1",
                "availability-1",
                poll_id="poll-after-restart",
                wait_timeout_ms=1,
            )
    finally:
        restarted.close()


def test_two_remote_agents_execute_two_globally_selected_runs(tmp_path: Path) -> None:
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
        machine_id="agent-a",
        value=1,
    )
    run_b, authority_b = _prepare_remote_producer_run(
        store,
        run_name="remote-b",
        machine_id="agent-b",
        value=2,
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        run_root,
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
    agent_a = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            _remote_agent_root(tmp_path, "remote-owner-a"),
            (
                ResidentExecutionProfile(
                    descriptor,
                    project_root,
                    Path(sys.executable),
                ),
            ),
        )
    )
    agent_b = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
            _remote_agent_root(tmp_path, "remote-owner-b"),
            (
                ResidentExecutionProfile(
                    descriptor,
                    project_root,
                    Path(sys.executable),
                ),
            ),
        )
    )

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
                resident_profiles=(descriptor,),
            ),
            idempotency_key=f"offer-{suffix}",
        )
        return session

    try:
        session_a = register(agent_a, "a")
        session_b = register(agent_b, "b")
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            execution_a = workers.submit(
                agent_a.execute_one,
                session_a.session_id,
                session_a.availability_revision,
                poll_id="poll-a",
                wait_timeout_ms=5_000,
            )
            execution_b = workers.submit(
                agent_b.execute_one,
                session_b.session_id,
                session_b.availability_revision,
                poll_id="poll-b",
                wait_timeout_ms=5_000,
            )
            coordinator.submit(LocalDaemonAdmissionRequest("item-a", run_a))
            coordinator.submit(LocalDaemonAdmissionRequest("item-b", run_b))
            result_a = execution_a.result(timeout=20)
            result_b = execution_b.result(timeout=20)
        completed_a = coordinator.wait("item-a", timeout_seconds=10)
        completed_b = coordinator.wait("item-b", timeout_seconds=10)

        assert result_a["state"] == "RELEASED"
        assert result_b["state"] == "RELEASED"
        assert completed_a.state is LocalDaemonAdmissionState.SUCCEEDED
        assert completed_b.state is LocalDaemonAdmissionState.SUCCEEDED
        for snapshot in (authority_a.open_run(run_a), authority_b.open_run(run_b)):
            assert snapshot.status is RunStatus.SUCCEEDED
            assert snapshot.stages[0].status is StageStatus.SUCCEEDED
            output = snapshot.stages[0].artifact_facts[0].artifact
            assert Path(output.uri.removeprefix("file://")).is_file()
        with sqlite3.connect(config.execution_database) as conn:
            assignments = tuple(
                conn.execute(
                    "SELECT agent_id, state FROM coordinator_assignments "
                    "ORDER BY agent_id"
                )
            )
        assert assignments == (
            ("agent-a", "released"),
            ("agent-b", "released"),
        )
    finally:
        agent_a.close()
        agent_b.close()
        server.stop()
        daemon.stop()


def test_protocol_codec_rejects_duplicate_nonfinite_deep_and_oversized_json() -> None:
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":1,"value":2}')
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":NaN}')
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(b'{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":1}}}}}}}}}')
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(b"{" + b" " * 65_536 + b"}")


def test_agent_client_rejects_an_old_coordinator_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            "https://localhost:1",
            tmp_path / "ca.crt",
            tmp_path / "agent.crt",
            tmp_path / "agent.key",
        )
    )

    def old_handshake(
        operation: str,
        value: Mapping[str, PlainData],
        *,
        role: str = "agent",
    ) -> Mapping[str, PlainData]:
        _ = operation, value, role
        return {
            "protocol_version": "1",
            "capabilities": ["agent-sessions-v1"],
            "coordinator_id": "coordinator-1",
            "coordinator_epoch": "epoch-1",
            "role": "agent",
        }

    monkeypatch.setattr(client, "_call", old_handshake)
    with pytest.raises(QueueServiceError, match="hard cut-over"):
        client.handshake()


def test_loopback_mtls_derives_credential_and_rechecks_live_policy(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent-root",
        run_store_root=tmp_path / "runs",
        agent_policy=_policy(),
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
                ): "agent-credential",
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "agent-credential-2",
            },
        ),
    )
    server.start()
    remote_agent_root = _remote_agent_root(tmp_path)
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            remote_agent_root,
        )
    )
    try:
        handshake = dict(client.handshake())
        assert set(handshake) == {
            "protocol_version",
            "capabilities",
            "coordinator_id",
            "coordinator_epoch",
            "role",
        }
        request = _request(handshake, client.agent_root_id)
        registered = client.register(request)
        with daemon._connection() as conn:
            verifier = conn.execute(
                "SELECT retirement_verifier FROM agent_sessions WHERE session_id = ?",
                (registered.session_id,),
            ).fetchone()[0]
        direct_replay = (
            daemon.agent_view(  # direct and HTTP share transition/idempotency state
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).register(replace(request, retirement_verifier=str(verifier)))
        )
        assert direct_replay.session_id == registered.session_id
        changed = replace(
            request, config_revision="changed", retirement_verifier=str(verifier)
        )
        with pytest.raises(QueueConflictError, match="protocol conflict"):
            client._call("register", changed.value())
        with pytest.raises(QueueConflictError, match="different content"):
            daemon.agent_view(
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).register(changed)
        with pytest.raises(QueueConflictError, match="protocol conflict"):
            client._call(
                "reconcile",
                {
                    "expected": replace(
                        registered, agent_id="body-selected-agent"
                    ).value(),
                    "coordinator_epoch": registered.coordinator_epoch,
                    "idempotency_key": "reconcile-forged-agent",
                },
            )
        client.publish_offer(
            AgentOffer(
                registered.session_id,
                registered.coordinator_epoch,
                "config-1",
                "inventory-1",
                "availability-1",
                1,
                1,
                10,
            ),
            idempotency_key="offer-1",
        )
        connection = client._connection
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                client.wait_for_work,
                registered.session_id,
                registered.availability_revision,
                poll_id="poll-live",
                wait_timeout_ms=1_000,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_polls WHERE poll_id = 'poll-live'"
                    ).fetchone()
                if active is not None and bool(active[0]):
                    break
                sleep(0.01)
            else:
                pytest.fail("loopback work poll did not become active")
            daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
            with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
                pending.result(timeout=2)
        assert connection is not None  # policy was rechecked on the held TLS request
        assert client._connection is None  # rejected requests fence connection framing
        client.close()

        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-3",
                agents=(
                    AgentPrincipalPolicy(
                        "agent-credential-2",
                        "agent-principal",
                        "agent-a",
                        ("default",),
                        ("python",),
                    ),
                ),
            )
        )
        rotated = LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials["other"].with_suffix(".crt"),
                credentials["other"].with_suffix(".key"),
                remote_agent_root,
            )
        )
        try:
            current = rotated.handshake()
            resumed = rotated.reconcile(
                registered.session_id,
                str(current["coordinator_epoch"]),
                idempotency_key="reconcile-rotated-credential",
            )
            assert resumed.policy_revision == "policy-3"
            rotated.publish_offer(
                AgentOffer(
                    resumed.session_id,
                    resumed.coordinator_epoch,
                    resumed.config_revision,
                    resumed.inventory_revision,
                    resumed.availability_revision,
                    1,
                    1,
                    10,
                ),
                idempotency_key="offer-rotated-credential",
            )
            assert (
                rotated.wait_for_work(
                    resumed.session_id,
                    resumed.availability_revision,
                    poll_id="poll-rotated-credential",
                    wait_timeout_ms=10,
                )["result"]
                == "wait"
            )
        finally:
            rotated.close()
    finally:
        client.close()
        server.stop()
        daemon.stop()


def test_loopback_remote_agent_declines_then_executes_and_commits_real_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
                "outputs": {"text": {"artifact_type": "text", "codec_key": "text.v1"}},
            },
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
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
        machine_id="agent-a",
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)

    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        run_root,
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
    remote_root = _remote_agent_root(tmp_path)
    profile = ResidentExecutionProfile(
        descriptor,
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    agent = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            remote_root,
            (profile,),
        )
    )
    try:
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
                resident_profiles=(descriptor,),
            ),
            idempotency_key="offer-remote-1",
        )
        coordinator = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
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
        with ThreadPoolExecutor(max_workers=1) as workers:
            execution = workers.submit(
                agent.execute_one,
                session.session_id,
                session.availability_revision,
                poll_id="poll-remote-1",
                wait_timeout_ms=5_000,
            )
            coordinator.submit(LocalDaemonAdmissionRequest("remote-item", run_uri))
            declined = execution.result(timeout=20)
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
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-2",
            )
            execution = workers.submit(
                agent.execute_one,
                session.session_id,
                next_availability,
                poll_id="poll-remote-2",
                wait_timeout_ms=5_000,
            )
            first = execution.result(timeout=20)
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
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-3",
            )
            execution = workers.submit(
                agent.execute_one,
                session.session_id,
                next_availability,
                poll_id="poll-remote-3",
                wait_timeout_ms=5_000,
            )
            second = execution.result(timeout=20)
        completed = coordinator.wait("remote-item", timeout_seconds=10)

        assert declined["state"] == "DECLINED"
        assert stale_target_once
        assert declined_once
        assert stale_transfer_once
        assert authority_outage_once
        assert partial_commit_blocked
        assert first["state"] == "RELEASED"
        assert second["state"] == "RELEASED"
        assert restarted
        assert daemon.status().coordinator_epoch != original_epoch
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
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


def test_lost_registration_response_replays_into_remote_agent_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        tmp_path / "runs",
        agent_policy=_policy(),
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
    remote_agent_root = _remote_agent_root(tmp_path)
    journal = remote_agent_root / "control.sqlite"
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            remote_agent_root,
        )
    )
    try:
        request = _request(client.handshake(), client.agent_root_id)
        original = client._call
        lose_once = {"register", "reconcile"}

        def lose_response(
            operation: str, value: Mapping[str, PlainData], *, role: str = "agent"
        ):
            result = original(operation, value, role=role)
            if operation in lose_once:
                lose_once.remove(operation)
                raise QueueServiceError("agent protocol outcome is indeterminate")
            return result

        monkeypatch.setattr(client, "_call", lose_response)
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.register(request)
        repaired = client.register(request)
        with sqlite3.connect(journal) as conn:
            persisted_request, first_secret = conn.execute(
                "SELECT request_json, retirement_secret FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()
            assert conn.execute(
                "SELECT result_json FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()[0]
            assert (
                conn.execute("SELECT session_id FROM agent_sessions_local").fetchone()[
                    0
                ]
                == repaired.session_id
            )
        assert first_secret is not None and len(str(first_secret)) == 64
        assert "retirement_verifier" in str(persisted_request)
        with sqlite3.connect(config.control_database) as conn:
            verifier = conn.execute(
                "SELECT retirement_verifier FROM agent_sessions WHERE session_id = ?",
                (repaired.session_id,),
            ).fetchone()[0]
        assert str(first_secret) not in str(verifier)
        with sqlite3.connect(config.agent_root / "control.sqlite") as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_sessions_local").fetchone()[0]
                == 0
            )

        daemon.stop()
        daemon.start()
        current = client.handshake()
        current_epoch = str(current["coordinator_epoch"])
        assert current_epoch != repaired.coordinator_epoch
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.reconcile(
                repaired.session_id,
                current_epoch,
                idempotency_key="reconcile-1",
            )
        resumed = client.reconcile(
            repaired.session_id,
            current_epoch,
            idempotency_key="reconcile-1",
        )
        assert resumed.coordinator_epoch == current_epoch
        with sqlite3.connect(journal) as conn:
            stored = conn.execute(
                "SELECT value_json FROM agent_sessions_local WHERE session_id = ?",
                (resumed.session_id,),
            ).fetchone()[0]
        assert current_epoch in str(stored)

        replacement_root = _remote_agent_root(tmp_path, "replacement-owner")
        replacement = LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".key"),
                replacement_root,
            )
        )
        try:
            with pytest.raises(QueueServiceError, match="evidence is unavailable"):
                replacement.retire_clean(
                    repaired.session_id, idempotency_key="retire-lost-root"
                )
        finally:
            replacement.close()

        lose_once.add("retire")
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.retire_clean(resumed.session_id, idempotency_key="retire-first")
        with sqlite3.connect(journal) as conn:
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                == first_secret
            )
            assert (
                conn.execute(
                    "SELECT result_json FROM agent_mutation_intents "
                    "WHERE operation = 'retire' AND operation_id = 'retire-first'"
                ).fetchone()[0]
                is None
            )
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT state FROM agent_sessions WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                == AgentSessionState.RETIRED_CLEAN.value
            )

        client.retire_clean(resumed.session_id, idempotency_key="retire-first")
        with sqlite3.connect(journal) as conn:
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_registration_intents WHERE operation_id = ?",
                    (request.idempotency_key,),
                ).fetchone()[0]
                is None
            )
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                is None
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_retirement_proofs_local"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_mutation_intents WHERE operation = 'retire'"
                ).fetchone()[0]
                == 0
            )
        with sqlite3.connect(config.control_database) as conn:
            coordinator_dump = "\n".join(conn.iterdump())
        assert str(first_secret) not in coordinator_dump

        second = client.register(
            replace(
                _request(current, client.agent_root_id), idempotency_key="register-2"
            )
        )
        with sqlite3.connect(journal) as conn:
            second_secret = conn.execute(
                "SELECT retirement_secret FROM agent_registration_intents WHERE operation_id = 'register-2'"
            ).fetchone()[0]
        assert second_secret is not None and second_secret != first_secret
        proof = client._journal.fence_and_prove_empty(second.session_id)  # type: ignore[union-attr]
        before = _sqlite_dump(config.control_database)
        missing_secret = proof.value()
        del missing_secret["retirement_secret"]
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client._call(
                "retire",
                {"proof": missing_secret, "idempotency_key": "retire-missing-secret"},
            )
        assert _sqlite_dump(config.control_database) == before
        with pytest.raises(QueueServiceError, match="proof is invalid"):
            daemon.agent_view(
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).retire_clean(
                replace(proof, retirement_secret=str(first_secret)),
                idempotency_key="retire-old-secret",
            )
        assert _sqlite_dump(config.control_database) == before
        client.retire_clean(second.session_id, idempotency_key="retire-second")

        missing_root = tmp_path / "missing-agent-root"
        with pytest.raises(QueueServiceError, match="root is missing"):
            LocalDaemonAgentHttpClient(
                AgentTlsClientConfig(
                    f"https://localhost:{server.port}",
                    credentials["ca"].with_suffix(".crt"),
                    credentials["agent"].with_suffix(".crt"),
                    credentials["agent"].with_suffix(".key"),
                    missing_root,
                )
            )
        assert not missing_root.exists()
    finally:
        client.close()
        server.stop()
        daemon.stop()


def test_loopback_rejects_unmapped_client_certificate_and_wrong_service_ca(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        agent_policy=policy,
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
    rejected = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    wrong_ca = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["server"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    wrong_service = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://127.0.0.1:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            rejected.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_ca.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_service.handshake()
    finally:
        rejected.close()
        wrong_ca.close()
        wrong_service.close()
        server.stop()
        daemon.stop()


def test_loopback_exposes_client_and_operator_views_only_to_configured_roles(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        agent_policy=policy,
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
                ): "agent-credential",
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "client-credential",
            },
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    agent = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        handshake = client.handshake(role="client")
        assert handshake["role"] == "client"
        assert handshake["capabilities"] in (
            ("authenticated-application-v1",),
            ["authenticated-application-v1"],
        )
        remote_status = client.call_application("client", "status", {})
        direct_status = (
            daemon.client_view(
                LocalDaemonPrincipal(
                    "client-principal", LocalDaemonRole.CLIENT, "client-credential"
                )
            )
            .status()
            .to_dict()
        )
        assert remote_status["coordinator_id"] == direct_status["coordinator_id"]
        assert remote_status["coordinator_epoch"] == direct_status["coordinator_epoch"]
        assert remote_status["admissions"] in ((), [])
        assert direct_status["admissions"] == []
        daemon.replace_agent_policy(
            AgentPolicyConfig(revision="policy-2", agents=policy.agents)
        )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client.handshake(role="client")
        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-3",
                agents=policy.agents,
                principals=(
                    TransportPrincipalPolicy(
                        "client-credential", "operator-principal", "operator"
                    ),
                ),
            )
        )
        operator_handshake = client.handshake(role="operator")
        assert operator_handshake["role"] == "operator"
        remote_operator = client.call_application("operator", "status", {})
        direct_operator = (
            daemon.operator_view(
                LocalDaemonPrincipal(
                    "operator-principal",
                    LocalDaemonRole.OPERATOR,
                    "client-credential",
                )
            )
            .status()
            .to_dict()
        )
        assert remote_operator["coordinator_id"] == direct_operator["coordinator_id"]
        assert client.call_application("operator", "reconcile", {})["admissions"] in (
            (),
            [],
        )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.handshake(role="client")
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.call_application("client", "status", {})
    finally:
        client.close()
        agent.close()
        server.stop()
        daemon.stop()
