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
        self._binding = None
        self._outstanding = {}
        self._delivered = OrderedDict()
        self._retiring = []

    def _discard(self, keys):
        for key in keys:
            view = self._outstanding.pop(key, None)
            if view is not None and not view.complete:
                # An HTTP call already in flight still consumes capacity.
                self._retiring.append(view)
            self._delivered.pop(key, None)

    def bind(self, binding):
        identity = binding["session_id"], binding["coordinator_epoch"]
        if identity != self._binding:
            self._discard(set(self._outstanding) | set(self._delivered))
            self._binding = identity

    def forget_results(self, assignment_id, *, keep_commit=False):
        self._discard([
            key for key in (*self._outstanding, *self._delivered)
            if key[0] == assignment_id and key[1] is not None
            and not (keep_commit and key[1] == "commit")
        ])

    def exchange(self, client, binding, evidence):
        self.bind(binding)
        body = {**binding, "cursor": None, "evidence": evidence}
        owner = evidence.get("assignment", {}).get("assignment_id", evidence.get("assignment_id"))
        key = owner, evidence.get("result_operation"), json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        now = monotonic()
        view = self._outstanding.get(key)
        if view is None:
            recent = self._delivered.get(key)
            if recent is not None and now < recent[1]:
                return recent[0]
            self._delivered.pop(key, None)
            self._retiring = [item for item in self._retiring if not item.complete]
            active = len(self._retiring) + sum(not item.complete for item in self._outstanding.values())
            if active >= 8 or len(self._outstanding) >= 32:
                raise SlurmEffectPending(0.05)
            self._outstanding[key] = yield _Spawn(_steps(client._call, "slurm_work", body))
            raise SlurmEffectPending(0.05)
        if not view.complete:
            raise SlurmEffectPending(0.05)
        del self._outstanding[key]
        if view.error is not None:
            raise view.error
        value = view.value
        if value.get("disposition") != "pending":
            if evidence.get("provider_released"):
                self._discard([other for other in (*self._outstanding, *self._delivered) if other[0] == owner])
            self._delivered[key] = value, now + 30
            if len(self._delivered) > 32:
                self._delivered.popitem(last=False)
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
