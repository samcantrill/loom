"""Small runtime helpers shared by the maintained Stage 29 journeys."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from typing import TypeVar


_T = TypeVar("_T")


class JourneyRecorder:
    """Record a surface only after the corresponding product call succeeds."""

    def __init__(self) -> None:
        self.surfaces: set[str] = set()
        self.started_pids: set[int] = set()

    def python(self, name: str, call: Callable[[], _T]) -> _T:
        result = call()
        self.surfaces.add(f"python:{name}")
        return result

    def cli(self, *arguments: str) -> dict[str, object]:
        process = self._popen(arguments)
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            raise RuntimeError(
                f"Loom CLI failed ({process.returncode}): {' '.join(arguments)}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Loom CLI returned invalid JSON: {stdout}") from exc
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise RuntimeError(f"Loom CLI returned a failed envelope: {envelope}")
        self.surfaces.add(_cli_surface(arguments))
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Loom CLI result is not a mapping")
        return result

    def start_cli(self, *arguments: str) -> subprocess.Popen[str]:
        process = self._popen(arguments)
        self.surfaces.add(_cli_surface(arguments))
        return process

    def observe_process_tree(self, *roots: int) -> None:
        for root in roots:
            self.started_pids.add(root)
            self.started_pids.update(descendant_pids(root))

    def emit(self, **facts: object) -> None:
        payload = {
            "surfaces": sorted(self.surfaces),
            "started_pids": sorted(self.started_pids),
            **facts,
        }
        print("journey_result: " + json.dumps(payload, sort_keys=True))

    def _popen(self, arguments: Sequence[str]) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"
        loom_cli = Path(sys.executable).with_name("loom")
        if not loom_cli.is_file():
            raise RuntimeError(f"Loom CLI entry point is unavailable: {loom_cli}")
        process = subprocess.Popen(
            [str(loom_cli), *arguments, "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            start_new_session=True,
        )
        self.started_pids.add(process.pid)
        return process


def example_root(name: str) -> Path:
    configured = os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT")
    base = Path(configured) if configured else Path(tempfile.gettempdir()) / "loom-examples"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{name}-", dir=base)).resolve()


def write_protected(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until(
    predicate: Callable[[], _T | None], *, timeout: float = 10.0, interval: float = 0.05
) -> _T:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result is not None:
                return result
        except Exception as exc:  # a live service may not be ready yet
            last_error = exc
        time.sleep(interval)
    raise RuntimeError(f"journey did not become ready: {last_error}")


def stop_cli_service(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        os.kill(process.pid, signal.SIGINT)
    try:
        stdout, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        raise RuntimeError("Loom service did not stop through its supported path") from exc
    if process.returncode not in {0, 130, -signal.SIGINT}:
        raise RuntimeError(
            f"Loom service stopped unexpectedly ({process.returncode})\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return stdout, stderr


def descendant_pids(root: int) -> set[int]:
    found: set[int] = set()
    pending = [root]
    while pending:
        parent = pending.pop()
        children_path = Path(f"/proc/{parent}/task/{parent}/children")
        try:
            children = {
                int(value)
                for value in children_path.read_text(encoding="utf-8").split()
            }
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            children = set()
        new = children - found
        found.update(new)
        pending.extend(new)
    found.discard(root)
    return found


def assert_processes_dead(process_ids: Iterable[int], *, timeout: float = 5.0) -> None:
    pending = {pid for pid in process_ids if pid > 0 and pid != os.getpid()}
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        pending = {pid for pid in pending if _process_exists(pid)}
        if pending:
            time.sleep(0.05)
    if pending:
        raise RuntimeError(f"journey leaked processes: {sorted(pending)}")


def generate_mutual_tls(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    _openssl(
        root,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-subj",
        "/CN=loom-example-ca",
        "-days",
        "1",
    )
    for name, subject, extension in (
        ("server", "/CN=localhost", "subjectAltName=DNS:localhost"),
        ("agent", "/CN=agent", "extendedKeyUsage=clientAuth"),
    ):
        _openssl(
            root,
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
            "-subj",
            subject,
        )
        (root / f"{name}.ext").write_text(extension, encoding="utf-8")
        _openssl(
            root,
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            f"{name}.crt",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            f"{name}.ext",
        )
    return {name: root / name for name in ("ca", "server", "agent")}


def certificate_fingerprint(path: Path) -> str:
    return hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(path.read_text(encoding="utf-8"))
    ).hexdigest()


def _openssl(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments], cwd=root, check=True, capture_output=True, text=True
    )


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cli_surface(arguments: Sequence[str]) -> str:
    if len(arguments) < 2:
        raise RuntimeError("journey CLI call has no command")
    return f"cli:{arguments[0]} {arguments[1]}"


__all__ = [
    "JourneyRecorder",
    "assert_processes_dead",
    "available_port",
    "certificate_fingerprint",
    "descendant_pids",
    "example_root",
    "generate_mutual_tls",
    "stop_cli_service",
    "wait_until",
    "write_protected",
]
