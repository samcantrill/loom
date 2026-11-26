"""Coordinator storage turns yield while real executor work remains blocked."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Any, cast
from types import SimpleNamespace, MethodType

import pytest

from loom.queue._coordinator_run_authority import _ScopedCoordinatorAuthority
from loom.queue.local_daemon_execution import LocalDaemonExecution, _SlurmRetentionRequired
from loom.queue.errors import QueueConflictError


@pytest.mark.parametrize("changed", ["record", "recovery"])
def test_slurm_report_observation_discards_superseded_evidence(changed):
    assignment = SimpleNamespace(assignment_id="A")
    original = SimpleNamespace(assignment=assignment, state="running", report={"status": "succeeded"}, fence="first")
    record = original
    recovering = False
    execution = object.__new__(LocalDaemonExecution)
    owner: Any = execution
    owner._slurm_agent = None
    owner.slurm_assignments = SimpleNamespace(
        list_run_unreleased=lambda uri: (original,), read=lambda identity: record,
    )
    owner._recovery_retains_assignment = lambda identity: recovering
    owner._reconcile_slurm_terminal_assignment = lambda *args: pytest.fail("superseded terminal report applied")
    steps = owner._reconcile_slurm_steps("run", None)
    assert next(steps) is None
    if changed == "record":
        record = SimpleNamespace(assignment=assignment, state="terminal", report=original.report, fence="first")
    else:
        recovering = True
    with pytest.raises(StopIteration) as done:
        steps.send(object())
    assert done.value.value == (True, None)


def test_storage_pending_deduplicates_and_allows_peer_commit(monkeypatch):
    import loom.queue.local_daemon_execution as module

    started, release, wake = Event(), Event(), Event()
    calls = []
    owner: Any = SimpleNamespace(
        slurm_assignments=SimpleNamespace(schema_version=5, read=lambda _: SimpleNamespace(publication_completed_at=None)),
        config=SimpleNamespace(coordinator_shared_roots={}),
        _slurm_chunk_futures={},
        _slurm_storage_futures={}, _slurm_storage_errors={},
        _slurm_storage_failures={}, _slurm_storage_retry_at={}, _slurm_storage_failed_publications=set(),
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
        _daemon_owner=lambda: SimpleNamespace(_wake=wake),
    )

    def acknowledge(agent, root, evidence, **options):
        key = evidence['assignment']['assignment_id']
        if key == 'B' or options['_retained'] is not None:
            return {'sequence': evidence['sequence']}
        record: Any = SimpleNamespace(
            assignment=SimpleNamespace(assignment_id=key), fence='fence', delivery={}, report=None, publication_cancelled_at=None,
        )
        raise _SlurmRetentionRequired(owner, record, evidence)

    def retain(continuation):
        calls.append(continuation.record.assignment.assignment_id)
        started.set()
        assert release.wait(10)
        continuation.completed = True

    owner._slurm_storage_count = MethodType(LocalDaemonExecution._slurm_storage_count, owner)
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
            # The embedded submit agent also replays its durable outbox when
            # reconciling another run. It must share the already running seal.
            replies = []
            owner.agent_id = "agent"
            owner._slurm_agent = SimpleNamespace(
                replay_pending=lambda ack: replies.append(ack(evidence)),
            )
            owner.slurm_assignments.list_run_unreleased = lambda uri: ()
            owner.acknowledge_slurm_pending = MethodType(LocalDaemonExecution.acknowledge_slurm_pending, owner)
            owner._slurm_record_steps = MethodType(LocalDaemonExecution._slurm_record_steps, owner)
            with pytest.raises(StopIteration) as done:
                unused_authority = object.__new__(_ScopedCoordinatorAuthority)
                next(LocalDaemonExecution._reconcile_slurm_steps(owner, "peer-run", unused_authority))
            assert done.value.value == (False, None)
            assert replies[0]['disposition'] == 'pending' and not release.is_set()
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
    record: Any = SimpleNamespace(assignment=SimpleNamespace(assignment_id='A'), fence='fence', delivery={}, report=None, publication_cancelled_at=None)
    owner: Any = SimpleNamespace(
        slurm_assignments=SimpleNamespace(schema_version=5, read=lambda _: SimpleNamespace(publication_completed_at=None)),
        config=SimpleNamespace(coordinator_shared_roots={}),
        _slurm_chunk_futures={},
        _slurm_storage_futures={'A': (future, None)}, _slurm_storage_errors={},
        _slurm_storage_failures={}, _slurm_storage_retry_at={}, _slurm_storage_failed_publications=set(),
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
    )
    evidence = {'assignment': {'assignment_id': 'A'}, 'sequence': 1, 'provider_released': True, 'release': {'state': 'CONTAINED'}}
    def acknowledge(*args, **kwargs):
        raise _SlurmRetentionRequired(owner, record, evidence)
    owner._slurm_storage_count = MethodType(LocalDaemonExecution._slurm_storage_count, owner)
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
    record: Any = SimpleNamespace(
        assignment=SimpleNamespace(agent_id='agent', agent_root_id='root'),
        fence='fence', bootstrap_incarnation='bootstrap', start_consumed=True,
        publication_completed_at='2026-11-15T00:00:00Z', publication_cancelled_at=None,
    )
    owner: Any = SimpleNamespace(
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
    from loom.queue._owner_journals import SlurmStorageFacts

    record = SlurmStorageFacts(
        assignment_id='A', compute_released_at='released-at', provider_released=True,
        publication_requested_at='requested-at', publication_completed_at=None, publication_cancelled_at=None,
        agent_evidence_accepted_at='accepted-at',
    )
    owner: Any = SimpleNamespace(
        _slurm_chunk_futures={},
        _slurm_storage_futures={}, _slurm_storage_errors={}, _slurm_storage_retry_at={},
        _slurm_storage_progress={}, _slurm_storage_progress_lock=Lock(),
    )
    def observed_item() -> dict[str, Any]:
        view = LocalDaemonExecution.slurm_storage_observations(owner, [record])
        item, = cast(list[dict[str, Any]], view['assignments'])
        return item

    item = observed_item()
    assert item['compute'] == {'state': 'released', 'released_at': 'released-at'}
    assert item['publication']['state'] == 'pending'
    assert item['storage']['progress'] is None
    assert item['storage']['worker_state_consistency'] == 'process_local'
    owner._slurm_storage_errors['A'] = 'ownership conflict'
    item = observed_item()
    assert item['storage']['state'] == 'failed'
    assert item['storage']['last_error'] == 'ownership conflict'


def test_reconciliation_replays_cancelled_release_before_missing_publication_marker():
    """Authority cancellation may commit before its assignment marker does."""
    evidence = {'provider_released': True, 'release': {'state': 'CONTAINED'}}
    record: Any = SimpleNamespace(
        assignment=SimpleNamespace(assignment_id='A', run_uri='run', attempt_id='attempt',
                                   agent_id='agent', agent_root_id='root'),
        publication_requested_at='requested', publication_completed_at=None,
        publication_cancelled_at=None,
    )
    calls = []
    owner: Any = SimpleNamespace(
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

    owner: Any = SimpleNamespace(config=SimpleNamespace(coordinator_shared_roots={}))
    original: Any = SimpleNamespace(assignment='assignment', fence='fence',
                               bootstrap_incarnation='incarnation', delivery={})
    evidence = {'provider_released': True}
    continuation = _SlurmRetentionRequired(owner, original, evidence)
    continuation.completed = True
    assert continuation.validates(owner, original, evidence)
    current = copy(original)
    setattr(current, changed, {'changed': True} if changed == 'delivery' else 'changed')
    assert not continuation.validates(owner, current, evidence)


def test_pending_chunk_deduplicates_and_does_not_block_peer_storage():
    from typing import Any
    from loom.queue._publication_guards import PublicationGuards
    from time import monotonic, sleep

    entered, release, wake = Event(), Event(), Event()
    calls = []

    def write(assignment, *args, **kwargs):
        calls.append(assignment)
        if assignment == "A":
            entered.set()
            assert release.wait(5)
        return 3

    owner: Any = SimpleNamespace(
        slurm_assignments=SimpleNamespace(write_output_chunk=write),
        _slurm_chunk_futures={}, _slurm_storage_futures={},
        _daemon_owner=lambda: SimpleNamespace(_wake=wake, _publication_guards=guards),
    )
    guards = PublicationGuards()
    owner._slurm_storage_count = MethodType(LocalDaemonExecution._slurm_storage_count, owner)
    def record(name):
        return SimpleNamespace(assignment=SimpleNamespace(assignment_id=name), bootstrap_incarnation="boot")
    evidence = {"identity": {}, "transfer_id": "transfer", "offset": 0, "data": "YWJj", "final": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner._slurm_storage_workers = pool
        try:
            assert LocalDaemonExecution._poll_slurm_output(owner, record("A"), evidence)["disposition"] == "pending"
            assert entered.wait(1)
            for _ in range(20):
                assert LocalDaemonExecution._poll_slurm_output(owner, record("A"), evidence)["disposition"] == "pending"
            deadline = monotonic() + 2
            while LocalDaemonExecution._poll_slurm_output(owner, record("B"), evidence).get("received") != 3:
                assert monotonic() < deadline
                sleep(0.005)
            assert calls == ["A", "B"]
            assert not release.is_set()
        finally:
            release.set()
        owner._slurm_chunk_futures["A"][1].result(timeout=2)
        assert LocalDaemonExecution._poll_slurm_output(owner, record("A"), evidence) == {"received": 3}
        assert calls == ["A", "B"]
