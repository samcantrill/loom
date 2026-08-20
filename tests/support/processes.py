"""Private POSIX process identity helpers for fixture-owned lifecycle tests."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OwnedProcessIdentity:
    pid: int
    start_ticks: str


def capture_owned_process_identity(pid: int) -> OwnedProcessIdentity:
    """Capture a live fixture-owned process identity before any signal is sent."""

    return OwnedProcessIdentity(pid=pid, start_ticks=_start_ticks(pid))


def owned_process_is_live(identity: OwnedProcessIdentity) -> bool:
    try:
        return _start_ticks(identity.pid) == identity.start_ticks
    except ProcessLookupError:
        return False


def kill_owned_process(identity: OwnedProcessIdentity, signal_number: int) -> bool:
    """Signal only when the live process still matches the captured identity."""

    if not owned_process_is_live(identity):
        return False
    os.kill(identity.pid, signal_number)
    return True


def _start_ticks(pid: int) -> str:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    except FileNotFoundError as exc:
        raise ProcessLookupError(errno.ESRCH, "process does not exist", pid) from exc
    if len(fields) <= 21:
        raise RuntimeError(f"cannot read process start identity for PID {pid}")
    return fields[21]
