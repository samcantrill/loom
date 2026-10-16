"""Owner-only Unix-socket transport for the persistent local daemon."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import stat
import struct
from threading import BoundedSemaphore, Event, Thread
import time
from typing import cast

from loom.serialization import PlainData

from ._coordinator_control import (
    CONTROL_CAPABILITY, WAIT_OPERATIONS, CoordinatorClientError,
    control_error, dispatch_control, encode_wire, error_envelope, OPERATOR_OPERATIONS,
)
from ._coordinator_transport import read_unix_message
from .errors import (
    QueueServiceError,
)
from .local_daemon import (
    LocalDaemon,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)


_MAX_MESSAGE_BYTES = 1_048_576
_WORKER_COUNT = 8
_LONG_POLL_WORKER_COUNT = _WORKER_COUNT - 1
_SERVER_WAIT_SECONDS = 0.5


class _WaitCapacityError(QueueServiceError):
    """A retryable local transport admission response."""


class LocalDaemonSocketServer:
    """Serve the client view without trusting a request-supplied principal."""

    def __init__(
        self,
        daemon: LocalDaemon,
        endpoint: str | Path,
        *,
        inspect_run: Callable[[str], Mapping[str, PlainData]] | None = None,
    ) -> None:
        self._daemon = daemon
        self._inspect_run = inspect_run
        self.endpoint = Path(endpoint)
        self._socket: socket.socket | None = None
        self._endpoint_identity: tuple[int, int] | None = None
        self._stop = Event()
        self._thread: Thread | None = None
        self._workers: ThreadPoolExecutor | None = None
        self._worker_slots = BoundedSemaphore(_WORKER_COUNT)
        self._long_poll_slots = BoundedSemaphore(_LONG_POLL_WORKER_COUNT)

    def start(self) -> None:
        if self._socket is not None:
            raise QueueServiceError("local daemon socket server is already started")
        _validate_endpoint_parent(self.endpoint)
        _remove_owned_stale_socket(self.endpoint)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.endpoint))
            self.endpoint.chmod(0o600)
            identity = self.endpoint.stat()
            listener.listen()
            listener.settimeout(0.2)
        except Exception:
            listener.close()
            raise
        self._socket = listener
        self._endpoint_identity = (identity.st_dev, identity.st_ino)
        self._stop.clear()
        self._workers = ThreadPoolExecutor(
            max_workers=_WORKER_COUNT, thread_name_prefix="loom-local-daemon-request"
        )
        self._thread = Thread(
            target=self._serve,
            name="loom-local-daemon-socket",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        listener = self._socket
        self._socket = None
        if listener is not None:
            listener.close()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        workers = self._workers
        self._workers = None
        if workers is not None:
            workers.shutdown(wait=True, cancel_futures=True)
        _unlink_exact_socket(self.endpoint, self._endpoint_identity)
        self._endpoint_identity = None

    def _serve(self) -> None:
        listener = self._socket
        assert listener is not None
        while not self._stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            try:
                if not self._worker_slots.acquire(blocking=False):
                    connection.settimeout(0.5)
                    _write_error(connection, "local_daemon_worker_capacity_exhausted")
                    connection.close()
                    continue
                workers = self._workers
                if workers is None:
                    self._worker_slots.release()
                    raise QueueServiceError("local daemon socket server is stopping")
                workers.submit(self._handle, connection)
            except Exception:
                try:
                    _write_error(connection, "local_daemon_internal_error")
                finally:
                    connection.close()

    def _handle(self, connection: socket.socket) -> None:
        long_poll_acquired = False
        payload: dict[str, object] = {}
        operation = "unknown"
        daemon_control: object = None
        try:
            uid = _peer_uid(connection)
            payload = dict(read_unix_message(connection, deadline=time.monotonic() + 30.0))
            operation_value = payload.pop("operation", None)
            operation = operation_value if isinstance(operation_value, str) else "unknown"
            daemon_control = payload.pop("daemon_control", None)
            if uid != os.getuid():
                raise control_error("unauthorized", operation, payload, boundary="authentication")
            if daemon_control != CONTROL_CAPABILITY:
                raise control_error("unsupported", operation, payload, boundary="client_protocol")
            if operation in WAIT_OPERATIONS:
                if not self._long_poll_slots.acquire(blocking=False):
                    raise _WaitCapacityError("local daemon wait capacity is exhausted")
                long_poll_acquired = True
            result = dict(dispatch_control(
                self._daemon,
                LocalDaemonPrincipal(f"uid:{uid}", LocalDaemonRole.OPERATOR if operation in OPERATOR_OPERATIONS else LocalDaemonRole.CLIENT),
                operation, payload, transport="unix", wait_slice=_SERVER_WAIT_SECONDS,
                inspect_run=self._inspect_run,
            ))
            response: PlainData = {"ok": True, "result": result}
        except Exception as exc:
            if isinstance(exc, CoordinatorClientError):
                detail = exc
            else:
                code = "capacity_exhausted" if isinstance(exc, _WaitCapacityError) else "invalid_request"
                detail = control_error(code, operation, payload, boundary="coordinator")
            response = error_envelope(detail)
        try:
            connection.settimeout(30.0)
            _write_message(connection, cast(Mapping[str, PlainData], response))
        finally:
            connection.close()
            self._worker_slots.release()
            if long_poll_acquired:
                self._long_poll_slots.release()


def _peer_uid(connection: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise QueueServiceError("local peer credentials are unavailable")
    raw = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
    )
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def _write_message(
    connection: socket.socket,
    value: Mapping[str, PlainData],
) -> None:
    payload = encode_wire(value)
    if len(payload) > _MAX_MESSAGE_BYTES:
        raise QueueServiceError("local daemon response is too large")
    connection.sendall(payload + b"\n")


def _write_error(connection: socket.socket, diagnostic: str) -> None:
    _write_message(
        connection,
        {"ok": False, "error": diagnostic, "message": diagnostic},
    )


def _validate_endpoint_parent(endpoint: Path) -> None:
    parent = endpoint.parent
    if not parent.is_dir():
        raise QueueServiceError("local daemon endpoint parent is missing")
    parent_stat = parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise QueueServiceError("local daemon endpoint parent must be owner-private")


def _remove_owned_stale_socket(endpoint: Path) -> None:
    if not endpoint.exists():
        return
    endpoint_stat = endpoint.lstat()
    if endpoint_stat.st_uid != os.getuid() or not stat.S_ISSOCK(endpoint_stat.st_mode):
        raise QueueServiceError(
            "local daemon endpoint exists and is not an owned socket"
        )
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(endpoint))
    except OSError:
        endpoint.unlink()
    else:
        raise QueueServiceError("local daemon endpoint is already active")
    finally:
        probe.close()


def _unlink_exact_socket(
    endpoint: Path,
    identity: tuple[int, int] | None,
) -> None:
    if identity is None or not endpoint.exists():
        return
    endpoint_stat = endpoint.lstat()
    if (
        stat.S_ISSOCK(endpoint_stat.st_mode)
        and (endpoint_stat.st_dev, endpoint_stat.st_ino) == identity
    ):
        endpoint.unlink()


__all__ = ["LocalDaemonSocketServer"]
