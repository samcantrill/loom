"""Scheduler IO yields without moving HTTP/session mutations to a worker."""

from threading import Event, Thread, get_ident
from types import SimpleNamespace

from typing import Any

import pytest

from loom.queue._agent_progress import _run_manager, _steps, _delay
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue._slurm_result_transport import SlurmEffectPending

pytestmark = pytest.mark.unit


def test_completed_child_does_not_rethrow_an_external_error_it_handled():
    from loom.queue._agent_progress import _Spawn, _external

    def unavailable():
        raise OSError("temporary observation failure")

    def child():
        try:
            yield from _external("control", unavailable)
        except OSError:
            return "pending"

    def primary():
        view = yield _Spawn(child())
        while not view.complete:
            yield from _delay(0.001)
        assert view.error is None
        return view.value

    def controls():
        while True:
            yield from _delay(0.001)

    assert _run_manager(primary(), controls()) == "pending"


@pytest.mark.parametrize("acknowledgement_fails", [False, True])
def test_blocked_scheduler_preserves_control_renewal_and_acknowledgement_owner(acknowledgement_fails):
    started, release, control_advanced, renewed = Event(), Event(), Event(), Event()
    owner_threads, worker_threads, results, failures = [], [], [], []

    def replay(acknowledge):
        worker_threads.append(get_ident())
        started.set()
        assert release.wait(10)
        try:
            results.append(acknowledge({"sequence": 1}))
        except SlurmEffectPending:
            pass

    def call(operation, body):
        owner_threads.append(get_ident())
        if body["evidence"] is not None:
            if acknowledgement_fails:
                raise ValueError("acknowledgement failed")
            return {"acknowledged": 1}
        return {"tasks": [], "next_cursor": None}

    agent = SimpleNamespace(
        _service_progress=True, _drained=False, _restart_with_retained_work=False,
        _slurm_agent=SimpleNamespace(begin_reconciliation=lambda identity: None,
                                    replay_pending=replay, observation_policy=None),
        active_session=lambda: SimpleNamespace(session_id="session", coordinator_epoch="epoch"),
        _slurm_cursor=None, _call=call,
        renew_current_offer=lambda session: renewed.set() if started.is_set() else None,
    )

    def primary():
        while not results:
            yield from _steps(LocalDaemonAgentHttpClient.drive_slurm_jobs, agent)
            yield from _delay(0.001)

    def controls():
        while True:
            if started.is_set():
                control_advanced.set()
            yield from _delay(0.001)

    def run():
        try:
            _run_manager(primary(), controls())
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(10)
        assert control_advanced.wait(10)
        assert renewed.wait(10)
        assert not results
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive(), "worker acknowledgement must not deadlock shutdown"
    assert owner_threads and set(owner_threads) == {thread.ident}
    assert set(worker_threads).isdisjoint(owner_threads)
    if acknowledgement_fails:
        assert len(failures) == 1 and str(failures[0]) == "acknowledgement failed"
        assert results == []
    else:
        assert failures == []
        assert results == [{"acknowledged": 1}]


def test_slurm_request_capacity_does_not_consume_control_or_poll_slots():
    from threading import BoundedSemaphore
    from loom.queue.agent_session_transport import _MutualTlsHttpServer, _SlurmWorkCapacityError

    owner: Any = SimpleNamespace(
        agent_slurm_work_slots=BoundedSemaphore(2),
        agent_control_wait_slots=BoundedSemaphore(1),
        agent_work_wait_slots=BoundedSemaphore(1),
    )
    def acquire(operation):
        slot = _MutualTlsHttpServer.acquire_agent_wait(owner, "agent", operation)
        assert slot is not None
        return slot
    slots = [acquire("slurm_work"), acquire("slurm_work")]
    with pytest.raises(_SlurmWorkCapacityError):
        acquire("slurm_work")
    controls = acquire("control_wait")
    polls = acquire("poll")
    controls.release()
    polls.release()
    slots.pop().release()
    slots.append(acquire("slurm_work"))
    for slot in slots:
        slot.release()


