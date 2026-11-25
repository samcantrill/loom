"""The tmux service's log reader follows rotation while its producer stays live."""

import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

import pytest


pytestmark = pytest.mark.integration


def test_service_stream_rotates_during_foreground_lifetime(tmp_path):
    log = tmp_path / "service.log"
    with log.open("wb") as stream:
        stream.truncate(16 * 1024**2 - 1)
    for number in (1, 2, 3):
        log.with_suffix(f".log.{number}").write_text(str(number))
    # Run the production entry point with a foreground CLI that writes through
    # both inherited OS descriptors and keep it live across rotation.
    code = """
import os
from loom.cli import main as cli
from loom.fleet._service_log import serve

def run(argv):
    os.write(1, b'first stdout\\n')
    if os.read(0, 1):
        os.write(2, b'final stderr\\n')
    os.read(0, 1)
    return 0

cli.main = run
raise SystemExit(serve())
"""

    def wait_until(predicate):
        end = monotonic() + 10
        while not predicate():
            assert monotonic() < end, "file descriptor owner did not rotate and write"
            sleep(0.01)

    with subprocess.Popen([sys.executable, "-c", code, str(log)], stdin=subprocess.PIPE) as service:
        assert service.stdin is not None
        try:
            wait_until(lambda: _ends_with(log, b"first stdout\n"))
            assert log.read_bytes() == b"first stdout\n"
            assert log.with_suffix(".log.1").stat().st_size == 16 * 1024**2 - 1
            assert log.with_suffix(".log.2").read_text() == "1"
            assert log.with_suffix(".log.3").read_text() == "2"
            os.write(service.stdin.fileno(), b"!")
            wait_until(lambda: _ends_with(log, b"final stderr\n"))
            assert service.poll() is None
            assert len(tuple(tmp_path.glob("service.log*"))) == 4
            assert all(path.stat().st_size <= 16 * 1024**2 for path in tmp_path.iterdir())
        finally:
            service.stdin.close()
            assert service.wait(timeout=10) == 0


def _ends_with(path: Path, value: bytes) -> bool:
    try:
        with path.open("rb") as stream:
            if stream.seek(0, 2) < len(value):
                return False
            stream.seek(-len(value), 2)
            return stream.read() == value
    except FileNotFoundError:
        return False
