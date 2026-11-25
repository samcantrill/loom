"""Independent host dispatch retains exact requests under one receipt writer."""
from copy import deepcopy
import hashlib
from threading import Barrier, Event, get_ident
from types import SimpleNamespace

import pytest

from loom.fleet import ssh_operations as ssh, workload_upgrades as workloads
from loom.fleet._host import atomic, read


def operation(tmp_path, monkeypatch):
    hosts = {}
    inputs = {}
    declarations = {}
    for name in ('first', 'second', 'third'):
        config = tmp_path / (name + '.json')
        atomic(config, {'host': name})
        declarations[name] = read(config)
        inputs[str(config)] = hashlib.sha256(config.read_bytes()).hexdigest()
        hosts[name] = {'name': name, 'host': name, 'config': str(config),
                       'root': '/native/' + name, 'env_file': None, 'env_sha256': None}
    intent = {'operation_id': 'upgrade', 'hosts': hosts, 'inputs': inputs,
              'release': {}, 'declarations': declarations}
    monkeypatch.setattr(ssh, 'verify_release', lambda _: {})
    monkeypatch.setattr(ssh, '_load_protected_config', lambda path, **kw: (None, None, read(path), None))
    return ssh._Operation(SimpleNamespace(runtime_release=tmp_path / 'release.json'), tmp_path, intent)


def test_all_hosts_dispatch_before_ack_with_parent_receipts_and_exact_replay(tmp_path, monkeypatch):
    op = operation(tmp_path, monkeypatch)
    parent = get_ident()
    barrier = Barrier(3, timeout=5)
    completed = {name: Event() for name in op.intent['hosts']}
    remote = {}
    dispatched = []
    writes = []
    peer_persisted = Event()
    op.inventory.name = "fleet"
    monkeypatch.setattr(ssh, "_directory", lambda *_: tmp_path)
    atomic(tmp_path / "intent.json", op.intent)
    original_atomic = ssh.atomic
    def publish(path, value):
        writes.append(get_ident())
        original_atomic(path, value)
        if path == op.receipts / "second-workload-stage" / "receipt.json":
            peer_persisted.set()
    monkeypatch.setattr(ssh, 'atomic', publish)
    def transport(host, request):
        if request['action'] == 'receipt':
            return remote[request['request_id']]
        assert get_ident() != parent
        assert len(list(op.receipts.glob('*/intent.json'))) == 3
        barrier.wait()
        if host == 'first':
            assert peer_persisted.wait(5)
            status = ssh.operation_status(op.inventory, op.intent["operation_id"])
            assert status is not None
            assert status["steps"]["second-workload-stage"]["native_outcome"] == "applied"
            assert status["steps"]["first-workload-stage"]["native_outcome"] == "unknown"
        elif host == 'second':
            assert completed['third'].wait(5)
        dispatched.append((host, request['request_id']))
        result = {'candidate_source': '/qualified/' + host}
        remote[request['request_id']] = result
        completed[host].set()
        if host == 'first':
            raise ssh.SshUnavailable('reply dropped after native completion')
        return result
    monkeypatch.setattr(ssh, 'ssh', transport)
    calls = [(name, 'workload-stage', {}) for name in op.intent['hosts']]
    with pytest.raises(ssh.SshUnavailable, match='reply dropped'):
        op.call_many(calls)
    assert [name for name, _ in dispatched] == ['third', 'second', 'first']
    assert len(list(op.receipts.glob('*/receipt.json'))) == 2
    assert set(writes) == {parent}
    before = {p: p.read_bytes() for p in op.receipts.glob('*/intent.json')}
    resumed = ssh._Operation(op.inventory, tmp_path, deepcopy(op.intent))
    results = resumed.call_many(calls)
    assert set(results) == set(op.intent['hosts'])
    assert len(dispatched) == 3
    assert len(list(op.receipts.glob('*/receipt.json'))) == 3
    assert all(p.read_bytes() == data for p, data in before.items())


def test_batch_refuses_changed_authored_input_before_dispatch(tmp_path, monkeypatch):
    op = operation(tmp_path, monkeypatch)
    atomic(tmp_path / 'second.json', {'host': 'changed'})
    monkeypatch.setattr(ssh, 'ssh', lambda *a: pytest.fail('changed input dispatched'))
    with pytest.raises(ssh.QueueConflictError, match='input changed'):
        op.call_many([(name, 'workload-stage', {}) for name in op.intent['hosts']])


