"""Owner-only Unix-socket transport for the persistent local daemon."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import socket
import stat
import struct
from threading import Event, Thread
import time
from typing import cast

from loom.serialization import PlainData

from .errors import (
    QueueConflictError,
    QueueError,
    QueueServiceError,
    QueueStorageError,
    QueueValidationError,
)
from .local_daemon import (
    AgentControl,
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonStatus,
    RecoverUnknownAssignment,
)


_MAX_MESSAGE_BYTES = 1_048_576


class LocalDaemonSocketServer:
    """Serve the client view without trusting a request-supplied principal."""

    def __init__(self, daemon: LocalDaemon, endpoint: str | Path) -> None:
        self._daemon = daemon
        self.endpoint = Path(endpoint)
        self._socket: socket.socket | None = None
        self._endpoint_identity: tuple[int, int] | None = None
        self._stop = Event()
        self._thread: Thread | None = None

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
            with connection:
                self._handle(connection)

    def _handle(self, connection: socket.socket) -> None:
        try:
            uid = _peer_uid(connection)
            if uid != os.getuid():
                raise QueueServiceError("local daemon peer is not authorized")
            payload = _read_message(connection)
            operation = payload.get("operation")
            client = self._daemon.client_view(
                LocalDaemonPrincipal(f"uid:{uid}", LocalDaemonRole.CLIENT)
            )
            operator = self._daemon.operator_view(
                LocalDaemonPrincipal(f"uid:{uid}", LocalDaemonRole.OPERATOR)
            )
            if operation == "submit":
                request = payload.get("request")
                if not isinstance(request, Mapping):
                    raise QueueServiceError("submit request must be a mapping")
                result: PlainData = client.submit(
                    LocalDaemonAdmissionRequest.from_dict(request)
                ).to_dict()
            elif operation == "status":
                result = client.status().to_dict()
            elif operation == "cancel":
                queue_item_id = payload.get("queue_item_id")
                if not isinstance(queue_item_id, str) or not queue_item_id:
                    raise QueueServiceError("queue_item_id must be a non-empty string")
                result = client.cancel(queue_item_id).to_dict()
            elif operation == "agent_control":
                control = payload.get("control")
                if not isinstance(control, Mapping):
                    raise QueueServiceError("agent control must be a mapping")
                result = dict(operator.control_agent(AgentControl.from_value(control)))
            elif operation == "scheduling_reload":
                request = payload.get("request")
                if not isinstance(request, Mapping):
                    raise QueueServiceError(
                        "scheduling reload request must be a mapping"
                    )
                result = dict(
                    operator.reload_scheduling(
                        CoordinatorSchedulingReload.from_dict(request)
                    )
                )
            elif operation == "recover_unknown":
                request = payload.get("request")
                if not isinstance(request, Mapping):
                    raise QueueServiceError("recovery request must be a mapping")
                result = dict(operator.recover_unknown(RecoverUnknownAssignment.from_dict(request)))
            else:
                raise QueueServiceError("local daemon operation is unsupported")
            response: PlainData = {"ok": True, "result": result}
        except Exception as exc:  # Public responses expose only stable safe codes.
            diagnostic = _safe_error_code(exc)
            response = {
                "ok": False,
                "error": diagnostic,
                "message": diagnostic,
            }
        _write_message(connection, cast(Mapping[str, PlainData], response))


class LocalDaemonSocketClient:
    """Typed client using the same application operations as direct composition."""

    def __init__(self, endpoint: str | Path) -> None:
        self.endpoint = Path(endpoint)

    def submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        result = self._call({"operation": "submit", "request": request.to_dict()})
        return LocalDaemonAdmission.from_dict(result)

    def status(self) -> LocalDaemonStatus:
        return LocalDaemonStatus.from_dict(self._call({"operation": "status"}))

    def wait(
        self, queue_item_id: str, *, timeout_seconds: float | None = None
    ) -> LocalDaemonAdmission:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise QueueServiceError("timeout_seconds must be non-negative")
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        terminal = {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
            "BLOCKED",
        }
        while True:
            for admission in self.status().admissions:
                if admission.queue_item_id != queue_item_id:
                    continue
                if admission.state.value in terminal:
                    return admission
                break
            else:
                raise QueueServiceError("managed admission was not found")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "managed local admission did not reach terminal state"
                )
            time.sleep(0.05)

    def cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        result = self._call({"operation": "cancel", "queue_item_id": queue_item_id})
        return LocalDaemonAdmission.from_dict(result)

    def control_agent(self, control: AgentControl) -> Mapping[str, PlainData]:
        return cast(
            Mapping[str, PlainData],
            self._call({"operation": "agent_control", "control": control.value()}),
        )

    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Mapping[str, PlainData]:
        return cast(
            Mapping[str, PlainData],
            self._call(
                {"operation": "scheduling_reload", "request": request.to_dict()}
            ),
        )

    def recover_unknown(self, request: RecoverUnknownAssignment) -> Mapping[str, PlainData]:
        return cast(
            Mapping[str, PlainData],
            self._call({"operation": "recover_unknown", "request": request.to_dict()}),
        )

    def _call(self, request: Mapping[str, PlainData]) -> Mapping[str, object]:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(self.endpoint))
            _write_message(connection, request)
            response = _read_message(connection)
        except OSError as exc:
            raise QueueServiceError("local daemon endpoint is unavailable") from exc
        finally:
            connection.close()
        if response.get("ok") is not True:
            diagnostic = response.get("error")
            raise QueueServiceError(
                diagnostic
                if isinstance(diagnostic, str)
                else "local_daemon_request_failed"
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise QueueServiceError("local daemon returned an invalid result")
        return result


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, QueueConflictError):
        return "local_daemon_conflict"
    if isinstance(exc, QueueValidationError):
        return "local_daemon_invalid_request"
    if isinstance(exc, QueueServiceError):
        return "local_daemon_request_rejected"
    if isinstance(exc, (QueueStorageError, QueueError)):
        return "local_daemon_storage_unavailable"
    return "local_daemon_internal_error"


def _peer_uid(connection: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise QueueServiceError("local peer credentials are unavailable")
    raw = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
    )
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def _read_message(connection: socket.socket) -> Mapping[str, object]:
    chunks: list[bytes] = []
    length = 0
    while True:
        chunk = connection.recv(min(65_536, _MAX_MESSAGE_BYTES + 1 - length))
        if not chunk:
            break
        chunks.append(chunk)
        length += len(chunk)
        if length > _MAX_MESSAGE_BYTES:
            raise QueueServiceError("local daemon request is too large")
        if b"\n" in chunk:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QueueServiceError("local daemon request is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise QueueServiceError("local daemon request must be a mapping")
    return value


def _write_message(
    connection: socket.socket,
    value: Mapping[str, PlainData],
) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_MESSAGE_BYTES:
        raise QueueServiceError("local daemon response is too large")
    connection.sendall(payload + b"\n")


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


__all__ = ["LocalDaemonSocketClient", "LocalDaemonSocketServer"]
