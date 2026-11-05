"""A settled native policy repair retains sessions and rejects GPU expansion."""

from dataclasses import asdict, replace
import json

import pytest

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue._agent_gpu_policy import CAPABILITY
from loom.queue._remote_stage_execution import GpuDeviceDescriptor
from loom.queue.agent_sessions import AgentControl, AgentControlKind, AgentOffer, LocalOwnerOperatorPolicy
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueConflictError
from loom.queue.local_daemon import CoordinatorSchedulingReload, LocalDaemonPrincipal, LocalDaemonRole
from tests.integration.queue.test_agent_session_transport import _policy, _request, _provider_descriptors
from tests.integration.queue.test_maintenance_admission import change, operator, owner as maintenance_owner  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]
DEVICES = (GpuDeviceDescriptor("GPU-good", "synthetic", 1024),
           GpuDeviceDescriptor("GPU-failed", "synthetic", 1024))


@pytest.fixture
def site(tmp_path):
    policy = replace(_policy(), agents=(replace(_policy().agents[0], gpu_devices=DEVICES),),
        local_owner=LocalOwnerOperatorPolicy(("maintenance", "scheduling_reload", "drain"), ("agent-a",), ("default",)))
    authored = asdict(policy)
    authored["agents"][0]["gpu_devices"] = [device.to_dict() for device in DEVICES]
    source = tmp_path / "coordinator.json"
    source.write_text(json.dumps({
        "schema_version": 3, "kind": "loom.coordinator-service",
        "deployment_root": str(tmp_path / "deployment"), "run_store_root": str(tmp_path / "runs"),
        "machine_id": "coordinator", "poll_interval_seconds": 0.01,
        "max_accepted_time_step_seconds": 60, "local_agent": None,
        "remote_profiles": [], "agent_server": None, "agent_policy": authored,
        "authority": {"kind": "embedded"},
    }))
    source.chmod(0o600)
    service = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, trusted_scheduling_loader=lambda: load_coordinator_service_config(source, current=service).daemon)
    daemon.start()
    agent = daemon.agent_view(LocalDaemonPrincipal("agent-principal", LocalDaemonRole.AGENT, "agent-credential"))
    session = agent.register(replace(_request(agent.handshake(), "remote-root"), retirement_verifier="a" * 64))
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        yield source, daemon, agent, session
    finally:
        server.stop()
        daemon.stop()


def candidate(site):
    _, daemon, _, _ = site
    old = daemon.config
    return replace(old, agent_policy=replace(old.agent_policy,
        agents=(replace(old.agent_policy.agents[0], gpu_devices=DEVICES[:1]),)))


def request(daemon, **overrides):
    gate = operator(daemon).observe_maintenance()
    return CoordinatorSchedulingReload("contract", daemon._scheduling_epoch, "remove failed GPU",
        gpu_policy_contraction={"maintenance_id": gate["maintenance_id"] or "maint-1",
            "maintenance_intent_digest": gate["intent_digest"] or "intent-maint-1",
            "expected_gate_revision": gate["revision"], **overrides})


def offer(agent, session, devices):
    return agent.publish_offer(AgentOffer(
        session.session_id, session.coordinator_epoch, session.config_revision,
        session.inventory_revision, session.availability_revision, 2, 4096, 60,
        _provider_descriptors("cpu", "memory", "gpu"), gpu_devices=devices,
        gpu_atoms=tuple(device.capacity_atom(device.device_id) for device in devices)),
        idempotency_key="remaining-devices")


def test_contraction_retains_session_and_accepts_remaining_inventory(site):
    _, daemon, agent, session = site
    with pytest.raises(QueueConflictError, match="GPU inventory"):
        offer(agent, session, DEVICES[:1])
    change(daemon, "close")
    daemon._trusted_scheduling_loader = lambda: candidate(site)
    reload = request(daemon)
    with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as client:
        assert CAPABILITY in client.observe_status().value["capabilities"]
        result = client.reload_scheduling(reload)
        assert result["state"] == "applied"
        assert client.reload_scheduling(reload) == result
    offer(agent, session, DEVICES[:1])
    assert daemon.agent(session.agent_id).session_id == session.session_id
    assert daemon.config.agent_policy.agents[0].gpu_devices == DEVICES[:1]
    assert operator(daemon).observe_maintenance()["state"] == "closed"