def test_gpu_successor_uses_distinct_immutable_host_request(tmp_path, monkeypatch):
    op = operation(tmp_path, monkeypatch)
    dispatched = []

    def transport(host, request):
        dispatched.append(request)
        if request['profile'] == {'old': True}:
            raise ssh.QueueConflictError('GPU capability policy differs from admitted selection')
        return {'outcome': 'passed'}

    monkeypatch.setattr(ssh, 'ssh', transport)
    with pytest.raises(ssh.QueueConflictError, match='differs'):
        op.call('first', 'gpu-capability', profile={'old': True})
    prior = op.receipts / 'first-gpu-capability/intent.json'
    before = prior.read_bytes()
    values = {'profile': {'current': True}, '_step_key': 'first-gpu-capability-retry'}
    assert op.call('first', 'gpu-capability', **values) == {'outcome': 'passed'}
    assert op.call('first', 'gpu-capability', **values) == {'outcome': 'passed'}
    assert len(dispatched) == 2
    assert dispatched[0]['request_id'] != dispatched[1]['request_id']
    assert '_step_key' not in dispatched[1]
    assert prior.read_bytes() == before


def test_all_hosts_stage_before_promotion_preserves_native_settlement(tmp_path):
    names = ('first', 'second', 'third')
    staged = []
    observed = []
    acknowledged = set()

    def stage(calls):
        staged.extend(name for name, _, _ in calls)
        return {name: {'candidate_source': '/' + name} for name, _, _ in calls}
    op = SimpleNamespace(
        intent={'agents': dict.fromkeys(names), 'target_declarations': dict.fromkeys(names, {}),
                'image': '/image', 'image_sha256': 'sha',
                'candidates': dict.fromkeys(names, {'target': {}})},
        receipts=tmp_path,
        call_many=stage,
        recover_host=lambda name: {'declaration': {}},
        accept_update=lambda *a: None,
    )
    def promote(name, source):
        assert source == '/' + name
        assert staged[-3:] == list(names)
        observed.append(name)
        if name not in acknowledged:
            raise workloads.maintenance._Waiting('native acknowledgement pending')
    op.promote = promote
    with pytest.raises(workloads.maintenance._Waiting, match='pending'):
        workloads._promote_agents(op)
    assert staged == list(names)
    assert observed == ['first']
    acknowledged.add('first')
    with pytest.raises(workloads.maintenance._Waiting, match='pending'):
        workloads._promote_agents(op)
    assert observed == ['first', 'first', 'second']
    acknowledged.update(names)
    workloads._promote_agents(op)
    assert observed[-3:] == list(names)

def test_preflight_prepares_peer_and_detaches_before_slow_capture(tmp_path, monkeypatch):
    import time
    from loom.fleet import upgrades
    from loom.queue.preparation import PreparationSource

    op = operation(tmp_path, monkeypatch)
    op.intent["hosts"]["coordinator"] = op.intent["hosts"].pop("third")
    op.intent["declarations"]["coordinator"] = op.intent["declarations"].pop("third")
    for name, row in op.intent["hosts"].items():
        row["expected_root_id"] = name + "-root"
    op.intent.update(agents={"first": {}, "second": {}}, check_selection={"deployment": "fixture", "config": "probe.yaml"})
    op.intent["target_declarations"] = {
        "coordinator": {"preparation": {"profiles": {"probe": {"resident_profile_id": "test"}}}},
        **{name: {"resident_profiles": [{"descriptor": {"profile_id": "test"}}]} for name in op.intent["agents"]},
    }
    monkeypatch.setattr(upgrades, "load_deployment", lambda _: SimpleNamespace(
        preparation_profile="probe", source=PreparationSource("shared", "projects", ".", ("probe.yaml",))))
    release, finished = Event(), Event()
    effects = {}
    def transport(host, request):
        identity = request["request_id"]
        if request["action"] == "receipt":
            return effects.get(identity)
        assert identity not in effects
        if request["action"] == "upgrade-check-capture":
            if request["agent_id"] == "first":
                assert release.wait(10)
            effects[identity] = {"bindings": {"value": request["agent_id"]}}
            if request["agent_id"] == "first":
                finished.set()
                raise ssh.SshUnavailable("reply dropped")
        else:
            assert request["bindings"] == {"value": request["agent_id"]}
            effects[identity] = {"outcome": "applied"}
        return effects[identity]

    monkeypatch.setattr(ssh, "ssh", transport)
    op.deadline = time.monotonic() + 1.5
    try:
        with pytest.raises(ssh.SshUnavailable, match="deadline"):
            upgrades._preflight_checks(op)
        assert not finished.is_set()
        assert (op.receipts / "second-upgrade-check-prepare-second/receipt.json").is_file()
        assert not (op.receipts / "first-upgrade-check-prepare-first/intent.json").exists()
    finally:
        release.set()
    assert finished.wait(5)
    op.deadline = time.monotonic() + 5
    upgrades._preflight_checks(op)
    assert len(effects) == 4


