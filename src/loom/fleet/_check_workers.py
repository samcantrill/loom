"""Bounded observation steps. An expired watcher releases no running worker."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, wait
from contextvars import copy_context
from dataclasses import dataclass
from functools import partial
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable

from loom._observer_deadline import observer_until

WORKERS = 3
_lock = Lock()
_active: dict[tuple, tuple[str, Future]] = {}


def _offer(key, kind, function, args):
    with _lock:
        current = _active.get(key)
        if current:
            return current[1] if current[0] == kind else None
        if len(_active) >= WORKERS or (
            kind == "transfer" and sum(item[0] == "transfer" for item in _active.values()) >= WORKERS - 1
        ):
            return None
        future = Future()
        _active[key] = (kind, future)

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


def completed_steps(directory, records, selected, *, dispatch, deadline, advance, started,
                    transfers=(), next_step=None, detach_transfers=False):
    """Offer one fair turn per selected ID, yielding results before later waits."""
    count = "dispatch_turns" if dispatch else "observation_turns"
    pending = sorted(selected, key=lambda key: records[key].get(count, 0))
    transfers = set(transfers)
    running: dict[Future, str] = {}
    while pending or running:
        left = deadline - monotonic()
        if left > 0:
            # First dispatch offers every selected slot an opportunity before
            # download. Accepted observations rotate across durable turn counts.
            groups = max(1, (len(pending) + len(running) + WORKERS - 1) // WORKERS)
            now = monotonic()
            fair_end = min(deadline, now + left / groups)
            for identity in tuple(pending):
                if len(running) >= WORKERS:
                    break
                step_end = min(fair_end if dispatch else deadline, now + 10.0)
                if identity in transfers:
                    step_end = deadline
                if monotonic() >= step_end:
                    break
                kind = "dispatch" if dispatch else "transfer" if identity in transfers else "observe"
                future = _offer((directory, identity), kind, advance, (identity, kind, step_end))
                if future is not None:
                    pending.remove(identity)
                    running[future] = identity
                    records[identity][count] = records[identity].get(count, 0) + 1
                    started()
        if not running:
            return
        # Follow can release the fleet writer while only downloads remain.
        # Per-check owners retain results and partial ranges.
        timeout = max(0, deadline - monotonic())
        if detach_transfers and all(key in transfers for key in running.values()):
            timeout = 0
        ready, _ = wait(running, timeout=timeout, return_when=FIRST_COMPLETED)
        if not ready:
            return
        for future in ready:
            identity = running.pop(future)
            yield identity, future
            next_kind = next_step(identity) if next_step is not None and future.exception() is None else None
            if next_kind == "transfer" and identity not in transfers:
                transfers.add(identity)
                pending.insert(0, identity)
            elif next_kind == "observe" and identity in transfers:
                transfers.remove(identity)
                pending.append(identity)


def wait_for_checks(directory, targets, deadline, native_wait):
    """Watch a fair slice outside the writer, sharing slots with unfinished downloads."""
    with _lock:
        watches = {future for key, (kind, future) in _active.items()
                   if kind == "transfer" and key[0].is_relative_to(directory)}
    offered = 0
    for identity, hint in targets:
        if monotonic() >= deadline:
            break
        future = _offer((directory, "native-wait", identity), "wait", native_wait,
                        (identity, hint, deadline))
        if future is None:
            break
        watches.add(future)
        offered += 1
        if offered == WORKERS:
            break
    if watches:
        ready, _ = wait(watches, timeout=max(0, deadline - monotonic()), return_when=FIRST_COMPLETED)
        if any(future.exception() is None and future.result() for future in ready):
            return offered
    # Terminal admissions can still await release, publication or a fresh offer.
    # A bounded fallback also covers temporarily unavailable native waits.
    sleep(max(0, deadline - monotonic()))
    return offered


@dataclass(frozen=True)
class _Rpc:
    key: tuple
    invoke: Callable[[], Any]


def rpc(key, function, /, *args, **kwargs):
    """Suspend this host until one bounded physical request has returned."""
    return (yield _Rpc(key, partial(function, *args, **kwargs)))


def inline(flow):
    """Drive the same receipt sequence inside a caller that already owns a turn."""
    result = error = None
    while True:
        try:
            step = flow.send(result) if error is None else flow.throw(error)
        except StopIteration as end:
            return end.value
        try:
            result = step.invoke()
            error = None
        except Exception as exc:
            error = exc


def _invoke(step, end):
    with observer_until(end):
        return step.invoke()


def host_steps(directory, flows, deadline, unavailable):
    """Advance host sequences on one receipt writer, detaching at the absolute deadline.

    A string reserves a shared writer until its flow yields None. A float
    schedules the next observation without consuming a transport worker.
    """
    running, queued, results, errors = {}, {}, {}, []
    owners = {}
    writer_error = None

    def advance(name, result=None, error=None):
        nonlocal writer_error
        try:
            flow = flows[name]
            queued[name] = flow.send(result) if error is None else flow.throw(error)
        except StopIteration as end:
            results[name] = end.value
        except Exception as exc:
            errors.append(exc)
            if name in owners.values():
                # A lost shared mutation must be reconciled before another
                # host can derive an expected coordinator declaration.
                writer_error = exc
        if name not in queued:
            for lane in tuple(owners):
                if owners[lane] == name:
                    del owners[lane]

    # Prime all flows before any transport. Invalid initial intent aborts dispatch.
    for name in flows:
        if deadline is not None and monotonic() >= deadline:
            raise unavailable("host observation deadline expired before dispatch")
        advance(name)
    if errors:
        raise errors[0]
    while queued or running:
        if writer_error is not None:
            raise writer_error
        now = monotonic()
        if deadline is not None and now >= deadline:
            break
        wake = deadline
        groups = max(1, (len(queued) + len(running) + WORKERS - 1) // WORKERS)
        step_end = None if deadline is None else now + (deadline - now) / groups
        progressed = False
        for name, step in tuple(queued.items()):
            if isinstance(step, _Rpc):
                future = _offer((directory, *step.key), "host", _invoke, (step, step_end))
                if future is None:
                    continue
                running[future] = name
                del queued[name]
            elif isinstance(step, float) and step > now:
                wake = step if wake is None else min(wake, step)
                continue
            else:
                if isinstance(step, str):
                    if step in owners:
                        continue
                    owners[step] = name
                elif step is None:
                    for lane in tuple(owners):
                        if owners[lane] == name:
                            del owners[lane]
                del queued[name]
                advance(name)
                progressed = True
        if progressed:
            continue
        if not running and not queued:
            break
        # Saturation can belong to a previous observer. Wait for actual
        # transport exit before offering more work, even across invocations.
        with _lock:
            occupied = tuple(item[1] for item in _active.values())
        timeout = None if wake is None else max(0, wake - monotonic())
        if running or occupied:
            ready, _ = wait((*running, *occupied), timeout=timeout, return_when=FIRST_COMPLETED)
            for future in ready.intersection(running):
                name = running.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    advance(name, error=exc)
                else:
                    advance(name, result)
        elif timeout is not None and any(isinstance(step, float) for step in queued.values()):
            sleep(timeout)
    if errors:
        raise errors[0]
    if queued or running:
        raise unavailable("host observation deadline expired; resume the retained operation")
    return results