def test_slow_http_ack_allows_same_agent_peer_submission_observation_and_cancel(tmp_path):
    from loom.queue._agent_progress import _cooperative, _external
    from loom.queue._agent_slurm import AgentSlurmJobs
    from loom.queue._agent_slurm_progress import drive_operation
    from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
    from tests.unit.loom.queue.test_agent_slurm import _profile, _task

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, tmp_path, retention_bytes=4 * 65 * 1024**2)
    AgentSlurmJobs.initialize(tmp_path)
    agent = AgentSlurmJobs(tmp_path, (profile,), asynchronous_preparation=True)
    entered, release, peer_cancelled = Event(), Event(), Event()
    failures, slow_requests = [], []

    def exchange(body):
        evidence = body["evidence"]
        if evidence["assignment"]["assignment_id"] == "assignment-1":
            slow_requests.append(evidence["sequence"])
            entered.set()
            assert release.wait(10)
        return {"sequence": evidence["sequence"], "cancel_requested": False}

    @_cooperative
    def call(operation, body):
        return (yield from _external("slurm_http", exchange, body))

    client = SimpleNamespace(
        _service_progress=True, _drained=False, _restart_with_retained_work=False,
        _call=call, renew_current_offer=lambda session: None,
    )
    binding = {"session_id": "session", "coordinator_epoch": "epoch"}
    first, peer = _task(profile), _task(profile, key="2")

    def primary():
        while True:
            yield from drive_operation(client, agent.replay_pending, binding)
            current = agent.journal.find("operation-2")
            observed = any(call[0] in {"squeue", "sacct"} for call in runner.calls)
            tasks = [first, {**peer, "cancel_requested": observed and current is not None and current.job_id is not None}]
            yield from drive_operation(client, agent.step_cycle, binding, tasks)
            current = agent.journal.find("operation-2")
            if current is not None and current.cancel_requested:
                peer_cancelled.set()
                if release.is_set():
                    return
            yield from _delay(0.001)

    def controls():
        while True:
            yield from _delay(0.001)

    def run():
        try:
            _run_manager(primary(), controls())
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        assert peer_cancelled.wait(5), failures
        assert not release.is_set()
        assert len(slow_requests) == 1, "pending HTTP must deduplicate exact outbox replay"
        assert sum(call[0] == "sbatch" for call in runner.calls) == 1
        assert any(call[0] in {"squeue", "sacct"} for call in runner.calls)
        assert any(call[0] == "scancel" for call in runner.calls)
    finally:
        release.set()
        thread.join(10)
        agent.close()
    assert not thread.is_alive()
    assert not failures


def test_slurm_capacity_reply_is_retryable_without_acknowledgement():
    from io import BytesIO
    from loom.queue.agent_session_transport import _read_agent_reply, _IndeterminateAgentProtocolError

    class Response(BytesIO):
        status = 503

    response = Response(b'{"ok":false,"error":"slurm_work_capacity"}')
    connection: Any = SimpleNamespace(request=lambda *args, **kwargs: None, getresponse=lambda: response)
    with pytest.raises(_IndeterminateAgentProtocolError):
        _read_agent_reply(connection, "slurm_work", b'{}', "agent")


def test_slurm_evidence_advances_while_both_bulk_workers_are_blocked(tmp_path, monkeypatch):
    from loom.queue import agent_session_transport as transport
    from loom.queue._agent_progress import _Spawn, _external

    entered = [Event(), Event()]
    release, acknowledged = Event(), Event()
    failures = []
    client = LocalDaemonAgentHttpClient(transport.AgentTlsClientConfig(
        "https://localhost:9443", tmp_path / "ca", tmp_path / "cert", tmp_path / "key",
    ))
    client._service_progress = True

    def exchange(config, operation, body, role, connection, reuse):
        assert operation == "slurm_work"
        return SimpleNamespace(value={"disposition": "pending"},
                               connection=SimpleNamespace(close=lambda: None))

    monkeypatch.setattr(transport, "_exchange_agent_request", exchange)

    def blocked(index):
        entered[index].set()
        assert release.wait(10)

    def bulk(index):
        yield from _external("bulk", blocked, index)

    def primary():
        yield _Spawn(bulk(0))
        yield _Spawn(bulk(1))
        while not all(event.is_set() for event in entered):
            yield from _delay(0.001)
        reply = yield from _steps(client._call, "slurm_work", {"evidence": None})
        assert reply["disposition"] == "pending"
        acknowledged.set()

    def controls():
        while True:
            yield from _delay(0.001)

    def run():
        try:
            _run_manager(primary(), controls())
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=run)
    thread.start()
    try:
        assert acknowledged.wait(5), "Slurm evidence was coupled to artifact transfer capacity"
        assert not release.is_set()
    finally:
        release.set()
        thread.join(10)
        client.close()
    assert not thread.is_alive()
    assert not failures
