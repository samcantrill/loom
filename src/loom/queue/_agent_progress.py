"""Private, cooperative outbound progress on one state-owning thread.

Generators contain the existing journal/provider transitions. Only an explicit
external operation runs in a worker; synchronous clients drive the same steps
inline. A submitted operation owns its slot until its actual call returns.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from functools import wraps
from inspect import isgenerator
from time import monotonic, sleep
from typing import Any


@dataclass(frozen=True)
class _External:
    lane: str
    function: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: tuple[tuple[str, Any], ...]

    def execute(self) -> Any:
        return self.function(*self.args, **dict(self.kwargs))


@dataclass(frozen=True)
class _Delay:
    due: float


_Progress = _External | _Delay


def _steps(
    function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Generator[_Progress, Any, Any]:
    implementation = getattr(function, "_progress", None)
    if implementation is not None:
        owner = getattr(function, "__self__", None)
        result = (
            implementation(*args, **kwargs)
            if owner is None
            else implementation(owner, *args, **kwargs)
        )
    else:
        result = function(*args, **kwargs)
    if isgenerator(result):
        return (yield from result)
    return result


def _cooperative[**P, R](
    function: Callable[P, Generator[_Progress, Any, R]],
) -> Callable[P, R]:
    @wraps(function)
    def synchronous(*args: P.args, **kwargs: P.kwargs) -> R:
        progress = function(*args, **kwargs)
        value: Any = None
        error: BaseException | None = None
        while True:
            try:
                step = (
                    progress.throw(error) if error is not None else progress.send(value)
                )
            except StopIteration as complete:
                return complete.value
            error = None
            try:
                if isinstance(step, _Delay):
                    sleep(max(0, step.due - monotonic()))
                    value = None
                else:
                    value = step.execute()
            except BaseException as caught:
                error = caught

    synchronous._progress = function  # type: ignore[attr-defined]
    return synchronous


def _external(
    lane: str, function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Generator[_Progress, Any, Any]:
    return (yield _External(lane, function, args, tuple(kwargs.items())))


def _delay(seconds: float) -> Generator[_Progress, Any, None]:
    yield _Delay(monotonic() + seconds)


@dataclass
class _View:
    progress: Generator[_Progress, Any, Any]
    pending: _Progress | None = None
    future: Future[Any] | None = None
    value: Any = None
    error: BaseException | None = None
    complete: bool = False


def _run_serial(
    primary: Generator[_Progress, Any, Any], controls: Generator[_Progress, Any, Any]
) -> Any:
    """Advance one assignment and reserved receipt handling without a job future."""
    budgets = {"bulk": 2, "control": 2, "poll": 1}
    pools = {
        lane: ThreadPoolExecutor(
            max_workers=limit, thread_name_prefix=f"loom-agent-{lane}"
        )
        for lane, limit in budgets.items()
    }
    views = [_View(primary), _View(controls)]
    try:
        while not views[0].complete:
            now = monotonic()
            for view in views:
                if view.complete:
                    continue
                if view.future is not None:
                    if not view.future.done():
                        continue
                    try:
                        view.value = view.future.result()
                    except BaseException as error:
                        view.error = error
                    view.future = None
                    view.pending = None
                if isinstance(view.pending, _Delay):
                    if view.pending.due > now:
                        continue
                    view.pending = None
                if view.pending is None:
                    try:
                        view.pending = (
                            view.progress.throw(view.error)
                            if view.error is not None
                            else view.progress.send(view.value)
                        )
                    except StopIteration as complete:
                        view.value = complete.value
                        view.complete = True
                        continue
                    view.error = None
                    view.value = None
                if isinstance(view.pending, _External):
                    lane = view.pending.lane
                    occupied = sum(
                        other.future is not None
                        and isinstance(other.pending, _External)
                        and other.pending.lane == lane
                        for other in views
                    )
                    if occupied < budgets[lane]:
                        view.future = pools[lane].submit(view.pending.execute)
            futures = [view.future for view in views if view.future is not None]
            delays = [
                view.pending.due for view in views if isinstance(view.pending, _Delay)
            ]
            timeout = max(0, min(delays) - monotonic()) if delays else None
            if futures:
                wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
            elif delays:
                sleep(timeout or 0)
        return views[0].value
    finally:
        # No cancelled future is interpreted as no effect or freed capacity.
        for pool in pools.values():
            pool.shutdown(wait=True)
        for view in views:
            view.progress.close()
