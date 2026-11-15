"""Opt-in outer PID namespace for Apptainer and its host-side image helpers.

The stable PID-one shim deliberately never execs the runtime or changes its
credentials: doing so can clear the parent-death signal established by unshare.
All runtime processes, including helpers with their own process groups, remain
inside this namespace. Existing direct runtime commands do not select this mode.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from typing import Sequence

from loom._bounded_process import ProcessOutputLimitError, run_bounded_process


VERSION = "loom-apptainer-guard version 1"
_RUNTIME_VERSION = "apptainer version 1.5.3"
_UNSHARE_VERSION = "unshare from util-linux 2.37.4"


class _GuardError(RuntimeError):
    pass


class _Interrupted(BaseException):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def _executable(setting: str, default: str) -> str:
    selected = os.environ.get(setting, default)
    resolved = shutil.which(selected)
    if resolved is None:
        raise _GuardError(f"{setting} must select an available executable")
    return os.path.abspath(resolved)


def _qualify(command: str, expected: str) -> None:
    result = run_bounded_process(
        [command, "--version"], timeout=5, environment=None,
        output_limit=4096, text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise _GuardError(f"selected executable must report {expected!r}")


def _run_init(unshare: str, runtime: str, arguments: Sequence[str]) -> int:
    if sys.platform != "linux" or os.getpid() != 1:
        raise _GuardError("the internal shim must be PID one in its owned namespace")
    child: subprocess.Popen[bytes] | None = None

    def forward(signum: int, _frame: object) -> None:
        if child is None:
            # Exiting PID one also settles an interrupted preflight or fork.
            raise _Interrupted(signum)
        child.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, forward)
    try:
        # These bounded queries run inside the owned namespace too. No runtime
        # payload starts for an unqualified runtime or unshare implementation.
        _qualify(unshare, _UNSHARE_VERSION)
        _qualify(runtime, _RUNTIME_VERSION)
        child = subprocess.Popen([runtime, *arguments])  # noqa: S603 - selected trusted executable/argv.
        code = child.wait()
        return code if code >= 0 else 128 - code
    except _Interrupted as exc:
        return 128 + exc.signum


def main(argv: Sequence[str] | None = None) -> int:
    """Run foreground exec inside a user-owned namespace, or report this guard."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        # This identifies our own protocol, never impersonates Apptainer.
        # Actual component versions are checked inside the namespace at launch.
        print(VERSION)
        return 0
    try:
        if arguments and arguments[0] == "--namespace-init":
            if len(arguments) < 5 or arguments[3] != "exec":
                raise _GuardError("invalid internal namespace invocation")
            return _run_init(arguments[1], arguments[2], arguments[3:])
        if not arguments or arguments[0] != "exec":
            raise _GuardError("supported commands are --version and exec")
        if sys.platform != "linux":
            raise _GuardError("the namespace guard requires Linux")
        runtime = _executable("LOOM_APPTAINER_GUARD_RUNTIME", "apptainer")
        unshare = _executable("LOOM_APPTAINER_GUARD_UNSHARE", "unshare")
        os.execv(unshare, [
            unshare, "--user", "--map-current-user", "--keep-caps",
            "--mount-proc", "--pid", "--fork", "--kill-child=KILL",
            sys.executable, "-B", "-m", "loom._apptainer_guard",
            "--namespace-init", unshare, runtime, *arguments,
        ])
    except (OSError, _GuardError, subprocess.TimeoutExpired, ProcessOutputLimitError) as exc:
        print(f"loom-apptainer-guard: {exc}", file=sys.stderr)
        return 125
    raise AssertionError("exec unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
