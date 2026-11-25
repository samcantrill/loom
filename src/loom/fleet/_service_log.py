"""Size-limited combined stdout/stderr for a tmux-managed native service."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def serve() -> int:
    """Keep the native CLI in the tmux pane PID and pipe its output to one writer."""
    path = Path(sys.argv[1])
    with path.open("ab") as log:
        writer = subprocess.Popen(
            [sys.executable, "-m", "loom.fleet._service_log", str(path)],
            stdin=subprocess.PIPE, stdout=log, start_new_session=True,
        )
    assert writer.stdin is not None
    with writer.stdin as pipe:
        os.dup2(pipe.fileno(), 1)
        os.dup2(pipe.fileno(), 2)
    from loom.cli.main import main

    return main(sys.argv[2:])


def capture(path: Path, limit: int = 16 * 1024**2, backups: int = 3) -> None:
    """The pipe reader owns the log descriptor through every rotation."""
    size = os.fstat(1).st_size
    while chunk := sys.stdin.buffer.readline(limit):
        if size and size + len(chunk) > limit:
            for number in range(backups, 0, -1):
                previous = path if number == 1 else path.with_suffix(f".log.{number - 1}")
                if previous.exists():
                    previous.replace(path.with_suffix(f".log.{number}"))
            with path.open("ab") as fresh:
                os.dup2(fresh.fileno(), 1)
            size = 0
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        size += len(chunk)


if __name__ == "__main__":
    capture(Path(sys.argv[1]))
