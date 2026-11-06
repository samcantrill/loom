"""Recovered GPUs require an explicit, settled policy expansion."""
from dataclasses import replace

import pytest

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.queue._agent_gpu_policy import EXPANSION_CAPABILITY
from loom.queue._remote_stage_execution import GpuDeviceDescriptor
from loom.queue.errors import QueueConflictError
from loom.queue.local_daemon import CoordinatorSchedulingReload
from tests.integration.queue.test_gpu_policy_contraction import DEVICES, offer, request, site  # noqa: F401
from tests.integration.queue.test_maintenance_admission import change, operator

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]
RECOVERED = GpuDeviceDescriptor("GPU-recovered", "synthetic", 1024)


def candidate(daemon):
    old = daemon.config
    rule = replace(old.agent_policy.agents[0], gpu_devices=(*DEVICES, RECOVERED))
    return replace(old, agent_policy=replace(old.agent_policy, agents=(rule,)))


def expansion(daemon):
    original = request(daemon)
    return replace(original, gpu_policy_expansion=original.gpu_policy_contraction,
                   gpu_policy_contraction=None)


def test_expansion_preserves_session_and_replays(site):  # noqa: F811
    _, daemon, agent, session = site
    change(daemon, "close")
    new = candidate(daemon)
    daemon._trusted_scheduling_loader = lambda: new
    reload = expansion(daemon)
    assert CoordinatorSchedulingReload.from_dict(reload.to_dict()) == reload
    with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as client:
        result = client.reload_scheduling(reload)
        assert result["state"] == "applied"
        assert client.reload_scheduling(reload) == result
    offer(agent, session, (*DEVICES, RECOVERED))
    assert daemon.agent(session.agent_id).session_id == session.session_id
    assert operator(daemon).observe_maintenance()["state"] == "closed"


@pytest.mark.parametrize("case", ["open", "owner", "revision", "credential", "descriptor", "replacement", "unrelated", "unbound"])
def test_expansion_rejects_unsafe_changes(site, case):  # noqa: F811
    _, daemon, _, _ = site
    if case != "open":
        change(daemon, "close")
    old = daemon.config
    new = candidate(daemon)
    rule = new.agent_policy.agents[0]
    if case == "credential":
        rule = replace(rule, credential_id="other")
    elif case == "descriptor":
        rule = replace(rule, gpu_devices=(replace(DEVICES[0], vram_bytes=2048), DEVICES[1], RECOVERED))
    elif case == "replacement":
        rule = replace(rule, gpu_devices=(DEVICES[0], RECOVERED))
    new = replace(new, agent_policy=replace(new.agent_policy, agents=(rule,)))
    if case == "unrelated":
        new = replace(new, poll_interval_seconds=0.2)
    daemon._trusted_scheduling_loader = lambda: new
    reload = expansion(daemon)
    if case in {"owner", "revision"}:
        binding = dict(reload.gpu_policy_expansion)
        binding["maintenance_id" if case == "owner" else "expected_gate_revision"] = "other" if case == "owner" else 99
        reload = replace(reload, gpu_policy_expansion=binding)
    elif case == "unbound":
        reload = replace(reload, gpu_policy_expansion=None)
    assert operator(daemon).reload_scheduling(reload)["state"] == "failed"
    assert daemon.config == old


def test_expansion_rechecks_gate_after_preparation(site, monkeypatch):  # noqa: F811
    _, daemon, _, _ = site
    change(daemon, "close")
    old = daemon.config
    daemon._trusted_scheduling_loader = lambda: candidate(daemon)
    prepare = daemon._execution.prepare_scheduling_reload
    def reopen(*args):
        result = prepare(*args)
        change(daemon, "open")
        return result
    monkeypatch.setattr(daemon._execution, "prepare_scheduling_reload", reopen)
    with pytest.raises(QueueConflictError, match="exact settled maintenance"):
        operator(daemon).reload_scheduling(expansion(daemon))
    assert daemon.config == old


def test_expansion_negotiates_before_mutation(site, monkeypatch):  # noqa: F811
    import loom.queue.local_daemon_transport as unix
    _, daemon, _, _ = site
    change(daemon, "close")
    calls, dispatch = [], unix.dispatch_control
    def old_peer(*args, **kwargs):
        calls.append(args[2])
        result = dict(dispatch(*args, **kwargs))
        if args[2] == "operator_handshake":
            result["capabilities"] = [v for v in result["capabilities"] if v != EXPANSION_CAPABILITY]
        return result
    monkeypatch.setattr(unix, "dispatch_control", old_peer)
    with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as client:
        with pytest.raises(CoordinatorClientError) as error:
            client.reload_scheduling(expansion(daemon))
    assert error.value.code == "unsupported_capability"
    assert calls == ["operator_handshake"]