@pytest.mark.parametrize("case", ["open", "owner", "revision", "permissions", "identity", "empty", "added", "descriptor", "reorder", "unrelated", "unbound", "unsettled"])
def test_contraction_refuses_unsafe_or_unbound_changes(site, case):
    _, daemon, _, _ = site
    if case != "open":
        change(daemon, "close")
    if case == "unsettled":
        session = site[3]
        operator(daemon).control_agent(AgentControl("drain", AgentControlKind.DRAIN, session.agent_id,
            session.session_id, session.config_revision, None, False, "pending native control"))
    old = daemon.config
    new = candidate(site)
    rule = new.agent_policy.agents[0]
    if case == "permissions":
        new = replace(new, agent_policy=replace(new.agent_policy, local_owner=replace(new.agent_policy.local_owner, actions=("scheduling_reload",))))
    elif case == "identity":
        new = replace(new, agent_policy=replace(new.agent_policy, agents=(replace(rule, credential_id="changed"),)))
    elif case in {"empty", "added", "descriptor", "reorder"}:
        devices = {"empty": (), "added": (*DEVICES[:1], GpuDeviceDescriptor("GPU-new", "synthetic", 1024)),
                   "descriptor": (replace(DEVICES[0], vram_bytes=2048),), "reorder": tuple(reversed(DEVICES))}[case]
        new = replace(new, agent_policy=replace(new.agent_policy, agents=(replace(rule, gpu_devices=devices),)))
    elif case == "unrelated":
        new = replace(new, poll_interval_seconds=0.2)
    daemon._trusted_scheduling_loader = lambda: new
    reload = request(daemon, **({"maintenance_id": "another"} if case == "owner" else
                               {"expected_gate_revision": 99} if case == "revision" else {}))
    if case == "unbound":
        reload = replace(reload, gpu_policy_contraction=None)
    assert operator(daemon).reload_scheduling(reload)["state"] == "failed"
    assert daemon.config == old


def test_contraction_rechecks_maintenance_after_reload_preparation(site, monkeypatch):
    _, daemon, _, _ = site
    change(daemon, "close")
    daemon._trusted_scheduling_loader = lambda: candidate(site)
    prepare = daemon._execution.prepare_scheduling_reload
    def open_gate(*args):
        result = prepare(*args)
        change(daemon, "open")
        return result
    monkeypatch.setattr(daemon._execution, "prepare_scheduling_reload", open_gate)
    with pytest.raises(QueueConflictError, match="exact settled maintenance"):
        operator(daemon).reload_scheduling(request(daemon))
    assert set(daemon.config.agent_policy.agents[0].gpu_devices) == set(DEVICES)


def test_contraction_negotiates_before_mutation(site, monkeypatch):
    import loom.queue.local_daemon_transport as unix
    _, daemon, _, _ = site
    change(daemon, "close")
    calls, dispatch = [], unix.dispatch_control
    def old_peer(*args, **kwargs):
        calls.append(args[2])
        value = dict(dispatch(*args, **kwargs))
        if args[2] == "operator_handshake":
            value["capabilities"] = [item for item in value["capabilities"] if item != CAPABILITY]
        return value
    monkeypatch.setattr(unix, "dispatch_control", old_peer)
    with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as client:
        with pytest.raises(CoordinatorClientError) as caught:
            client.reload_scheduling(request(daemon))
    assert caught.value.code == "unsupported_capability"
    assert calls == ["operator_handshake"]


def test_contraction_refuses_authorized_check(maintenance_owner):  # noqa: F811
    from loom.coordinator import RunRequest
    from loom.queue._agent_gpu_policy import validate_coordinator
    from tests.integration.queue.test_maintenance_admission import check_binding
    from tests.integration.queue.test_preparation_operations import _request as preparation_request

    daemon = maintenance_owner
    change(daemon, "close")
    check = RunRequest(preparation_request(), "check-queue")
    change(daemon, "authorize", check=check_binding(daemon, check))
    with pytest.raises(QueueConflictError, match="exact settled maintenance"):
        validate_coordinator(daemon, daemon.config, request(daemon).gpu_policy_contraction)
