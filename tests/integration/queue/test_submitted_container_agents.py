"""Native agent capacity and delivery without an installed scientific profile."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from loom.pipeline.planning import StageFingerprintRecord
from loom.queue import GpuDeviceDescriptor, LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue._managed_local import AssignmentState, ClaimCommand, ManagedAssignment
from loom.queue._remote_stage_execution import AgentResourceInventory, ResidentExecutionProfile, ResidentGpuDevice, ResidentProfileDescriptor
from loom.queue._shared_assignment import publish
from loom.queue.agent_session_transport import AgentTlsClientConfig, LocalDaemonAgentHttpClient, _resident_provider_descriptors
from loom.queue.agent_sessions import AgentOffer, AgentPolicyConfig, AgentPrincipalPolicy, AgentRegistration, AgentSession, AgentSessionState
from loom.queue.deployment import read_agent_spec, qualify_agent_spec
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.submitted_execution import SUBMITTED_EXECUTION_SCOPE
from loom.scheduling import ExactQuantity, ResourceClaim
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = pytest.mark.integration

CAPABILITIES = ("remote-stage-execution-v4", "regular-file-relay-v1", "shared-execution-v1",
                "shared-assignment-reference-v1", "submitted-container-execution-v1")


def _fixture(tmp_path):
    policy, execution, request, _ = _submitted(tmp_path)
    control = tmp_path / "control"
    control.mkdir()
    (control / "challenge").write_bytes(b"control")
    policy = replace(policy, shared_roots={**policy.shared_roots, "control": {
        "host_path": str(control), "container_path": None, "access": "rw",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"control").hexdigest()},
    }})
    return policy, execution, _bound(request, execution, policy)


def _bound(request, execution, policy):
    old = StageFingerprintRecord.from_dict(request.fingerprint)
    return replace(request, profile=policy.capability, fingerprint=StageFingerprintRecord.create(
        algorithm=old.algorithm, inputs_summary=old.inputs_summary,
        payload=replace(old.payload, fingerprint_fields={**old.payload.fingerprint_fields,
            SUBMITTED_EXECUTION_SCOPE: {"execution": execution.to_dict(),
                                       "container_capability": policy.capability.to_dict()}}),
    ).to_dict())


def _config(tmp_path, policy, inventory=None):
    return AgentTlsClientConfig(
        "https://localhost", tmp_path / "ca", tmp_path / "cert", tmp_path / "key",
        agent_root=tmp_path / "native-agent", container_policies=(policy,),
        resource_inventory=inventory or AgentResourceInventory(2),
    )


def _close(client):
    if client._supervisor is not None:
        client._supervisor.shutdown_for_test()
    client.close()


@pytest.mark.parametrize("installed_first", [False, True])
def test_container_only_agent_images_share_resource_owners_and_exclusive_gpu(tmp_path, installed_first):
    policy, first, request = _fixture(tmp_path)
    second = replace(first, image=replace(first.image, sha256="b" * 64))
    inventory = AgentResourceInventory(2, gpu_devices=(ResidentGpuDevice(
        GpuDeviceDescriptor("gpu", "synthetic", 1024), "private-gpu-binding"),))
    config = _config(tmp_path, policy, inventory)
    with pytest.raises(QueueServiceError, match="explicit agent resource inventory"):
        replace(config, resource_inventory=None)
    legacy = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "installed", "1", "project", policy.capability.environment_fingerprint, "executor"),
        tmp_path, Path(sys.executable), cpu_capacity=99,
    )
    if installed_first:
        config = replace(config, resident_profiles=(legacy,))
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    session = AgentSession("session", "coordinator", "epoch", "agent", client.agent_root_id,
                           "policy", "config", "inventory", "available", (), ("default",), AgentSessionState.ACTIVE)
    try:
        providers, journal = client._runtime_owners(session)
        assert client._supervisor is not None and config.agent_root is not None
        identity = (client.agent_root_id, client._supervisor.supervisor_id, client._supervisor.continuity_epoch)
        commands_by_assignment = []
        for index, image in enumerate((first, second, second)):
            selected = _bound(request, image, policy)
            if installed_first and index == 0:
                fingerprint = StageFingerprintRecord.from_dict(selected.fingerprint)
                selected = replace(selected, profile=legacy.descriptor,
                    fingerprint=StageFingerprintRecord.create(
                        algorithm=fingerprint.algorithm, inputs_summary=fingerprint.inputs_summary,
                        payload=replace(fingerprint.payload, fingerprint_fields={
                            key: value for key, value in fingerprint.payload.fingerprint_fields.items()
                            if key != SUBMITTED_EXECUTION_SCOPE
                        }),
                    ).to_dict())
            from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
            workspace = _ResidentAssignmentWorkspace(config.agent_root, f"work-{index}")
            launch = client._assignment_launch_profile(selected, workspace)
            assert launch.submitted_execution == (None if installed_first and index == 0 else image)
            current, same_journal = client._runtime_owners(session)
            assert same_journal is journal and all(current[key] is value for key, value in providers.items())
            assignment = ManagedAssignment(f"work-{index}", f"run-{index}", f"stage-{index}", "probe", 1,
                f"attempt-{index}", "agent", "session", f"offer-{index}", f"claim-{index}")
            commands = tuple(ClaimCommand(assignment, f"prepare-{index}-{atom.owner_resource_kind}",
                ResourceClaim(atom.owner_resource_kind, providers[atom.owner_resource_kind].claim_contracts[0],
                    (replace(atom, amount=ExactQuantity(1)),), 1), providers[atom.owner_resource_kind].descriptor)
                for atom in inventory.capacity_atoms("agent"))
            journal.persist_request(assignment, {"profile": selected.profile.to_dict()})
            state = journal.prepare_composite(assignment, commands, current)
            assert state is (AssignmentState.DECLINED if index == 1 else AssignmentState.PREPARED)
            commands_by_assignment.append((assignment, commands))
            if index == 1:
                journal.release_declined(assignment.assignment_id, "declined")
                previous, held = commands_by_assignment[0]
                journal.abort_pregrant(previous.assignment_id, held, providers)
                journal.release_declined(previous.assignment_id, "aborted")
            elif index == 2:
                journal.abort_pregrant(assignment.assignment_id, commands, providers)
                journal.release_declined(assignment.assignment_id, "aborted")
        assert journal.retained_claim_commands() == ()
        assert identity == (client.agent_root_id, client._supervisor.supervisor_id, client._supervisor.continuity_epoch)
        with pytest.raises(QueueConflictError, match="fresh agent-root"):
            client._validate_reload_config(replace(config, container_policies=(replace(policy, environment={"X": "Y"}),)))
    finally:
        _close(client)


def test_submitted_offer_matches_policy_without_installed_profile(tmp_path):
    policy, execution, _ = _fixture(tmp_path)
    config = LocalDaemonConfig(tmp_path / "coordinator", None, tmp_path / "runs", None,
        cpu_capacity=0, container_capabilities=(policy.capability,),
        shared_roots=policy.shared_roots, assignment_payload_root_id="control",
        agent_policy=AgentPolicyConfig(agents=(AgentPrincipalPolicy("credential", "principal", "agent",
            ("default",), CAPABILITIES),)))
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        view = daemon.agent_view(LocalDaemonPrincipal("principal", LocalDaemonRole.AGENT, "credential"))
        hello = view.handshake()
        session = view.register(AgentRegistration("register", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]),
            "root", "config", "inventory", "availability", ("default",), CAPABILITIES,
            retirement_verifier="01" * 32))
        inventory = AgentResourceInventory(2)
        offer = AgentOffer(session.session_id, session.coordinator_epoch, session.config_revision,
            session.inventory_revision, session.availability_revision, 2, 0, 30,
            _resident_provider_descriptors(inventory, "agent"),
            container_execution_capabilities=(policy.capability,))
        assert AgentOffer.from_value(offer.value()) == offer
        assert offer.resident_profiles == ()
        view.publish_offer(offer, idempotency_key="offer")
        assert daemon._execution is not None
        candidates = daemon._execution._remote_candidates()
        assert len(candidates) == 1
        candidate, target = next(iter(candidates.values()))
        assert target.profile == policy.capability
        assert candidate.attributes["container_policy_fingerprint"] == policy.capability.fingerprint
        assert "resident_project_fingerprint" not in candidate.attributes
        assert policy.capability.satisfies(policy.capability.requirement(execution))
    finally:
        daemon.stop()


def test_submitted_shared_reference_resolves_original_image_on_replay(tmp_path):
    policy, execution, request = _fixture(tmp_path)
    config = _config(tmp_path, policy)
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    try:
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        ref = publish(encoded, request, root_id="control", roots=policy.shared_roots,
                      session_id="session", issuer_epoch="epoch")
        assert client._resolve_delivery("session", ref) == request
        # Exact retained delivery can be recovered even after payload storage disappears.
        (tmp_path / "control").rename(tmp_path / "unavailable-control")
        assert client._resolve_delivery("session", ref).submitted_execution == execution
    finally:
        _close(client)


def test_container_only_service_declaration_qualifies_no_scientific_image(tmp_path):
    policy, _, _ = _fixture(tmp_path)
    config = {"schema_version": 3, "kind": "loom.outbound-agent-service", "agent_root": "agent",
        "url": "https://localhost", "server_ca_path": "ca", "certificate_path": "cert", "private_key_path": "key",
        "resident_profiles": [], "container_policies": [policy.to_dict()], "reconnect_seconds": 1,
        "registration": {"config_revision": "config", "inventory_revision": "inventory",
                         "availability_revision": "availability", "pools": ["default"], "capabilities": list(CAPABILITIES)},
        "resources": {"cpu_capacity": 1, "memory_capacity_bytes": 0, "gpu": {"provider": "nvidia", "devices": "none"}}}
    path = tmp_path / "outbound.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    spec = read_agent_spec(path)
    # No image must exist to qualify the manager's runtime and storage policy.
    (tmp_path / "workloads" / "aaa" / "image.sif").unlink()
    service = qualify_agent_spec(spec)
    assert service.client.resident_profiles == ()
    assert service.client.container_policies == (policy,)
    assert service.client.execution_inventory.cpu_capacity == 1
    from loom.queue.preflight import check_loaded_agent
    result = check_loaded_agent(service)
    assert any(check.check_id == "execution.container_policy" and check.status.value == "PASS" for check in result.checks)
    assert not any("pure coordinator" in check.message for check in result.checks)


def test_container_only_agent_registers_and_refreshes_offer(tmp_path):
    from loom.queue.agent_session_transport import AgentTlsServerConfig, LocalDaemonAgentHttpServer
    from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint

    policy, _, _ = _fixture(tmp_path)
    credentials = mutual_tls_credentials(tmp_path / "tls")
    config = LocalDaemonConfig(tmp_path / "coordinator", None, tmp_path / "runs", None,
        cpu_capacity=0, container_capabilities=(policy.capability,), shared_roots=policy.shared_roots,
        assignment_payload_root_id="control", agent_policy=AgentPolicyConfig(agents=(
            AgentPrincipalPolicy("credential", "principal", "agent", ("default",), CAPABILITIES),)))
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig("localhost", 0,
        credentials["server"].with_suffix(".crt"), credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"),
        {certificate_fingerprint(credentials["agent"].with_suffix(".crt")): "credential"}))
    server.start()
    client_config = replace(_config(tmp_path, policy), url=f"https://localhost:{server.port}",
        server_ca_path=credentials["ca"].with_suffix(".crt"), certificate_path=credentials["agent"].with_suffix(".crt"),
        private_key_path=credentials["agent"].with_suffix(".key"))
    LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
    client = LocalDaemonAgentHttpClient(client_config)
    try:
        hello = client.handshake()
        client.register(AgentRegistration("register", str(hello["coordinator_id"]), str(hello["coordinator_epoch"]),
            client.agent_root_id, "config", "inventory", "available", ("default",), CAPABILITIES))
        client.refresh_resource_offer()
        assert daemon._execution is not None
        assert len(daemon._execution._remote_candidates()) == 1
        members = client._configured_provider_members
        client.refresh_resource_offer()
        assert client._configured_provider_members is members
    finally:
        _close(client)
        server.stop()
        daemon.stop()
