"""Real loopback mutual-TLS evidence for the restricted agent protocol."""

from __future__ import annotations

from contextlib import suppress
import hashlib
import json
from multiprocessing import get_context
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import ssl
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any, cast

import pytest

import loom.queue.local_daemon_execution as local_daemon_execution
from loom.pipeline import PipelineSpec
from loom.queue._managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    GpuResourceProvider,
    ManagedAssignment,
    ManagedOfferSnapshot,
    SQLiteAgentJournal,
    _configured_provider_descriptor,
)
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import (
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
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
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
    ResidentWorkerLaunchProfile,
    SessionReplacementRequest,
    prepare_managed_local_runtime_record,
)
from loom.queue._agent_process_supervisor import (
    ResidentWorkerLaunch,
    SupervisorReceipt,
)
from loom.queue._remote_stage_execution import (
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
    _decode,
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
    AgentProviderDescriptor,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSession,
    AgentSessionState,
    AgentTransferAuthorizationStaleError,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueConflictError, QueueError, QueueServiceError
from loom.scheduling import (
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, json_dumps_pretty


def _local_launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        Path.cwd(),
        Path(sys.executable),
        ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _execution_requirements(pipeline: PipelineSpec) -> dict[str, ExecutionRequirement]:
    return {
        stage_name: ExecutionRequirement(
            "test-project", "test-environment", "test-executor"
        )
        for stage_name in pipeline.stage_names
    }


def _provider_descriptors(*kinds: str) -> tuple[AgentProviderDescriptor, ...]:
    return tuple(
        AgentProviderDescriptor(
            SchedulingComponentDescriptor(
                kind, 1, "1", f"test-{kind}-provider", f"{kind}-configuration"
            ),
            (ResourceClaimContractDescriptor(kind, 1, f"builtin-{kind}-claim-v1"),),
        )
        for kind in sorted(kinds)
    )


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


def test_outbound_service_registers_offers_and_stops_cleanly(tmp_path: Path) -> None:
    credentials = _credentials(tmp_path / "tls")
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
    daemon_config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
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
        ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        ),
        Path(__file__).resolve().parents[3],
        Path(sys.executable),
    )
    client_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
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
            capabilities,
        ),
        0.01,
        tmp_path / "agent.yaml",
    )
    stop = Event()
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
    finally:
        stop.set()
        thread.join(timeout=7)
        server.stop()
        daemon.stop()
    assert not thread.is_alive()
    assert failure == []


def _remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    root = tmp_path / name / "agent"
    LocalDaemon.initialize_agent_root(root)
    return root


def _fresh_remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    """Return a path for the explicit profile-set remote initializer."""
    root = tmp_path / name / "agent"
    root.parent.mkdir(parents=True, exist_ok=True)
    return root


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
            original_launch = supervisor.launch

            def interrupt_launch(launch: ResidentWorkerLaunch) -> SupervisorReceipt:
                if barrier == "before_supervisor_accept":
                    raise RuntimeError("simulated fresh agent application restart")
                original_launch(launch)
                raise RuntimeError("simulated fresh agent application restart")

            setattr(cast(Any, supervisor), "launch", interrupt_launch)
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
            agent.execute_one(
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=5_000,
            )
        except RuntimeError as exc:
            queue.put(("crashed", os.getpid(), str(exc), supervisor.supervisor_id))
            return
        queue.put(("unexpected_completion", os.getpid()))
    except Exception as exc:  # pragma: no cover - surfaced by the parent assertion
        queue.put(("error", os.getpid(), repr(exc)))
    finally:
        agent.close()


