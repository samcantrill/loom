"""Kernel process identities for container supervision.

Some portable CPython builds omit pidfd wrappers even on a capable Linux host.
Prefer the standard wrappers. The fallback is limited to the Linux x86-64 LP64
ABI and uses the same kernel operations, never numeric-PID signaling. Callers
own the returned descriptor and supply kernel-derived PIDs/descriptors.
"""

from __future__ import annotations

import errno
import os
import signal
import sys


def _syscall(number: int, *arguments: object) -> int:
    import ctypes

    if (
        sys.platform != "linux"
        or os.uname().machine != "x86_64"
        or ctypes.sizeof(ctypes.c_void_p) != 8
        or ctypes.sizeof(ctypes.c_long) != 8
    ):
        raise OSError(errno.ENOTSUP, "pidfd syscall ABI is unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    call = getattr(library, "syscall", None)
    if call is None:
        raise OSError(errno.ENOTSUP, "pidfd syscall entry point is unavailable")
    call.restype = ctypes.c_long
    result = call(ctypes.c_long(number), *arguments)
    if result == -1:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return int(result)


def open_pidfd(pid: int) -> int:
    """Open a close-on-exec process descriptor; the caller must close it."""
    native = getattr(os, "pidfd_open", None)
    if native is not None:
        return native(pid)
    import ctypes

    # Linux x86-64 syscall numbers: pidfd_open=434, pidfd_send_signal=424.
    return _syscall(434, ctypes.c_int(pid), ctypes.c_uint(0))


def send_pidfd_signal(descriptor: int, signum: int) -> None:
    """Signal the process held by the descriptor, with no siginfo or flags."""
    native = getattr(signal, "pidfd_send_signal", None)
    if native is not None:
        native(descriptor, signum)
        return
    import ctypes

    _syscall(
        424,
        ctypes.c_int(descriptor),
        ctypes.c_int(signum),
        ctypes.c_void_p(None),
        ctypes.c_uint(0),
    )


def require_pidfd_support() -> None:
    """Verify opening and probing an owned identity before creating a payload."""
    descriptor = open_pidfd(os.getpid())
    try:
        send_pidfd_signal(descriptor, 0)
    finally:
        os.close(descriptor)
