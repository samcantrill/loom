"""Private, cooperative outbound progress on one state-owning thread.

Generators contain the existing journal/provider transitions. Only an explicit
external operation runs in a worker; synchronous clients drive the same steps
inline. A submitted operation owns its slot until its actual call returns.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextvars import ContextVar
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from functools import wraps
from inspect import isgenerator
from time import monotonic, sleep
from typing import Any, Concatenate


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


@dataclass(frozen=True)
class _Spawn:
    progress: Generator[Any, Any, Any]


_Progress = _External | _Delay | _Spawn
_owner: ContextVar[object | None] = ContextVar("agent_progress_owner", default=None)


class _Gate:
    """A manager-local, reentrant exclusion boundary across finite yields."""

    def __init__(self) -> None:
        self.owner: object | None = None
        self.waiters: list[object] = []

    def run[R](
        self, progress: Generator[_Progress, Any, R]
    ) -> Generator[_Progress, Any, R]:
        owner = _owner.get()
        if owner is None or self.owner is owner:
            return (yield from progress)
        self.waiters.append(owner)
        try:
            while self.owner is not None or self.waiters[0] is not owner:
                yield from _delay(0.01)
            self.owner = owner
            try:
                return (yield from progress)
            finally:
                self.owner = None
        finally:
            self.waiters = [item for item in self.waiters if item is not owner]


def _serialized(attribute: str):
    def decorate[**P, R](
        function: Callable[Concatenate[Any, P], Generator[_Progress, Any, R]],
    ) -> Callable[Concatenate[Any, P], Generator[_Progress, Any, R]]:
        @wraps(function)
        def serialized(
            self: Any, *args: P.args, **kwargs: P.kwargs
        ) -> Generator[_Progress, Any, R]:
            return (
                yield from getattr(self, attribute).run(function(self, *args, **kwargs))
            )

        return serialized

    return decorate


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
        token = _owner.set(_owner.get() or object())
        try:
            return drive(*args, **kwargs)
        finally:
            _owner.reset(token)

    def drive(*args: P.args, **kwargs: P.kwargs) -> R:
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
                elif isinstance(step, _Spawn):
                    raise RuntimeError("assignment views require the service manager")
                else:
                    value = step.execute()
            except BaseException as caught:
                error = caught

    synchronous._progress = function  # type: ignore[attr-defined]
    return synchronous


def _external(
    lane: str, function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Generator[_Progress, Any, Any]:
    try:
        return (yield _External(lane, function, args, tuple(kwargs.items())))
    except Exception as error:
        # Preserve the original error and its dispatch uncertainty. This finite
        # operation label lets the service diagnose recovery without its message.
        error.__dict__.setdefault("_agent_external_step", getattr(function, "__name__", "external_operation"))
        raise


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
    assignment_id: str | None = None


def _set_assignment_owner(assignment_id: str) -> None:
    view = _owner.get()
    if isinstance(view, _View):
        view.assignment_id = assignment_id


def _owns_assignment(assignment_id: str) -> bool:
    view = _owner.get()
    return not isinstance(view, _View) or view.assignment_id == assignment_id


def _run_manager(
    primary: Generator[_Progress, Any, Any], controls: Generator[_Progress, Any, Any]
) -> Any:
    """Rotate ready views with no executor queue beyond the occupied slots."""
    budgets = {"bulk": 2, "control": 2, "poll": 1}
    pools = {
        lane: ThreadPoolExecutor(
            max_workers=limit, thread_name_prefix=f"loom-agent-{lane}"
        )
        for lane, limit in budgets.items()
    }
    views = [_View(primary), _View(controls)]
    ready: dict[str, list[_View]] = {lane: [] for lane in budgets}
    primary_view = views[0]
    controls_view = views[1]
    cursor = 0
    try:
        while not primary_view.complete:
            now = monotonic()
            order = views[cursor:] + views[:cursor]
            cursor = (cursor + 1) % len(views)
            for view in order:
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
                    token = _owner.set(view)
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
                    except BaseException as error:
                        if view is primary_view:
                            raise
                        if view is controls_view:
                            primary_view.error = error
                            if primary_view.future is None:
                                primary_view.pending = None
                        view.error = error
                        view.complete = True
                        continue
                    finally:
                        _owner.reset(token)
                    view.error = None
                    view.value = None
                if isinstance(view.pending, _Spawn):
                    child = _View(view.pending.progress)
                    views.append(child)
                    view.value = child
                    view.pending = None
                if isinstance(view.pending, _External):
                    lane = view.pending.lane
                    if not any(item is view for item in ready[lane]):
                        ready[lane].append(view)
            for lane, queue in ready.items():
                occupied = sum(
                    other.future is not None
                    and isinstance(other.pending, _External)
                    and other.pending.lane == lane
                    for other in views
                )
                while queue and occupied < budgets[lane]:
                    view = queue.pop(0)
                    assert isinstance(view.pending, _External)
                    view.future = pools[lane].submit(view.pending.execute)
                    occupied += 1
            views = [
                view for view in views if not view.complete or view is primary_view
            ]
            futures = [view.future for view in views if view.future is not None]
            delays = [
                view.pending.due for view in views if isinstance(view.pending, _Delay)
            ]
            timeout = max(0, min(delays) - monotonic()) if delays else None
            if any(not view.complete and view.pending is None for view in views):
                timeout = 0
            if futures:
                wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
            elif delays:
                sleep(timeout or 0)
        return primary_view.value
    finally:
        # No cancelled future is interpreted as no effect or freed capacity.
        for pool in pools.values():
            pool.shutdown(wait=True)
        for view in views:
            view.progress.close()
