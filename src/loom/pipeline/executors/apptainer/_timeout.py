"""Bounded observation of the supported foreground runtime's PID namespace.

The caller owns the launcher; Linux namespace-init teardown is the descendant
barrier. No process group is created or signaled here: an enclosing queue owner
must retain its original cancellation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
from time import monotonic, sleep
from typing import BinaryIO, Sequence

from .build import MAX_APPTAINER_OUTPUT_CHARS, ApptainerOptionError


class UnsupportedTimeoutError(ApptainerOptionError):
    """The configured command cannot enter the evidenced timeout boundary."""


@dataclass(frozen=True)
class TimedExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    error: str | None


def namespace_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Select the init shim without changing caller or enclosing group ownership."""
    if len(argv) < 3 or argv[1] != "exec":
        raise UnsupportedTimeoutError("timeout supervision requires foreground exec")
    flags = {"--cleanenv", "--nv", "--rocm", "--fakeroot", "--no-home", "--pid"}
    values = {"--cpus", "--memory", "--pwd", "--bind", "--env"}
    index = 2
    options: list[str] = []
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        if option in flags or option == "--no-init=false":
            if option not in {"--pid", "--no-init=false"}:
                options.append(option)
            index += 1
        elif option in values and index + 1 < len(argv):
            options.extend(argv[index : index + 2])
            index += 2
        else:
            raise UnsupportedTimeoutError(
                "timeout supervision requires the supported foreground exec options; "
                "use build_apptainer_exec_command without instance/join/no-init options"
            )
    if index >= len(argv) - 1 or argv[index].startswith("instance://"):
        raise UnsupportedTimeoutError(
            "timeout supervision requires an image and worker, not an existing instance"
        )
    return (argv[0], "exec", "--pid", "--no-init=false", *options, *argv[index:])


def _require_runtime(command: str, deadline: float) -> None:
    if (
        sys.platform != "linux"
        or not all(hasattr(os, name) for name in ("pidfd_open", "waitid", "WNOWAIT"))
        or not hasattr(signal, "pidfd_send_signal")
    ):
        raise UnsupportedTimeoutError(
            "container timeouts require Linux pidfds and non-reaping child waits; "
            "use a supported execution host or explicitly disable the timeout"
        )
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, 0)
    version = subprocess.run(  # noqa: S603 - trusted configured runtime, no payload.
        [command, "--version"],
        capture_output=True,
        text=True,
        timeout=remaining,
        check=False,
    )
    if (
        version.returncode != 0
        or re.fullmatch(
            r"singularity(?:-ce)? version 3\.10\.4(?:-focal)?\s*", version.stdout
        )
        is None
    ):
        raise UnsupportedTimeoutError(
            "container timeout cleanup is currently verified for SingularityCE 3.10.4 "
            "foreground exec with its PID-namespace init; select that runtime or "
            "explicitly disable the timeout"
        )


def _ready(fd: int) -> bool:
    return bool(select.select([fd], [], [], 0)[0])


def _root_status(process: subprocess.Popen[bytes]) -> int | None:
    status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    if status is None:
        return None
    return status.si_status if status.si_code == os.CLD_EXITED else -status.si_status


def _capture_init(process: subprocess.Popen[bytes], group: int) -> int | None:
    # The unreaped creation-owned root cannot be replaced while reading its
    # live child lineage. Check the opened pidfd after reading process facts so
    # a candidate exit/reuse race cannot turn a different PID into our init.
    for children in Path(f"/proc/{process.pid}/task").glob("*/children"):
        try:
            candidates = children.read_text().split()
        except FileNotFoundError:
            continue
        for value in candidates:
            fd: int | None = None
            accepted = False
            try:
                pid = int(value)
                fd = os.pidfd_open(pid)
                status = {
                    key: value.strip()
                    for key, value in (
                        line.split(":", 1)
                        for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                    )
                }
                namespace_pids = status.get("NSpid", "").split()
                accepted = (
                    status.get("PPid") == str(process.pid)
                    and status.get("Name") == "sinit"
                    and len(namespace_pids) > 1
                    and namespace_pids[-1] == "1"
                    and os.getpgid(pid) == group
                    and not _ready(fd)
                )
                if accepted:
                    try:
                        _root_status(process)
                    except BaseException:
                        accepted = False
                        raise
                    return fd
            except (ProcessLookupError, FileNotFoundError):
                continue
            finally:
                if fd is not None and not accepted:
                    os.close(fd)
    return None


