"""Single scheduler writer with acknowledgements on the service owner thread."""

from concurrent.futures import Future
from collections import OrderedDict
import json
from queue import Empty, Queue
from threading import Lock
from time import monotonic

from ._agent_progress import _Spawn, _delay, _external, _steps
from .errors import QueueError, QueueServiceError
from ._slurm_result_transport import SlurmEffectPending


class SlurmAcknowledgements:
    """Manager-owned finite HTTP attempts; journals remain the replay authority."""

    def __init__(self):
        self._views = OrderedDict()

    def exchange(self, client, binding, evidence):
        # A task-page cursor is not part of evidence identity. In particular,
        # pagination must not turn an exact replay into another HTTP operation.
        body = {key: value for key, value in binding.items() if key != "cursor"}
        body["cursor"] = None
        body["evidence"] = evidence
        key = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        now = monotonic()
        for old, (view, expires) in tuple(self._views.items()):
            if view.complete and now >= expires:
                del self._views[old]
        existing = self._views.get(key)
        if existing is None:
            if sum(not view.complete for view, _ in self._views.values()) >= 8:
                raise SlurmEffectPending(0.05)
            while len(self._views) >= 32:
                old = next((item for item, (view, _) in self._views.items() if view.complete), None)
                if old is None:
                    raise SlurmEffectPending(0.05)
                del self._views[old]
            view = yield _Spawn(_steps(client._call, "slurm_work", body))
            self._views[key] = view, float("inf")
            raise SlurmEffectPending(0.05)
        view, _ = existing
        self._views.move_to_end(key)
        if not view.complete:
            raise SlurmEffectPending(0.05)
        if view.error is not None:
            del self._views[key]
            raise view.error
        value = view.value
        if value.get("disposition") == "pending":
            # A completed receipt for unfinished storage must be polled again.
            del self._views[key]
        else:
            self._views[key] = view, now + 30
        return value


def drive_operation(client, operation, binding, *args, **kwargs):
    """Yield scheduler IO and each exact acknowledgement independently.

    Only AgentSlurmJobs state crosses into the dedicated worker. HTTP/session
    mutations stay on the manager. A worker cannot pass its next journal effect
    until the manager returns that exact acknowledgement. Pending HTTP ends
    only that assignment's turn. Shutdown closes the
    bridge so an outstanding callback cannot deadlock executor shutdown.
    """
    def acknowledge(evidence):
        return client._call("slurm_work", {**binding, "evidence": dict(evidence)})

    if not client._service_progress:
        return operation(*args, acknowledge=acknowledge, **kwargs)

    acknowledgements = getattr(client, "_slurm_acknowledgements", None)
    if acknowledgements is None:
        acknowledgements = client._slurm_acknowledgements = SlurmAcknowledgements()

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
                    value = yield from acknowledgements.exchange(client, binding, evidence)
                except Exception as error:
                    # Pending/uncertain attempts preserve the durable outbox.
                    # Protocol errors are still delivered to the journal owner.
                    reply.set_exception(error)
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
                if (not client._drained and not client._restart_with_retained_work
                    and not getattr(client, "_resident_poll_active", False)):
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
