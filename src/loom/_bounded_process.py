"""Bounded communication with one owned POSIX subprocess group."""

from __future__ import annotations

import codecs
from collections.abc import Mapping, Sequence
import io
import os
import selectors
import signal
import subprocess
from time import monotonic
from typing import Literal, cast, overload


class ProcessOutputLimitError(RuntimeError):
    """The complete response exceeded a caller's per-stream capture limit."""


@overload
def run_bounded_process(
    argv: Sequence[str], *, timeout: float, environment: Mapping[str, str] | None,
    output_limit: int, text: Literal[True], input: bytes | None = None,
    executable: str | None = None,
    start_new_session: bool = True,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_bounded_process(
    argv: Sequence[str], *, timeout: float, environment: Mapping[str, str] | None,
    output_limit: int, text: Literal[False] = False, input: bytes | None = None,
    executable: str | None = None,
    start_new_session: bool = True,
) -> subprocess.CompletedProcess[bytes]: ...


def run_bounded_process(
    argv, *, timeout, environment, output_limit, text=False, input=None, executable=None,
    start_new_session=True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Capture each stream in bytes, or decoded characters with text=True.

    Input and output progress concurrently under one monotonic deadline. On
    timeout, overflow or another communication failure, kill the owned process
    group and reap its leader. Kernel-uninterruptible IO cannot be time bounded.
    Descendants that deliberately create another session are outside this group.
    With start_new_session=False, the caller owns group cleanup: this function
    kills/reaps only its direct child on failure. This supports a disposable
    helper whose outer owner must also be able to kill its nested commands.
    """
    if os.name != "posix":
        raise OSError("bounded processes require POSIX process groups")
    deadline = monotonic() + timeout
    with subprocess.Popen(
        list(argv), executable=executable,
        stdin=None if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text,
        env=None if environment is None else dict(environment), start_new_session=start_new_session,
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        pipes = (process.stdout, process.stderr)
        output = ([], [])
        lengths = [0, 0]
        decoders = tuple(
            io.IncrementalNewlineDecoder(
                codecs.getincrementaldecoder(cast(io.TextIOWrapper, pipe).encoding)(), translate=True,
            ) for pipe in pipes
        ) if text else None
        offset = 0
        try:
            with selectors.DefaultSelector() as selector:
                for index, pipe in enumerate(pipes):
                    selector.register(pipe, selectors.EVENT_READ, index)
                if process.stdin is not None:
                    if input:
                        os.set_blocking(process.stdin.fileno(), False)
                        selector.register(process.stdin, selectors.EVENT_WRITE, "input")
                    else:
                        process.stdin.close()
                while selector.get_map():
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(list(argv), timeout)
                    for key, _events in selector.select(remaining):
                        if key.data == "input":
                            assert input is not None and process.stdin is not None
                            try:
                                offset += os.write(key.fd, input[offset:offset + 4096])
                            except BlockingIOError:
                                continue
                            except BrokenPipeError:
                                offset = len(input)
                            if offset == len(input):
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                            continue
                        index = key.data
                        chunk = os.read(key.fd, 4096)
                        value = decoders[index].decode(chunk, final=not chunk) if decoders else chunk
                        lengths[index] += len(value)
                        if lengths[index] > output_limit:
                            raise ProcessOutputLimitError("bounded process output exceeds the evidence limit")
                        output[index].append(value)
                        if not chunk:
                            selector.unregister(key.fileobj)
                returncode = process.wait(timeout=max(0.0, deadline - monotonic()))
        except BaseException:
            try:
                if start_new_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            for pipe in (*pipes, process.stdin):
                if pipe is not None:
                    pipe.close()
            process.wait()
            raise
        if text:
            return subprocess.CompletedProcess(
                list(argv), returncode,
                "".join(cast(list[str], output[0])), "".join(cast(list[str], output[1])),
            )
        return subprocess.CompletedProcess(
            list(argv), returncode,
            b"".join(cast(list[bytes], output[0])), b"".join(cast(list[bytes], output[1])),
        )