def _settle(process: subprocess.Popen[bytes], init: int | None) -> list[str]:
    errors: list[str] = []
    anchored = True

    def status() -> int | None:
        nonlocal anchored
        try:
            return _root_status(process)
        except ChildProcessError:
            anchored = False
            if "launcher ownership lost" not in errors:
                errors.append("launcher ownership lost")
            return None

    def complete() -> bool:
        return status() is not None and init is not None and _ready(init)

    if not complete():
        for signum in (signal.SIGTERM, signal.SIGKILL):
            status()
            if anchored:
                try:
                    os.kill(process.pid, signum)
                except ProcessLookupError:
                    anchored = False
                    errors.append("launcher ownership lost during cleanup")
                except OSError as exc:
                    errors.append(f"launcher cleanup: {type(exc).__name__}")
            if init is not None and not _ready(init):
                try:
                    signal.pidfd_send_signal(init, signum)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    errors.append(f"namespace cleanup: {type(exc).__name__}")
            deadline = monotonic() + 2
            while not complete() and monotonic() < deadline:
                if init is None and status() is not None:
                    break
                sleep(0.01)
            if complete():
                break
    if anchored and status() is not None:
        process.wait(timeout=0)
    else:
        errors.append("launcher exit/reaping unresolved")
    if init is None:
        errors.append("namespace init identity unavailable; cleanup unresolved")
    elif not _ready(init):
        errors.append("namespace termination unresolved")
    return errors


def _output(stream: BinaryIO) -> str:
    stream.seek(0)
    # Command results already expose at most this many text characters.
    return stream.read(MAX_APPTAINER_OUTPUT_CHARS * 4 + 1).decode(errors="replace")


def run_timed_exec(argv: Sequence[str], timeout_seconds: float) -> TimedExecResult:
    """Run within one deadline, then use a separate bounded cleanup budget."""
    deadline = monotonic() + timeout_seconds
    _require_runtime(argv[0], deadline)
    init: int | None = None
    timed_out = False
    error: str | None = None
    interrupted: BaseException | None = None
    root_code: int | None = None
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(  # noqa: S603 - trusted configured exec argv.
            list(argv),
            stdout=stdout,
            stderr=stderr,
        )
        try:
            _root_status(process)
            group = os.getpgid(process.pid)
            while True:
                if init is None:
                    init = _capture_init(process, group)
                root_code = _root_status(process)
                if monotonic() >= deadline:
                    timed_out = True
                    break
                if root_code is not None:
                    break
                sleep(0.005)
        except BaseException as exc:
            if isinstance(exc, Exception):
                error = f"namespace observation failed: {type(exc).__name__}"
            else:
                interrupted = exc
        finally:
            try:
                try:
                    cleanup = _settle(process, init)
                except BaseException as exc:
                    cleanup = [
                        f"cleanup failed: {type(exc).__name__}; settlement unresolved"
                    ]
                    if (
                        not isinstance(exc, Exception)
                        and interrupted is None
                        and not timed_out
                    ):
                        interrupted = exc
            finally:
                if init is not None:
                    os.close(init)
        if interrupted is not None:
            if cleanup:
                interrupted.add_note("container cleanup: " + "; ".join(cleanup))
            raise interrupted
        if cleanup:
            error = "; ".join(filter(None, (error, *cleanup)))
        if timed_out:
            error = "; ".join(
                filter(None, ("container execution deadline exceeded", error))
            )
        return TimedExecResult(
            returncode=124
            if timed_out
            else 127
            if error
            else (root_code if root_code is not None else 127),
            stdout=_output(stdout),
            stderr=_output(stderr),
            timed_out=timed_out,
            error=error,
        )