def _reconcile_remote_agent_application(
    config: AgentTlsClientConfig,
    session_id: str,
    events: object,
) -> None:
    """Run application B in another interpreter and replay the retained work."""

    queue = cast(Any, events)
    agent = LocalDaemonAgentHttpClient(config)
    try:
        session = agent._require_journal().session(session_id)  # noqa: SLF001
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
        blocked_offer = blocked_poll = False
        try:
            agent.publish_offer(offer, idempotency_key="offer-before-fresh-replay")
        except QueueConflictError:
            blocked_offer = True
        try:
            agent.wait_for_work(
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=1,
            )
        except QueueConflictError:
            blocked_poll = True
        replayed = agent.resume_retained_work()
        released = agent._require_journal().session(session_id)  # noqa: SLF001
        agent.publish_offer(
            AgentOffer(
                released.session_id,
                released.coordinator_epoch,
                released.config_revision,
                released.inventory_revision,
                released.availability_revision,
                1,
                0,
                30,
                _resident_provider_descriptors(profile, released.agent_id),
                resident_profiles=(profile.descriptor,),
            ),
            idempotency_key="offer-after-fresh-replay",
        )
        supervisor = agent._supervisor  # noqa: SLF001 - continuity assertion
        assert supervisor is not None
        queue.put(
            (
                "replayed",
                os.getpid(),
                blocked_offer,
                blocked_poll,
                tuple(item["state"] for item in replayed),
                supervisor.supervisor_id,
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced by the parent assertion
        queue.put(("error", os.getpid(), repr(exc)))
    finally:
        agent.close()


@pytest.fixture(autouse=True)
def _shutdown_detached_remote_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Every integration test that initializes a detached owner also stops it."""

    initialized: list[AgentTlsClientConfig] = []
    original = LocalDaemonAgentHttpClient.initialize_agent_root.__func__

    def initialize(
        cls: type[LocalDaemonAgentHttpClient], config: AgentTlsClientConfig
    ) -> None:
        original(cls, config)
        initialized.append(config)

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "initialize_agent_root", classmethod(initialize)
    )
    yield
    for config in initialized:
        with suppress(QueueError):
            client = LocalDaemonAgentHttpClient(config)
            try:
                assert client._supervisor is not None  # noqa: SLF001
                client._supervisor.shutdown_for_test()  # noqa: SLF001
            finally:
                client.close()


def test_agent_reload_rejects_profile_set_addition_and_requires_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _remote_agent_root(tmp_path)
    base = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=root,
    )
    profile = ResidentExecutionProfile(
        descriptor=ResidentProfileDescriptor(
            "python", "2", "project-2", "environment-2", "executor-2"
        ),
        project_root=tmp_path,
        python_executable=Path(sys.executable),
    )
    replacement = replace(base, resident_profiles=(profile,))
    client = LocalDaemonAgentHttpClient(base, trusted_config_loader=lambda: replacement)
    try:
        registration = AgentRegistration(
            idempotency_key="register-local-control",
            coordinator_id="coordinator-a",
            coordinator_epoch="coordinator-epoch-a",
            agent_root_id=client.agent_root_id,
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            declared_pools=("default",),
        )
        persisted = client._require_journal().persist_registration_intent(registration)
        session = AgentSession(
            session_id="session-a",
            coordinator_id="coordinator-a",
            coordinator_epoch="coordinator-epoch-a",
            agent_id="agent-a",
            agent_root_id=client.agent_root_id,
            policy_revision="policy-1",
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            capabilities=("python",),
            pools=("default",),
            state=AgentSessionState.ACTIVE,
        )
        client._require_journal().persist_session(
            persisted.idempotency_key, persisted.value(), session
        )

        reload_control = AgentControl(
            operation_id="reload-agent-1",
            kind=AgentControlKind.RELOAD,
            agent_id="agent-a",
            expected_session_id="session-a",
            expected_config_revision="config-1",
            pool=None,
            cancel_active=False,
            reason="trusted config changed",
        )
        assert client._require_journal().prepare_control(reload_control) is None
        effect = client._apply_agent_control(reload_control)
        client._require_journal().record_control_effect(reload_control, effect)
        assert effect.code == "reload_rejected"
        assert effect.config_revision == "config-1"
        assert client._drained is True
        assert client._config is base  # noqa: SLF001 - rejected reload has no swap
        assert client._profiles == {}  # noqa: SLF001 - no profile can be added live
        acknowledgements: list[Mapping[str, PlainData]] = []

        def acknowledge(
            operation: str,
            value: Mapping[str, PlainData],
            *,
            role: str = "agent",
        ) -> Mapping[str, PlainData]:
            assert operation == "control_ack"
            assert role == "agent"
            acknowledgements.append(value)
            return {"state": "applied"}

        monkeypatch.setattr(client, "_call", acknowledge)
        assert client.poll_control(session.session_id) == reload_control
        assert len(acknowledgements) == 1
        with sqlite3.connect(root / "control.sqlite") as conn:
            assert (
                conn.execute(
                    "SELECT acknowledged FROM agent_controls_local "
                    "WHERE operation_id = ?",
                    (reload_control.operation_id,),
                ).fetchone()[0]
                == 1
            )

        resume = AgentControl(
            operation_id="resume-agent-1",
            kind=AgentControlKind.RESUME,
            agent_id="agent-a",
            expected_session_id="session-a",
            expected_config_revision=effect.config_revision,
            pool=None,
            cancel_active=False,
            reason="validated replacement",
        )
        assert client._require_journal().prepare_control(resume) is None
        resumed = client._apply_agent_control(resume)
        client._require_journal().record_control_effect(resume, resumed)
        assert resumed.code == "applied"
        assert client._drained is False
    finally:
        client.close()


def test_agent_reload_requires_fresh_root_for_changed_launch_profile_set(
    tmp_path: Path,
) -> None:
    root = _fresh_remote_agent_root(tmp_path)
    descriptor = ResidentProfileDescriptor(
        "python", "1", "project-1", "environment-1", "executor-1"
    )
    original = ResidentExecutionProfile(
        descriptor=descriptor,
        project_root=tmp_path,
        python_executable=Path(sys.executable),
        cpu_capacity=1,
    )
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    changed = replace(original, project_root=other_project)
    base = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=root,
        resident_profiles=(original,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(base)
    client = LocalDaemonAgentHttpClient(base)
    try:
        with pytest.raises(
            QueueConflictError, match="requires fresh agent-root initialization"
        ):
            client._validate_reload_config(replace(base, resident_profiles=(changed,)))
    finally:
        client.close()


def test_agent_open_rejects_durable_supervisor_without_profiles_without_locking_root(
    tmp_path: Path,
) -> None:
    root = _fresh_remote_agent_root(tmp_path)
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "python", "1", "project-1", "environment-1", "executor-1"
        ),
        tmp_path,
        Path(sys.executable),
        cpu_capacity=1,
    )
    configured = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=root,
        resident_profiles=(profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(configured)
    with pytest.raises(
        QueueServiceError, match="managed_supervisor_state_requires_reinitialization"
    ):
        LocalDaemonAgentHttpClient(replace(configured, resident_profiles=()))

    reopened = LocalDaemonAgentHttpClient(configured)
    try:
        supervisor = reopened._supervisor  # noqa: SLF001 - root reopening proof
        assert supervisor is not None
        supervisor.shutdown_for_test()
    finally:
        reopened.close()

    no_profile_root = tmp_path / "no-profile-agent"
    LocalDaemon.initialize_agent_root(no_profile_root)
    no_profile = LocalDaemonAgentHttpClient(
        replace(configured, agent_root=no_profile_root, resident_profiles=())
    )
    no_profile.close()


def test_agent_reload_canonicalizes_bound_profile_set_without_update_path(
    tmp_path: Path,
) -> None:
    root = _fresh_remote_agent_root(tmp_path)
    first_descriptor = ResidentProfileDescriptor(
        "first", "1", "project-1", "environment-1", "executor-1"
    )
    second_descriptor = ResidentProfileDescriptor(
        "second", "1", "project-2", "environment-2", "executor-2"
    )
    first = ResidentExecutionProfile(
        first_descriptor, tmp_path, Path(sys.executable), cpu_capacity=1
    )
    second = ResidentExecutionProfile(
        second_descriptor, tmp_path, Path(sys.executable), cpu_capacity=1
    )
    base = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=root,
        resident_profiles=(first, second),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(base)
    client = LocalDaemonAgentHttpClient(base)
    try:
        client._validate_reload_config(  # noqa: SLF001 - reload boundary contract
            replace(base, resident_profiles=(second, first))
        )
        third = replace(
            second,
            descriptor=ResidentProfileDescriptor(
                "third", "1", "project-3", "environment-3", "executor-3"
            ),
        )
        for replacement in (
            replace(base, resident_profiles=(first,)),
            replace(base, resident_profiles=(first, second, third)),
        ):
            with pytest.raises(
                QueueConflictError, match="requires fresh agent-root initialization"
            ):
                client._validate_reload_config(replacement)  # noqa: SLF001
    finally:
        client.close()


def _prepare_remote_producer_run(
    store: LocalRunStore,
    *,
    run_name: str,
    machine_id: str,
    value: int,
    requirement: ExecutionRequirement | None = None,
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
                "placement": {"target": machine_id},
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
        execution_requirements={
            stage_name: (
                requirement
                or ExecutionRequirement(
                    "test-project", "test-environment", "test-executor"
                )
            )
            for stage_name in spec.stage_names
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


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
        run_store=store,
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


def _prepare_remote_sleep_run(
    store: LocalRunStore, *, run_name: str, machine_id: str
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": "slow",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {"seconds": 30},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": machine_id},
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
        {"executor": "local", "stages": {"slow": {"executor": "local"}}},
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
    return run_uri, authority


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
    operator = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
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
        with pytest.raises(QueueConflictError, match="agent protocol conflict"):
            operator.recover_unknown(active_request)
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


def _prepare_gpu_environment_run(
    store: LocalRunStore,
    *,
    run_name: str,
    preferred_models: tuple[str, ...],
    include_cpu_preprocess: bool = False,
    fallback_after_seconds: int | None = None,
    target: str | None = None,
    capture_requirement: ExecutionRequirement | None = None,
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    stages: list[dict[str, object]] = []
    if include_cpu_preprocess:
        stages.append(
            {
                "name": "preprocess",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages."
                        "EnvironmentProducerStage"
                    )
                },
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": "machine-A"},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        )
    preference: dict[str, object] = {
        "kind": "resource_attribute_order",
        "resource": "gpu",
        "attribute": "model",
        "values": list(preferred_models),
    }
    if fallback_after_seconds is not None:
        preference["fallback_after_seconds"] = fallback_after_seconds
    placement: dict[str, object] = {"preferences": [preference]}
    if target is not None:
        placement["target"] = target
    capture: dict[str, object] = {
        "name": "capture",
        "factory": {
            "_target_": (
                "tests.support.pipeline_execution_stages.EnvironmentProducerStage"
            )
        },
        "resources": {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 1,
                    "unit": "count",
                    "attributes": {"allocation_mode": "exclusive"},
                }
            }
        },
        "placement": placement,
        "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
    }
    if include_cpu_preprocess:
        capture["depends_on"] = ["preprocess"]
    stages.append(capture)
    pipeline_config = {
        "name": run_name,
        "stages": stages,
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
            "stages": {stage.name: {"executor": "local"} for stage in spec.stages},
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
            **_execution_requirements(spec),
            "capture": capture_requirement
            or ExecutionRequirement(
                "test-project", "test-environment", "test-executor"
            ),
        },
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
    provider_descriptor = _resident_provider_descriptors(profile, "agent-a")[
        0
    ].descriptor
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
                "cpu": AtomResourceProvider(
                    provider_descriptor,
                    planner.claim_contracts,
                    (atom,),
                )
            },
        )
        is AssignmentState.PREPARED
    )

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
    "restart_barrier",
    (
        "before_supervisor_accept",
        "after_supervisor_accept",
        "before_result_commit",
        "before_coordinator_release",
    ),
)
def test_agent_restart_joins_one_supervisor_and_replays_durable_remote_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restart_barrier: str
) -> None:
    """A fresh application joins one exact operation across every crash barrier."""

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
        run_name="restart-run",
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
            resident_profiles=(descriptor,),
        )
        agent.publish_offer(offer, idempotency_key="offer-restart")
        supervisor = agent._supervisor  # noqa: SLF001 - causal service boundary
        assert supervisor is not None
        if restart_barrier in {
            "before_supervisor_accept",
            "after_supervisor_accept",
        }:
            original_launch = supervisor.launch

            def interrupt_launch(value: ResidentWorkerLaunch) -> SupervisorReceipt:
                if restart_barrier == "before_supervisor_accept":
                    raise RuntimeError("simulated agent application restart")
                original_launch(value)
                raise RuntimeError("simulated agent application restart")

            monkeypatch.setattr(supervisor, "launch", interrupt_launch)
        elif restart_barrier == "before_result_commit":

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
                agent.execute_one,
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=5_000,
            )
            coordinator.submit(LocalDaemonAdmissionRequest("restart-item", run_uri))
            with pytest.raises(RuntimeError, match="application restart"):
                execution.result(timeout=20)
        supervisor_id = supervisor.supervisor_id
        agent.close()
        replacement = LocalDaemonAgentHttpClient(remote_config)
        replacement_supervisor = replacement._supervisor  # noqa: SLF001
        assert replacement_supervisor is not None
        assert replacement_supervisor.supervisor_id == supervisor_id
        with pytest.raises(QueueConflictError, match="cannot advertise"):
            replacement.publish_offer(offer, idempotency_key="offer-before-replay")
        (replayed,) = replacement.resume_retained_work()
        assert replayed["state"] == "RELEASED"
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
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
        assert (
            coordinator.wait("restart-item", timeout_seconds=10).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        assert authority.open_run(run_uri).status is RunStatus.SUCCEEDED
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
        crashed = events.get(timeout=20)
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
        requirement=ExecutionRequirement("project-1", "environment-1", "executor-1"),
    )
    run_b, authority_b = _prepare_remote_producer_run(
        store,
        run_name="remote-b",
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
                sequence=1,
                wait_timeout_ms=5_000,
            )
            execution_b = workers.submit(
                agent_b.execute_one,
                session_b.session_id,
                session_b.availability_revision,
                sequence=1,
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


def test_same_run_local_and_remote_stages_overlap(tmp_path: Path) -> None:
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
        with ThreadPoolExecutor(max_workers=1) as workers:
            remote = workers.submit(
                agent.execute_one,
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=5_000,
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
                if active_agent_ids == {"machine-A", "agent-a"}:
                    break
                sleep(0.01)
            assert active_agent_ids == {"machine-A", "agent-a"}
            assert remote.result(timeout=90)["state"] == "RELEASED"
        assert coordinator.wait("mixed-item", timeout_seconds=90).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
        assert authority.open_run(run_uri).status is RunStatus.SUCCEEDED
    finally:
        agent.close()
        server.stop()
        daemon.stop()


def test_gpu_model_preference_selects_exact_private_local_or_remote_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        preferred_models=("large", "small"),
        include_cpu_preprocess=True,
        capture_requirement=ExecutionRequirement(
            "project-1", "environment-1", "executor-1"
        ),
    )
    local_run, local_authority = _prepare_gpu_environment_run(
        store,
        run_name="local-model-preferred",
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
        agent_id: str, resident_profile: ResidentExecutionProfile
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
        assert remote_output["value"] == remote_binding
        assert local_output["value"] == local_binding
        assert preprocess_output["value"] is None
        assert preprocess_output["pid"] != os.getpid()
        assert remote_output["pid"] != os.getpid()
        assert local_output["pid"] != os.getpid()

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


def test_protocol_codec_rejects_duplicate_nonfinite_deep_and_oversized_json() -> None:
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":1,"value":2}')
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":NaN}')
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(b'{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":1}}}}}}}}}')
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(b"{" + b" " * 65_536 + b"}")


@pytest.mark.parametrize("old_version", ["5", "6"])
def test_agent_client_rejects_an_old_protocol_without_compatibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_version: str
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
            "protocol_version": old_version,
            "capabilities": [f"agent-sessions-v{old_version}"],
            "coordinator_id": "coordinator-1",
            "coordinator_epoch": "epoch-1",
            "role": "agent",
        }

    monkeypatch.setattr(client, "_call", old_handshake)
    with pytest.raises(QueueServiceError, match="hard cut-over"):
        client.handshake()


@pytest.mark.parametrize("old_version", [5, 6])
def test_agent_open_rejects_an_old_root_without_migration(
    tmp_path: Path, old_version: int
) -> None:
    root = tmp_path / f"version-{old_version}-agent"
    LocalDaemon.initialize_agent_root(root)
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute(f"PRAGMA user_version = {old_version}")

    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                "https://localhost:1",
                tmp_path / "ca.crt",
                tmp_path / "agent.crt",
                tmp_path / "agent.key",
                agent_root=root,
            )
        )


def test_loopback_mtls_derives_credential_and_rechecks_live_policy(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent-root",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_local_launch_profile(),
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
                _provider_descriptors("cpu", "memory"),
            ),
            idempotency_key="offer-1",
        )
        connection = client._connection
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                client.wait_for_work,
                registered.session_id,
                registered.availability_revision,
                sequence=1,
                wait_timeout_ms=1_000,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_poll_state "
                        "WHERE session_id = ? AND sequence = 1",
                        (registered.session_id,),
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
                    _provider_descriptors("cpu", "memory"),
                ),
                idempotency_key="offer-rotated-credential",
            )
            assert (
                rotated.wait_for_work(
                    resumed.session_id,
                    resumed.availability_revision,
                    sequence=2,
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
        execution_requirements={
            stage_name: ExecutionRequirement("project-1", "environment-1", "executor-1")
            for stage_name in spec.stage_names
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)

    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        run_root,
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
                _resident_provider_descriptors(profile, session.agent_id),
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
                sequence=1,
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
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-2",
            )
            execution = workers.submit(
                agent.execute_one,
                session.session_id,
                next_availability,
                sequence=2,
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
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(descriptor,),
                ),
                idempotency_key="offer-remote-3",
            )
            execution = workers.submit(
                agent.execute_one,
                session.session_id,
                next_availability,
                sequence=3,
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
        _local_launch_profile(),
        agent_policy=_policy(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, clock=lambda: "2020-01-01T00:00:00Z")
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
        _local_launch_profile(),
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


def test_loopback_operator_scope_denial_matches_direct_before_persistence(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator-principal",
                "operator",
                actions=("drain",),
                agent_ids=("another-agent",),
                pools=("default",),
            ),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
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
                _fingerprint(credentials["agent"].with_suffix(".crt")): (
                    "agent-credential"
                ),
                _fingerprint(credentials["other"].with_suffix(".crt")): (
                    "operator-credential"
                ),
            },
        ),
    )
    server.start()
    agent = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            _remote_agent_root(tmp_path),
        )
    )
    operator = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    try:
        handshake = agent.handshake()
        session = agent.register(_request(handshake, agent.agent_root_id))
        control = AgentControl(
            operation_id="denied-control",
            kind=AgentControlKind.DRAIN,
            agent_id=session.agent_id,
            expected_session_id=session.session_id,
            expected_config_revision=session.config_revision,
            pool="default",
            cancel_active=False,
            reason="outside exact agent scope",
        )
        direct = daemon.operator_view(
            LocalDaemonPrincipal(
                "operator-principal",
                LocalDaemonRole.OPERATOR,
                "operator-credential",
            )
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            direct.control_agent(control)
        operator.handshake(role="operator")
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            operator.control_agent(control)
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_controls").fetchone()[0] == 0
            )
    finally:
        agent.close()
        operator.close()
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
        _local_launch_profile(),
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
        assert remote_status["active_admissions"] == 0
        assert remote_status["waiting_admissions"] == 0
        assert direct_status["active_admissions"] == 0
        assert direct_status["waiting_admissions"] == 0
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


def test_loopback_maps_slurm_certificate_only_to_fixed_bootstrap_role(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    profile = SlurmReadyStageProfile(
        profile_id="training",
        partition="gpu",
        max_outstanding=1,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=FakeSlurmCommandRunner(),
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference="slurm-credential",
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="project-v1",
        environment_fingerprint="environment-v1",
        executor_fingerprint="executor-v1",
        job_private_file_provider=SlurmJobPrivateFileProvider(
            fixed_path=str(tmp_path / "capability"),
            descriptor="fake-prolog-v1",
            helper_argv=(
                sys.executable,
                str(
                    Path(__file__).parents[2]
                    / "support"
                    / "slurm_job_private_helper.py"
                ),
            ),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        slurm_profiles=(profile,),
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
                    credentials["other"].with_suffix(".crt")
                ): "slurm-credential"
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
    try:
        handshake = client.handshake(role="slurm_bootstrap")
        assert handshake["role"] == "slurm_bootstrap"
        assert handshake["profile_id"] == "training"
        assert handshake["credential_policy_revision"] == "slurm-policy-1"
        capabilities = handshake["capabilities"]
        assert isinstance(capabilities, (list, tuple))
        assert "slurm-ready-stage-bootstrap-v1" in capabilities
        with pytest.raises(QueueServiceError, match="role-exclusive"):
            daemon.replace_agent_policy(
                AgentPolicyConfig(
                    agents=(
                        AgentPrincipalPolicy(
                            "slurm-credential",
                            "agent-principal",
                            "agent-a",
                            ("default",),
                            ("python",),
                        ),
                    )
                )
            )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client.handshake(role="client")
    finally:
        client.close()
        server.stop()
        daemon.stop()
