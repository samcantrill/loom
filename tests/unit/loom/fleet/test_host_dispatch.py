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
    original_atomic = ssh.atomic
    def publish(path, value):
        writes.append(get_ident())
        original_atomic(path, value)
    monkeypatch.setattr(ssh, 'atomic', publish)
    def transport(host, request):
        if request['action'] == 'receipt':
            return remote[request['request_id']]
        assert get_ident() != parent
        assert len(list(op.receipts.glob('*/intent.json'))) == 3
        barrier.wait()
        if host == 'first':
            assert completed['second'].wait(5)
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


def test_promotion_dispatches_other_hosts_before_pending_acknowledgement(tmp_path):
    names = ('first', 'second', 'third')
    submitted = []
    observed = []
    op = SimpleNamespace(
        intent={'agents': dict.fromkeys(names), 'target_declarations': dict.fromkeys(names, {}),
                'image': '/image', 'image_sha256': 'sha',
                'candidates': dict.fromkeys(names, {'target': {}})},
        receipts=tmp_path,
        call_many=lambda calls: {name: {'candidate_source': '/' + name} for name, _, _ in calls},
        recover_host=lambda name: {'declaration': {}},
        accept_update=lambda *a: None,
    )
    def promote(name, source, *, dispatch_only=False):
        assert source == '/' + name
        if dispatch_only:
            submitted.append(name)
        else:
            observed.append(name)
            assert submitted == list(names)
            raise workloads.maintenance._Waiting('native acknowledgement pending')
    op.promote = promote
    with pytest.raises(workloads.maintenance._Waiting, match='pending'):
        workloads._promote_agents(op)
    assert submitted == list(names)
    assert observed == ['first']
