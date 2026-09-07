"""Identity ordering tests; numeric reuse is simulated, never induced on the host."""

from types import SimpleNamespace
import os
import signal
from typing import Any

import pytest

from loom.queue._process_group import OwnedProcessGroup


def test_root_exit_does_not_reap_before_last_signal_and_reuse_never_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    now = [0.0]
    present = [True]

    def waitid(*args: Any) -> object:
        assert args[-1] & os.WNOWAIT
        events.append("observe-root")
        return SimpleNamespace(si_code=os.CLD_EXITED, si_status=7)

    def wait(*, timeout: int) -> int:
        assert timeout == 0
        events.append("reap")
        return 7

    def killpg(pid: int, signum: int) -> None:
        assert pid == 12345
        events.append(signum)
        if signum:
            assert "reap" not in events
        elif not present[0]:
            raise ProcessLookupError

    monkeypatch.setattr(os, "waitid", waitid)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr("loom.queue._process_group.monotonic", lambda: now[0])
    group = OwnedProcessGroup(SimpleNamespace(pid=12345, wait=wait))  # type: ignore[arg-type]
    assert group.root_status() == 7
    assert group.poll() is None
    assert "reap" not in events
    now[0] = 2.1
    assert group.poll() is None  # root reaped, but group is still present
    assert events.count("reap") == 1
    assert (
        events.index(signal.SIGTERM)
        < events.index(signal.SIGKILL)
        < events.index("reap")
    )
    group.terminate()
    group.kill()
    assert group.poll() is None  # simulate numeric reuse after reap
    present[0] = False
    assert group.contain() is True
    assert group.poll() == 7
    assert events.count(signal.SIGTERM) == events.count(signal.SIGKILL) == 1
    assert events.count("reap") == 1


def test_lost_creation_owned_child_fails_closed_without_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lost(*args: Any) -> None:
        raise ChildProcessError

    def signal_forbidden(*args: Any) -> None:
        pytest.fail("lost ownership must not authorize group signaling")

    monkeypatch.setattr(os, "waitid", lost)
    monkeypatch.setattr(os, "killpg", signal_forbidden)
    group = OwnedProcessGroup(SimpleNamespace(pid=12345))  # type: ignore[arg-type]
    assert group.poll() is None
    group.terminate()
    group.kill()
    assert not group.contain()


@pytest.mark.parametrize(
    ("start", "contain_at", "settlement_deadline"),
    [
        ("terminate", 3.0, 4.0),
        ("terminate", 6.0, 4.0),
        ("poll", 3.0, 4.0),
        ("kill", 1.0, 2.0),
        ("early_kill", 1.0, 2.5),
    ],
)
def test_cleanup_budget_is_shared_by_delayed_and_repeated_calls(
    monkeypatch: pytest.MonkeyPatch,
    start: str,
    contain_at: float,
    settlement_deadline: float,
) -> None:
    now = [0.0]
    present = [True]
    events: list[object] = []

    def waitid(*args: Any) -> object:
        assert args[-1] & os.WNOWAIT
        return SimpleNamespace(si_code=os.CLD_EXITED, si_status=7)

    def wait(*, timeout: int) -> int:
        assert timeout == 0
        events.append("reap")
        return 7

    def killpg(pid: int, signum: int) -> None:
        assert pid == 12345
        if signum:
            assert "reap" not in events
            events.append(signum)
        elif not present[0]:
            raise ProcessLookupError

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(os, "waitid", waitid)
    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr("loom.queue._process_group.monotonic", lambda: now[0])
    monkeypatch.setattr("loom.queue._process_group.sleep", sleep)
    group = OwnedProcessGroup(SimpleNamespace(pid=12345, wait=wait))  # type: ignore[arg-type]
    if start == "poll":
        assert group.poll() is None
    elif start == "kill":
        group.kill()
    else:
        group.terminate()
        if start == "early_kill":
            now[0] = 0.5
            group.kill()

    now[0] = contain_at
    assert group.contain() is False
    assert now[0] == pytest.approx(max(contain_at, settlement_deadline))
    assert events == (
        [signal.SIGKILL, "reap"]
        if start == "kill"
        else [signal.SIGTERM, signal.SIGKILL, "reap"]
    )
    stopped_at = now[0]
    cleanup_events = events.copy()
    for _ in range(2):
        group.terminate()
        group.kill()
        assert group.contain() is False
        assert group.poll() is None
        assert now[0] == stopped_at
        assert events == cleanup_events

    present[0] = False
    assert group.contain() is True
    assert group.poll() == 7
    assert now[0] == stopped_at
    assert events == cleanup_events
