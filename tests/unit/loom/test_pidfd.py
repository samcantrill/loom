"""Process-descriptor operations with and without CPython's optional wrappers."""

import ctypes
import errno
import os
import select
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from loom import _pidfd


@pytest.fixture
def direct_syscalls(monkeypatch):
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)


def test_standard_wrappers_remain_preferred(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "pidfd_open", lambda pid: calls.append(("open", pid)) or 42, raising=False)
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda fd, sig: calls.append(("send", fd, sig)), raising=False)
    monkeypatch.setattr(_pidfd, "_syscall", lambda *args: pytest.fail("native wrapper bypassed"))
    assert _pidfd.open_pidfd(1234) == 42
    _pidfd.send_pidfd_signal(42, signal.SIGTERM)
    assert calls == [("open", 1234), ("send", 42, signal.SIGTERM)]


def test_syscall_fallback_preserves_owned_process_identity(direct_syscalls):
    if sys.platform != "linux" or os.uname().machine != "x86_64" or ctypes.sizeof(ctypes.c_long) != 8:
        pytest.skip("physical syscall fallback requires Linux x86-64 LP64")
    _pidfd.require_pidfd_support()
    child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"])
    descriptor = None
    try:
        descriptor = _pidfd.open_pidfd(child.pid)
        assert not os.get_inheritable(descriptor)
        assert not select.select([descriptor], [], [], 0)[0]
        _pidfd.send_pidfd_signal(descriptor, signal.SIGTERM)
        assert select.select([descriptor], [], [], 5)[0]
        observed = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        assert observed.si_pid == child.pid
        assert child.wait(timeout=5) == -signal.SIGTERM
        with pytest.raises(ProcessLookupError):
            _pidfd.send_pidfd_signal(descriptor, 0)
        with pytest.raises(OSError) as invalid:
            _pidfd.send_pidfd_signal(-1, 0)
        assert invalid.value.errno == errno.EBADF
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if descriptor is not None:
            os.close(descriptor)


def test_unselected_abi_never_attempts_syscall(monkeypatch, direct_syscalls):
    monkeypatch.setattr(sys, "platform", "unsupported")
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: pytest.fail("unsupported ABI entered libc"))
    with pytest.raises(OSError) as unsupported:
        _pidfd.open_pidfd(os.getpid())
    assert unsupported.value.errno == errno.ENOTSUP


def test_kernel_refusal_preserves_errno(monkeypatch, direct_syscalls):
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        pytest.skip("syscall admission requires Linux x86-64")

    def unsupported(*args):
        ctypes.set_errno(errno.ENOSYS)
        return -1

    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: SimpleNamespace(syscall=unsupported))
    with pytest.raises(OSError) as failure:
        _pidfd.require_pidfd_support()
    assert failure.value.errno == errno.ENOSYS


def test_support_probe_closes_descriptor_when_signaling_is_denied(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    monkeypatch.setattr(_pidfd, "open_pidfd", lambda _: read_fd)

    def denied(*args):
        raise PermissionError(errno.EPERM, "pidfd signaling denied")

    monkeypatch.setattr(_pidfd, "send_pidfd_signal", denied)
    with pytest.raises(PermissionError):
        _pidfd.require_pidfd_support()
    with pytest.raises(OSError) as closed:
        os.fstat(read_fd)
    assert closed.value.errno == errno.EBADF
