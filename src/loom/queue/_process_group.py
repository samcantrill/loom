"""Creation-owned group cleanup for the two local queue process owners."""

from __future__ import annotations

import os
import signal
import subprocess
from threading import RLock
from time import monotonic, sleep


def require_group_wait_support() -> None:
    if not all(hasattr(os, name) for name in ("waitid", "WNOWAIT", "P_PID", "killpg")):
        raise OSError(
            "managed process-group cleanup requires non-reaping child waits "
            "(waitid/WNOWAIT); use a supported POSIX execution host"
        )


class OwnedProcessGroup:
    """Keep the unreaped session leader until the last possible group signal.

    The caller must have created ``process`` with ``start_new_session=True`` and
    must not independently wait for it. Root exit and group settlement are
    different observations. After the sole reap, numeric group checks may delay
    settlement conservatively, but can never authorize another group signal.
    """

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.pid = process.pid
        self.pgid = process.pid
        self.returncode: int | None = None
        self._lock = RLock()
        self._term_deadline: float | None = None
        self._cleanup_deadline: float | None = None
        self._kill_sent = False
        self._reaped = False
        self._settled = False
        self._ownership_lost = False

    def root_status(self) -> int | None:
        """Observe root exit without releasing its PID/PGID identity anchor."""
        with self._lock:
            if self.returncode is not None or self._ownership_lost:
                return self.returncode
            try:
                status = os.waitid(
                    os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
            except ChildProcessError:
                self._ownership_lost = True
                return None
            if status is not None:
                self.returncode = (
                    status.si_status
                    if status.si_code == os.CLD_EXITED
                    else -status.si_status
                )
            return self.returncode

    def terminate(self) -> None:
        with self._lock:
            if self._term_deadline is None and not self._kill_sent:
                if self._signal(signal.SIGTERM):
                    self._term_deadline = monotonic() + 2
                    self._cleanup_deadline = self._term_deadline + 2

    def kill(self) -> None:
        with self._lock:
            if not self._kill_sent:
                self._kill_sent = self._signal(signal.SIGKILL)
                if self._kill_sent:
                    deadline = monotonic() + 2
                    self._cleanup_deadline = (
                        deadline
                        if self._cleanup_deadline is None
                        else min(self._cleanup_deadline, deadline)
                    )

    def _signal(self, signum: signal.Signals) -> bool:
        if self._reaped or self._ownership_lost:
            return False
        self.root_status()
        if self._ownership_lost:
            return False
        try:
            os.killpg(self.pgid, signum)
        except ProcessLookupError:
            # A continuously owned, unreaped session leader reserves its group.
            # Losing that premise is not permission to signal a reused number.
            self._ownership_lost = True
            return False
        return True

    def settled(self) -> bool:
        """Observe settlement; never initiate cleanup or signal a numeric group."""
        with self._lock:
            if self._settled:
                return True
            if not self._reaped or self._ownership_lost:
                return False
            try:
                os.killpg(self.pgid, 0)
            except ProcessLookupError:
                self._settled = True
            except PermissionError:
                pass
            return self._settled

    def _advance_cleanup(self) -> bool:
        self.root_status()
        if self._ownership_lost:
            return False
        if (
            self._term_deadline is not None
            and monotonic() >= self._term_deadline
            and not self._kill_sent
        ):
            self.kill()
        if self._kill_sent and self.returncode is not None and not self._reaped:
            try:
                self._process.wait(timeout=0)
            except (ChildProcessError, subprocess.TimeoutExpired):
                self._ownership_lost = True
                return False
            self._reaped = True
        return self.settled()

    def poll(self) -> int | None:
        """Legacy adapter terminal observation, including root-first cleanup."""
        with self._lock:
            if self.root_status() is not None:
                self.terminate()
            return self.returncode if self._advance_cleanup() else None

    def contain(self) -> bool:
        """Consume the shared cleanup budget; never renew it on later calls."""
        with self._lock:
            if self.settled():
                return True
            self.terminate()
            while not self._advance_cleanup():
                if self._ownership_lost or self._cleanup_deadline is None:
                    return False
                remaining = self._cleanup_deadline - monotonic()
                if remaining <= 0:
                    return False
                sleep(min(0.02, remaining))
            return True
