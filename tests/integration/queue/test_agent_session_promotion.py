"""Agent role reload, capacity changes, and profile promotion boundaries."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
import socket
import ssl
import sqlite3
import sys
from collections.abc import Mapping

import pytest

from loom.queue._managed_local import (
    AssignmentState,
    ClaimCommand,
    GpuResourceProvider,
    ManagedAssignment,
)
from loom.queue import (
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonConfig,
)
from loom.queue._remote_stage_execution import (
    AgentResourceInventory,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentRegistration,
    AgentSession,
    AgentSessionState,
)
from loom.queue.errors import QueueConflictError, QueueError, QueueServiceError
from loom.scheduling import (
    ExactQuantity,
    ResourceClaim,
)
from loom.serialization import PlainData
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.agent_sessions import (
    _shutdown_detached_remote_supervisors as _shutdown_detached_remote_supervisors,
    _fresh_remote_agent_root,
    _local_launch_profile,
    _policy,
    _remote_agent_root,
    _request,
)


def test_agent_listener_prepares_tls_rotation_before_atomic_install(
    tmp_path: Path,
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
    daemon = LocalDaemon(config)
    daemon.start()
    initial = AgentTlsServerConfig(
        "localhost",
        0,
        credentials["server"].with_suffix(".crt"),
        credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"),
        {_fingerprint(credentials["agent"].with_suffix(".crt")): ("agent-credential")},
    )
    server = LocalDaemonAgentHttpServer(daemon, initial)
    server.start()
    try:
        assert _server_peer_fingerprint(server.port, credentials) == _fingerprint(
            credentials["server"].with_suffix(".crt")
        )
        invalid = replace(
            initial,
            certificate_path=tmp_path / "missing.crt",
            private_key_path=tmp_path / "missing.key",
        )
        with pytest.raises(OSError):
            server.prepare_reload(invalid)
        assert _server_peer_fingerprint(server.port, credentials) == _fingerprint(
            credentials["server"].with_suffix(".crt")
        )

        install = server.prepare_reload(
            replace(
                initial,
                certificate_path=credentials["server-next"].with_suffix(".crt"),
                private_key_path=credentials["server-next"].with_suffix(".key"),
            )
        )
        assert _server_peer_fingerprint(server.port, credentials) == _fingerprint(
            credentials["server"].with_suffix(".crt")
        )
        install()
        assert _server_peer_fingerprint(server.port, credentials) == _fingerprint(
            credentials["server-next"].with_suffix(".crt")
        )
    finally:
        server.stop()
        daemon.stop()


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
        assert client._require_journal().availability_drained() is True
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
        assert client._require_journal().availability_drained() is False
    finally:
        client.close()


@pytest.mark.parametrize("declaration", ["programmatic", "bound", "clear-bound"])
def test_agent_reload_recovers_crash_after_bound_replacement(
    tmp_path: Path,
    declaration: str,
) -> None:
    from loom.queue.resident_readiness import qualified_resident_profile
    from loom.queue.retirement import read_agent_declaration_binding
    root = _fresh_remote_agent_root(tmp_path)
    profile = ResidentExecutionProfile(
        descriptor=ResidentProfileDescriptor(
            "python", "1", "project-1", "environment-1", "executor-1"
        ),
        project_root=tmp_path,
        python_executable=Path(sys.executable),
    )
    if declaration != "programmatic":
        profile = qualified_resident_profile(profile)
    base = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=root,
        resident_profiles=(profile,),
        deployment_configuration_fingerprint="1" * 64,
        active_configuration_fingerprint="1" * 64,
        declaration_digest=None if declaration == "programmatic" else "a" * 64,
    )
    replacement = replace(
        base, active_configuration_fingerprint="2" * 64,
        declaration_digest="b" * 64 if declaration == "bound" else None,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(base)
    before = read_agent_declaration_binding(root, "a" * 64)
    assert (before is None) is (declaration == "programmatic")
    client = LocalDaemonAgentHttpClient(base, trusted_config_loader=lambda: replacement)
    registration = AgentRegistration(
        idempotency_key="register-crash-reload",
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
        session_id="session-crash-reload",
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
    control = AgentControl(
        operation_id="reload-agent-crash-boundary",
        kind=AgentControlKind.RELOAD,
        agent_id="agent-a",
        expected_session_id=session.session_id,
        expected_config_revision=session.config_revision,
        pool=None,
        cancel_active=False,
        reason="recover accepted replacement",
    )
    plan = client._prepare_agent_reload()  # noqa: SLF001 - exact crash boundary
    assert (
        client._require_journal().prepare_control(
            control, replacement_fingerprint=plan.active_fingerprint
        )
        is None
    )
    client.close()  # Process loss before complete_reload leaves the bound intent.
    if before is not None:
        with pytest.raises(QueueError, match="pending agent reload"):
            read_agent_declaration_binding(root, "a" * 64)

    recovered = LocalDaemonAgentHttpClient(replacement)
    try:
        retained = recovered._require_journal().next_unacknowledged_control()
        assert retained is not None
        retained_control, effect = retained
        assert retained_control == control
        assert effect.code == "applied"
        active_session = recovered.active_session()
        assert active_session is not None
        assert active_session.config_revision == effect.config_revision
        assert recovered._require_journal().availability_drained() is True
        with sqlite3.connect(root / "control.sqlite") as conn:
            metadata = dict(
                conn.execute(
                    "SELECT key, value FROM root_metadata WHERE key IN "
                    "('active_configuration_revision', "
                    "'active_configuration_fingerprint')"
                )
            )
        assert metadata == {
            "active_configuration_revision": "2",
            "active_configuration_fingerprint": "2" * 64,
        }
        after = read_agent_declaration_binding(root, "b" * 64)
        if declaration == "bound":
            assert after is not None and before is not None
            assert after.root_id == before.root_id
            assert after.active_configuration_revision == 2
            assert after.active_fingerprint == "2" * 64
            assert after.declaration_digest == "b" * 64
        else:
            assert after is None
        recovered._require_journal().complete_reload(control, replacement, effect)
        assert read_agent_declaration_binding(root, "b" * 64) == after
        recovered.shutdown_clean()
    finally:
        recovered.close()


@pytest.mark.parametrize("change", ["resources", "ceiling", "slurm-pacing", "slurm-observation", "slurm-batching"])
def test_agent_reload_allows_idle_capacity_change_but_not_retained_reinterpretation(
    tmp_path: Path,
    change: str,
) -> None:
    from loom.queue._slurm_observation import SlurmObservationPolicy

    root = _fresh_remote_agent_root(tmp_path)
    original = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "python", "1", "project-1", "environment-1", "executor-1"
        ),
        tmp_path,
        Path(sys.executable),
        cpu_capacity=1,
    )
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
    replacement = (
        replace(base, resident_profiles=(replace(original, cpu_capacity=2),))
        if change == "resources"
        else replace(base, slurm_submit_interval_seconds=1.0)
        if change == "slurm-pacing"
        else replace(base, slurm_observation_policy=SlurmObservationPolicy(300))
        if change == "slurm-observation"
        else replace(base, slurm_observation_policy=SlurmObservationPolicy(300, 8, 4, 10))
        if change == "slurm-batching"
        else replace(base, max_concurrent_assignments=2)
    )
    try:
        client._validate_reload_config(  # noqa: SLF001 - exact reload boundary
            replacement, retained_work=False
        )
        with pytest.raises(QueueConflictError, match="retained work"):
            client._validate_reload_config(  # noqa: SLF001 - exact reload boundary
                replacement, retained_work=True
            )
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
    with pytest.raises(QueueServiceError, match="configuration changed without reload"):
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


def test_agent_resource_inventory_overrides_profile_capacity_as_one_domain(
    tmp_path: Path,
) -> None:
    first = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "first", "1", "project-1", "environment-1", "executor-1"
        ),
        tmp_path,
        Path(sys.executable),
        cpu_capacity=1,
    )
    second = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "second", "1", "project-2", "environment-2", "executor-2"
        ),
        tmp_path,
        Path(sys.executable),
        cpu_capacity=9,
    )

    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        agent_root=tmp_path / "agent",
        resident_profiles=(first, second),
        resource_inventory=AgentResourceInventory(cpu_capacity=4),
    )

    assert config.capacity_profile.cpu_capacity == 4
    assert config.capacity_profile.descriptor == first.descriptor


@pytest.mark.parametrize("cpu,memory,accepted", ((8, 8, 8), (4, 8, 4), (8, 4, 4)))
def test_shared_inventory_prepares_competing_profile_claims(
    tmp_path: Path, cpu: int, memory: int, accepted: int
) -> None:
    profiles = tuple(
        ResidentExecutionProfile(
            ResidentProfileDescriptor(name, "1", name, "environment", "executor"),
            tmp_path,
            Path(sys.executable),
            cpu_capacity=index + 1,
        )
        for index, name in enumerate(("first", "second"))
    )
    inventory = AgentResourceInventory(
        cpu,
        memory,
        tuple(
            ResidentGpuDevice(
                GpuDeviceDescriptor(f"GPU-{index}", "synthetic", 1024), f"GPU-{index}"
            )
            for index in range(8)
        ),
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        profiles,
        resource_inventory=inventory,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    session = AgentSession(
        "session",
        "coordinator",
        "epoch",
        "agent",
        client.agent_root_id,
        "policy",
        "config",
        "inventory",
        "availability",
        (),
        ("default",),
        AgentSessionState.ACTIVE,
    )
    held: list[tuple[ManagedAssignment, tuple[ClaimCommand, ...]]] = []
    try:
        providers, journal = client._runtime_owners(session)
        capacity = {
            atom.local_capacity_key: atom
            for atom in config.capacity_profile.capacity_atoms("agent")
        }
        for index in range(accepted + 1):
            profile = profiles[index % len(profiles)]
            assert client._profile_for_descriptor(profile.descriptor) == profile
            current, current_journal = client._runtime_owners(session)
            assignment = ManagedAssignment(
                f"assignment-{index}",
                f"run-{index}",
                f"work-{index}",
                profile.descriptor.profile_id,
                1,
                f"attempt-{index}",
                "agent",
                session.session_id,
                f"offer-{index}",
                f"claim-{index}",
            )
            selected = (
                replace(capacity["agent:cpu"], amount=ExactQuantity(1)),
                replace(capacity["agent:memory"], amount=ExactQuantity(1)),
                capacity[f"agent:GPU-{index % 8}"],
            )
            commands = tuple(
                ClaimCommand(
                    assignment,
                    f"prepare-{index}-{atom.owner_resource_kind}",
                    ResourceClaim(
                        atom.owner_resource_kind,
                        providers[atom.owner_resource_kind].claim_contracts[0],
                        (atom,),
                        1,
                    ),
                    providers[atom.owner_resource_kind].descriptor,
                )
                for atom in selected
            )
            current_journal.persist_request(
                assignment, {"profile": profile.descriptor.to_dict()}
            )
            state = current_journal.prepare_composite(assignment, commands, current)
            if index < accepted:
                assert state is AssignmentState.PREPARED
                held.append((assignment, commands))
            else:
                assert state is AssignmentState.DECLINED
                journal.release_declined(assignment.assignment_id, "after-decline")
        held_gpus = [
            atom.local_capacity_key
            for _, commands in held
            for command in commands
            if command.claim.resource_kind == "gpu"
            for atom in command.claim.atoms
        ]
        assert len(set(held_gpus)) == accepted
        assert {item.stage_name for item, _ in held} == {"first", "second"}
        for assignment, commands in held:
            journal.abort_pregrant(assignment.assignment_id, commands, providers)
            journal.release_declined(assignment.assignment_id, "after-abort")
        assert journal.retained_claim_commands() == ()
    finally:
        if client._supervisor is not None:
            client._supervisor.shutdown_for_test()
        client.close()


def test_agent_policy_reload_rebuilds_the_shared_gpu_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.queue.gpu.occupancy import (
        GpuOccupancyPolicy,
        GpuProcessObservation,
        NvidiaSmiGpuProcessObserver,
    )

    queried: list[GpuOccupancyPolicy] = []

    def observe(observer: NvidiaSmiGpuProcessObserver):
        queried.append(observer.policy)
        return {
            uuid: GpuProcessObservation(uuid, True, False, "available")
            for uuid in observer.selected_uuids
        }

    monkeypatch.setattr(NvidiaSmiGpuProcessObserver, "observe", observe)
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident", "v1", "project", "environment", "executor"
        ),
        tmp_path,
        Path(sys.executable),
        gpu_devices=(
            ResidentGpuDevice(
                GpuDeviceDescriptor("gpu-0", "model", 1024), "GPU-private"
            ),
        ),
    )
    base = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        (profile,),
        gpu_occupancy_policy=GpuOccupancyPolicy(),
    )
    changed_policy = GpuOccupancyPolicy(external_process_policy="allow")
    replacement = replace(base, gpu_occupancy_policy=changed_policy)
    LocalDaemonAgentHttpClient.initialize_agent_root(base)
    client = LocalDaemonAgentHttpClient(base, trusted_config_loader=lambda: replacement)
    try:
        journal = client._require_journal()
        registration = journal.persist_registration_intent(
            _request(
                {"coordinator_id": "coordinator", "coordinator_epoch": "epoch"},
                client.agent_root_id,
            )
        )
        session = AgentSession(
            "session",
            "coordinator",
            "epoch",
            "agent-a",
            client.agent_root_id,
            "policy-1",
            "config-1",
            "inventory-1",
            "availability-1",
            ("python",),
            ("default",),
            AgentSessionState.ACTIVE,
        )
        journal.persist_session(
            registration.idempotency_key, registration.value(), session
        )
        providers = client._provider_composition("agent-a", profile)
        original = providers["gpu"]
        assert isinstance(original, GpuResourceProvider)
        original.refresh_occupancy(force=True)
        assert queried[-1] == GpuOccupancyPolicy()
        reload_control = AgentControl(
            "gpu-policy-reload",
            AgentControlKind.RELOAD,
            "agent-a",
            session.session_id,
            session.config_revision,
            None,
            False,
            "change monitoring cadence",
        )
        journal.prepare_control(reload_control)
        effect = client._apply_agent_control(reload_control)
        journal.record_control_effect(reload_control, effect)
        assert effect.code == "applied"
        assert journal.availability_drained()
        active = client.active_session()
        assert active is not None
        resume_control = AgentControl(
            "gpu-policy-resume",
            AgentControlKind.RESUME,
            "agent-a",
            active.session_id,
            active.config_revision,
            None,
            False,
            "resume after monitoring reload",
        )
        journal.prepare_control(resume_control)
        resumed = client._apply_agent_control(resume_control)
        journal.record_control_effect(resume_control, resumed)
        assert resumed.code == "applied"
        installed = client._provider_composition("agent-a", profile)["gpu"]
        assert isinstance(installed, GpuResourceProvider)
        assert installed is not original
        installed.refresh_occupancy(force=True)
        assert queried[-1] == changed_policy
        assert client._provider_composition("agent-a", profile)["gpu"] is installed
    finally:
        client.shutdown_clean()
        client.close()


def _server_peer_fingerprint(port: int, credentials: Mapping[str, Path]) -> str:
    context = ssl.create_default_context(
        cafile=str(credentials["ca"].with_suffix(".crt"))
    )
    context.load_cert_chain(
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
    )
    with socket.create_connection(("localhost", port), timeout=2.0) as connection:
        with context.wrap_socket(connection, server_hostname="localhost") as secured:
            certificate = secured.getpeercert(binary_form=True)
    assert certificate is not None
    return hashlib.sha256(certificate).hexdigest()
