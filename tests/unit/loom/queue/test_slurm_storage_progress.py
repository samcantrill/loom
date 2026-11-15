"""Coordinator storage turns yield while real executor work remains blocked."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace, MethodType

import pytest

from loom.queue.local_daemon_execution import LocalDaemonExecution, _SlurmRetentionRequired
from loom.queue.errors import QueueConflictError


def test_storage_pending_deduplicates_and_allows_peer_commit(monkeypatch):
    import loom.queue.local_daemon_execution as module

    started, release, wake = Event(), Event(), Event()
    calls = []
    owner = SimpleNamespace(
        slurm_assignments=SimpleNamespace(schema_version=5, read=lambda _: SimpleNamespace(publication_completed_at=None)),
        config=SimpleNamespace(coordinator_shared_roots={}),
        _slurm_storage_futures={}, _slurm_storage_errors={},
        _slurm_storage_failures={}, _slurm_storage_retry_at={}, _slurm_storage_failed_publications=set(),
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
        _daemon_owner=lambda: SimpleNamespace(_wake=wake),
    )

    def acknowledge(agent, root, evidence, **options):
        key = evidence['assignment']['assignment_id']
        if key == 'B' or options['_retained'] is not None:
            return {'sequence': evidence['sequence']}
        record = SimpleNamespace(
            assignment=SimpleNamespace(assignment_id=key), fence='fence', delivery={}, report=None, publication_cancelled_at=None,
        )
        raise _SlurmRetentionRequired(owner, record, evidence)

    def retain(continuation):
        calls.append(continuation.record.assignment.assignment_id)
        started.set()
        assert release.wait(10)
        continuation.completed = True

    owner.acknowledge_slurm_agent = acknowledge
    owner._perform_slurm_storage = MethodType(LocalDaemonExecution._perform_slurm_storage, owner)
    monkeypatch.setattr(_SlurmRetentionRequired, 'retain_guarded', retain)
    evidence = {'assignment': {'assignment_id': 'A'}, 'sequence': 1, 'provider_released': True, 'release': {'state': 'CONTAINED'}}
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner._slurm_storage_workers = executor
        try:
            monkeypatch.setattr(module, '_SLURM_STORAGE_LIMIT', 0)
            reply = LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)
            assert reply['reason'] == 'storage_capacity'
            assert not owner._slurm_storage_futures
            assert not calls
            monkeypatch.setattr(module, '_SLURM_STORAGE_LIMIT', 1)
            reply = LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)
            assert reply['disposition'] == 'pending'
            assert started.wait(5)
            for _ in range(20):
                assert LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)['disposition'] == 'pending'
            peer = LocalDaemonExecution.acknowledge_slurm_pending(
                owner, 'agent', 'root', {'assignment': {'assignment_id': 'B'}, 'sequence': 1},
            )
            assert peer['sequence'] == 1
            assert not release.is_set()
            assert calls == ['A']
            assert owner._slurm_storage_progress['A']['phase'] == 'sealing_recovery'
            assert owner._slurm_storage_progress['A']['started_at']
            assert len(owner._slurm_storage_futures) == 1
            queued_evidence = {**evidence, 'assignment': {'assignment_id': 'C'}}
            queued = LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', queued_evidence)
            assert queued['reason'] == 'storage_capacity'
            assert len(owner._slurm_storage_futures) == 1
        finally:
            release.set()
        assert wake.wait(5)
        assert LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)['disposition'] == 'applied'
        assert not owner._slurm_storage_futures
        assert LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', queued_evidence)['disposition'] == 'pending'
        owner._slurm_storage_futures['C'][0].result(timeout=5)
        assert LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', queued_evidence)['disposition'] == 'applied'
        assert calls == ['A', 'C']
        assert not owner._slurm_storage_futures


@pytest.mark.parametrize('error', [OSError('storage unavailable'), QueueConflictError('ownership changed')])
def test_failed_storage_releases_worker_slot_and_retains_error(monkeypatch, error):
    from concurrent.futures import Future
    import loom.queue.local_daemon_execution as module

    future = Future()
    future.set_exception(error)
    record = SimpleNamespace(assignment=SimpleNamespace(assignment_id='A'), fence='fence', delivery={}, report=None, publication_cancelled_at=None)
    owner = SimpleNamespace(
        slurm_assignments=SimpleNamespace(schema_version=5, read=lambda _: SimpleNamespace(publication_completed_at=None)),
        config=SimpleNamespace(coordinator_shared_roots={}),
        _slurm_storage_futures={'A': (future, None)}, _slurm_storage_errors={},
        _slurm_storage_failures={}, _slurm_storage_retry_at={}, _slurm_storage_failed_publications=set(),
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
    )
    evidence = {'assignment': {'assignment_id': 'A'}, 'sequence': 1, 'provider_released': True, 'release': {'state': 'CONTAINED'}}
    def acknowledge(*args, **kwargs):
        raise _SlurmRetentionRequired(owner, record, evidence)
    owner.acknowledge_slurm_agent = acknowledge
    monkeypatch.setattr(module, 'monotonic', lambda: 10)
    if isinstance(error, OSError):
        reply = LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)
        assert reply['reason'] == 'storage_retry'
    else:
        with pytest.raises(QueueConflictError, match='ownership changed'):
            LocalDaemonExecution.acknowledge_slurm_pending(owner, 'agent', 'root', evidence)
    assert not owner._slurm_storage_futures
    assert owner._slurm_storage_errors['A'] == str(error)


def test_completed_publication_replay_reauthenticates_without_storage_work():
    identity = {'fence': 'fence', 'incarnation': 'bootstrap'}
    record = SimpleNamespace(
        assignment=SimpleNamespace(agent_id='agent', agent_root_id='root'),
        fence='fence', bootstrap_incarnation='bootstrap', start_consumed=True,
        publication_completed_at='2026-11-15T00:00:00Z', publication_cancelled_at=None,
    )
    owner = SimpleNamespace(
        slurm_assignments=SimpleNamespace(read=lambda _: record),
        slurm_result_identity=lambda _: identity,
        _slurm_finalize_record=lambda *args, **kwargs: pytest.fail('completed replay repeated storage work'),
    )
    evidence = {'assignment_id': 'A', 'identity': identity, 'result_operation': 'commit'}
    assert LocalDaemonExecution.relay_slurm_result(owner, 'agent', 'root', evidence) == {'acknowledged': True}
    with pytest.raises(QueueConflictError):
        LocalDaemonExecution.relay_slurm_result(owner, 'agent', 'root', {**evidence, 'identity': {**identity, 'fence': 'stale'}})
    with pytest.raises(QueueConflictError):
        LocalDaemonExecution.relay_slurm_result(owner, 'other-agent', 'root', evidence)


def test_observations_distinguish_compute_release_from_pending_publication():
    record = SimpleNamespace(
        assignment=SimpleNamespace(assignment_id='A'), compute_released_at='released-at',
        publication_requested_at='requested-at', publication_completed_at=None, publication_cancelled_at=None,
        agent_evidence_accepted_at='accepted-at',
    )
    owner = SimpleNamespace(
        slurm_assignments=SimpleNamespace(list_run_unreleased=lambda _: [record],
                                         agent_evidence=lambda _: (1, {'provider_released': True})),
        _slurm_storage_futures={}, _slurm_storage_errors={}, _slurm_storage_retry_at={},
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
    )
    item, = LocalDaemonExecution.slurm_storage_observations(owner, 'run')['assignments']
    assert item['compute'] == {'state': 'released', 'released_at': 'released-at'}
    assert item['publication']['state'] == 'pending'
    assert item['storage']['progress'] is None
    assert item['storage']['worker_state_consistency'] == 'process_local'
    owner._slurm_storage_errors['A'] = 'ownership conflict'
    item, = LocalDaemonExecution.slurm_storage_observations(owner, 'run')['assignments']
    assert item['storage']['state'] == 'failed'
    assert item['storage']['last_error'] == 'ownership conflict'


def test_reconciliation_replays_cancelled_release_before_missing_publication_marker():
    """Authority cancellation may commit before its assignment marker does."""
    evidence = {'provider_released': True, 'release': {'state': 'CONTAINED'}}
    record = SimpleNamespace(
        assignment=SimpleNamespace(assignment_id='A', run_uri='run', attempt_id='attempt',
                                   agent_id='agent', agent_root_id='root'),
        publication_requested_at='requested', publication_completed_at=None,
        publication_cancelled_at=None,
    )
    calls = []
    owner = SimpleNamespace(
        slurm_assignments=SimpleNamespace(pending_storage_page=lambda **_: [record],
                                         agent_evidence=lambda _: (7, evidence)),
        _slurm_storage_cursor=None, _slurm_storage_errors={},
        _attempt_cancel_requested=lambda *_: True,
        acknowledge_slurm_pending=lambda *args: calls.append(args),
        slurm_result_identity=lambda _: pytest.fail('cancelled publication was rediscovered'),
    )
    LocalDaemonExecution.reconcile_slurm_storage(owner)
    assert calls == [('agent', 'root', evidence)]
    assert not owner._slurm_storage_errors


@pytest.mark.parametrize('changed', ['fence', 'bootstrap_incarnation', 'delivery'])
def test_prepared_retention_cannot_commit_after_ownership_changes(changed):
    from copy import copy

    owner = SimpleNamespace(config=SimpleNamespace(coordinator_shared_roots={}))
    original = SimpleNamespace(assignment='assignment', fence='fence',
                               bootstrap_incarnation='incarnation', delivery={})
    evidence = {'provider_released': True}
    continuation = _SlurmRetentionRequired(owner, original, evidence)
    continuation.completed = True
    assert continuation.validates(owner, original, evidence)
    current = copy(original)
    setattr(current, changed, {'changed': True} if changed == 'delivery' else 'changed')
    assert not continuation.validates(owner, current, evidence)
