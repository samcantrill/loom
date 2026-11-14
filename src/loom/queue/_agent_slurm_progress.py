"""Single scheduler writer with acknowledgements on the service owner thread."""

from concurrent.futures import Future
from queue import Empty, Queue
from threading import Lock
from time import monotonic

from ._agent_progress import _Spawn, _delay, _external, _steps
from .errors import QueueError, QueueServiceError


def drive_operation(client, operation, binding, *args, **kwargs):
    """Yield scheduler IO while retaining ordered, synchronous acknowledgements.

    Only AgentSlurmJobs state crosses into the dedicated worker. HTTP/session
    mutations stay on the manager. A worker cannot pass its next journal effect
    until the manager returns that exact acknowledgement. Shutdown closes the
    bridge so an outstanding callback cannot deadlock executor shutdown.
    """
    def acknowledge(evidence):
        return client._call("slurm_work", {**binding, "evidence": dict(evidence)})

    if not client._service_progress:
        return operation(*args, acknowledge=acknowledge, **kwargs)

    pending = Queue(maxsize=1)
    lock = Lock()
    closed = False
    outstanding = None

    def request(evidence):
        nonlocal outstanding
        reply = Future()
        with lock:
            if closed:
                raise QueueServiceError("scheduler acknowledgement owner closed")
            outstanding = reply
            pending.put_nowait((dict(evidence), reply))
        try:
            return reply.result()
        finally:
            with lock:
                if outstanding is reply:
                    outstanding = None

    def work():
        return operation(*args, acknowledge=request, **kwargs)

    view = yield _Spawn(_external("slurm", work))
    next_renewal = monotonic()
    try:
        while not view.complete:
            try:
                evidence, reply = pending.get_nowait()
            except Empty:
                pass
            else:
                try:
                    value = yield from _steps(
                        client._call, "slurm_work", {**binding, "evidence": evidence},
                    )
                except BaseException as error:
                    reply.set_exception(error)
                    raise
                else:
                    reply.set_result(value)
            # Do not apply reload/drain effects while the scheduler owns a
            # captured profile. The separate receipt view remains responsive;
            # effects are applied at the existing next scheduler boundary.
            if monotonic() >= next_renewal:
                next_renewal = monotonic() + 5
                if not client._drained and not client._restart_with_retained_work:
                    try:
                        yield from _steps(client.renew_current_offer, binding["session_id"])
                    except QueueError:
                        # The durable renewal is retried by normal maintenance.
                        pass
            yield from _delay(0.01)
        if view.error is not None:
            raise view.error
        return view.value
    finally:
        with lock:
            closed = True
            if outstanding is not None and not outstanding.done():
                outstanding.set_exception(QueueServiceError("scheduler acknowledgement owner closed"))
