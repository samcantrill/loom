"""Bounded observation steps. An expired watcher releases no running worker."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, wait
from contextvars import copy_context
from threading import Lock, Thread
from time import monotonic

WORKERS = 3
_lock = Lock()
_active: dict[tuple, tuple[bool, Future]] = {}


def _offer(key, dispatch, function, args):
    with _lock:
        current = _active.get(key)
        if current:
            return current[1] if current[0] == dispatch else None
        if len(_active) >= WORKERS:
            return None
        future = Future()
        _active[key] = (dispatch, future)

        def run():
            try:
                result = function(*args)
            except BaseException as exc:
                with _lock:
                    del _active[key]
                    future.set_exception(exc)
            else:
                with _lock:
                    del _active[key]
                    future.set_result(result)

        try:
            Thread(target=copy_context().run, args=(run,), daemon=True,
                   name="loom-fleet-check").start()
        except BaseException:
            del _active[key]
            raise
        return future


def completed_steps(directory, records, selected, *, dispatch, deadline, advance, started, transfers=()):
    """Offer one fair turn per selected ID, yielding results before later waits."""
    count = "dispatch_turns" if dispatch else "observation_turns"
    pending = sorted(selected, key=lambda key: records[key].get(count, 0))
    running: dict[Future, str] = {}
    while pending or running:
        left = deadline - monotonic()
        if left > 0:
            # Divide the allowance among successive groups. Preserve room for
            # a slow late check when an earlier native request uses its full cut.
            groups = max(1, (len(pending) + len(running) + WORKERS - 1) // WORKERS)
            now = monotonic()
            fair_end = min(deadline, now + left / groups)
            for identity in tuple(pending):
                # Known transfers can use their whole fair share. An unknown
                # check gets a short first observation so peers can report.
                step_end = fair_end if identity in transfers else min(fair_end, now + 10.0)
                if len(running) >= WORKERS or monotonic() >= step_end:
                    break
                future = _offer((directory, identity), dispatch, advance, (identity, dispatch, step_end))
                if future is not None:
                    pending.remove(identity)
                    running[future] = identity
                    records[identity][count] = records[identity].get(count, 0) + 1
                    started()
        if not running:
            return
        ready, _ = wait(running, timeout=max(0, deadline - monotonic()),
                        return_when=FIRST_COMPLETED)
        if not ready:
            return
        for future in ready:
            yield running.pop(future), future