def test_setup_submits_later_checks_during_first_missing_offer(tmp_path, monkeypatch):
    import time
    from contextlib import nullcontext
    from dataclasses import make_dataclass
    from loom.coordinator import CoordinatorOperatorClient
    from loom.fleet import self_tests

    op = operation(tmp_path, monkeypatch)
    op.inventory = make_dataclass("Selected", [("path", object), ("runtime_release", object)])(
        tmp_path / "inventory", op.inventory.runtime_release)
    op.intent["hosts"]["coordinator"] = op.intent["hosts"].pop("third")
    op.intent["declarations"]["coordinator"] = op.intent["declarations"].pop("third")
    for name, decl in op.intent["declarations"].items():
        if name != "coordinator":
            decl.update(url="https://localhost", registration=name)
            path = tmp_path / (name + ".json")
            atomic(path, decl)
            op.intent["inputs"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    op.intent.update(issuer="issuer", fresh_coordinator=False, nonce="nonce", check_selection={"config": "probe.yaml"})
    op.deadline = time.monotonic() + 8
    offered, checked = set(), set()
    first_observed = Event()
    actions = []
    def transport(host, req):
        name = req.get("agent_id", "coordinator" if host == "third" else host)
        action = req["action"]
        actions.append((name, action))
        if action == "prepare":
            return {"ca": "ca", "issuer_fingerprint": "issuer", "csr": "csr-" + name}
        if action == "issue":
            return {"ca": "ca", "certificate": "cert-" + name}
        if action == "enroll":
            assert ("receive" in [kind for agent, kind in actions if agent == name]
                    and req["certificate"] == "cert-" + name)
        if action in {"observe", "initialize"}:
            return {"owner": name, "gpu_devices": [], "profile": "profile"}
        return {"outcome": "applied"}
    def offer(name, *, deadline):
        assert deadline == op.deadline and (name, "start") in actions
        offered.add(name)
        if name == "first":
            first_observed.set()
        return SimpleNamespace(value={"offer": name == "second" or "second" in checked})
    def check(inventory, *, agent_id, _setup_id, timeout_seconds, **kwargs):
        assert agent_id in offered and timeout_seconds <= 8
        assert agent_id not in checked and _setup_id.startswith("check-")
        if agent_id == "second":
            assert first_observed.wait(3) and "first" not in checked
        checked.add(agent_id)
        return {"outcome": "passed"}

    monkeypatch.setattr(ssh, "ssh", transport)
    monkeypatch.setattr(ssh, "_connections", lambda *args: (tmp_path / "deployment", tmp_path / "operator"))
    monkeypatch.setattr(ssh, "_bundle", lambda *args: {})
    monkeypatch.setattr(ssh, "_fingerprint", lambda cert: cert)
    monkeypatch.setattr(self_tests, "self_test", check)
    monkeypatch.setattr(CoordinatorOperatorClient, "from_connection_file", lambda _: nullcontext(SimpleNamespace(observe_agent=offer)))
    result = ssh._continue(op)
    assert result["state"] == "complete" and checked == {"first", "second"}

def test_native_capture_allows_independent_request_and_excludes_shared_mutation(tmp_path, monkeypatch):
    import fcntl
    import io
    import json
    import sys
    from loom.fleet import _host

    admin = tmp_path / "admin"
    first = admin / "operations" / "first"
    _host.protected_directory(first)
    monkeypatch.setattr(_host.os, "umask", lambda _: 0o077)
    calls = []
    monkeypatch.setattr(_host, "execute", lambda request, *args:
                        calls.append(request["request_id"]) or {"bindings": {"ok": True}})
    def native(request_id, action):
        request = {"admin": str(admin), "action": action, "request_id": request_id}
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())))
        return _host.main()
    with (admin / "native.lock").open("a") as shared, (first / "capture.lock").open("a") as owner:
        fcntl.flock(shared, fcntl.LOCK_SH)
        fcntl.flock(owner, fcntl.LOCK_EX)
        initial = native("second", "upgrade-check-capture")
        assert initial is not None and initial["native_outcome"] == "applied"
        repeated = native("second", "upgrade-check-capture")
        assert repeated is not None and repeated["bindings"] == {"ok": True}
        with pytest.raises(BlockingIOError):
            native("first", "upgrade-check-capture")
        with pytest.raises(BlockingIOError):
            native("change", "enroll")
    assert calls == ["second"]
