"""Scheduler IO yields without moving HTTP/session mutations to a worker."""

from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from loom.queue._agent_progress import _run_manager, _steps, _delay
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("acknowledgement_fails", [False, True])
def test_blocked_scheduler_preserves_control_renewal_and_acknowledgement_owner(acknowledgement_fails):
    started, release, control_advanced, renewed = Event(), Event(), Event(), Event()
    owner_threads, worker_threads, results, failures = [], [], [], []

    def replay(acknowledge):
        worker_threads.append(get_ident())
        started.set()
        assert release.wait(10)
        results.append(acknowledge({"sequence": 1}))

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
        yield from _steps(LocalDaemonAgentHttpClient.drive_slurm_jobs, agent)

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

    owner = SimpleNamespace(
        agent_slurm_work_slots=BoundedSemaphore(2),
        agent_control_wait_slots=BoundedSemaphore(1),
        agent_work_wait_slots=BoundedSemaphore(1),
    )
    acquire = lambda operation: _MutualTlsHttpServer.acquire_agent_wait(owner, "agent", operation)
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


def test_slurm_capacity_reply_is_retryable_without_acknowledgement():
    from io import BytesIO
    from loom.queue.agent_session_transport import _read_agent_reply, _IndeterminateAgentProtocolError

    response = BytesIO(b'{"ok":false,"error":"slurm_work_capacity"}')
    response.status = 503
    connection = SimpleNamespace(request=lambda *args, **kwargs: None, getresponse=lambda: response)
    with pytest.raises(_IndeterminateAgentProtocolError):
        _read_agent_reply(connection, "slurm_work", b'{}', "agent")
