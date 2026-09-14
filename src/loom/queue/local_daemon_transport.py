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

from ._coordinator_client import NativeCoordinatorClient
from ._coordinator_control import (
    CONTROL_CAPABILITY, CONTROL_OPERATIONS, WAIT_OPERATIONS, CoordinatorClientError,
    control_error, dispatch_control, encode_wire,
)
from ._coordinator_transport import UnixControlTransport, read_unix_message
from .errors import (
    QueueConflictError,
    QueueError,
    QueueServiceError,
    QueueStorageError,
    QueueValidationError,
)
from .local_daemon import (
    AdmissionNotFoundError,
    AgentControl,
    AgentPage,
    AgentProjection,
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    AdmissionPage,
    AdmissionWaitResult,
    DaemonStatus,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonOperation,
    OperationWaitResult,
    RecoverUnknownAssignment,
    SessionReplacementRequest,
    TimeRecoveryReceipt,
    TimeRecoveryRequest,
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
            except Exception as exc:
                try:
                    _write_error(connection, _safe_error_code(exc))
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
            if daemon_control not in (None, CONTROL_CAPABILITY):
                raise QueueValidationError("local daemon client protocol is invalid")
            if operation in WAIT_OPERATIONS:
                if not self._long_poll_slots.acquire(blocking=False):
                    raise _WaitCapacityError("local daemon wait capacity is exhausted")
                long_poll_acquired = True
            operator = self._daemon.operator_view(
                LocalDaemonPrincipal(f"uid:{uid}", LocalDaemonRole.OPERATOR)
            )
            result: PlainData
            if operation in CONTROL_OPERATIONS or daemon_control == CONTROL_CAPABILITY:
                result = dict(dispatch_control(
                    self._daemon, LocalDaemonPrincipal(f"uid:{uid}", LocalDaemonRole.CLIENT),
                    operation, payload, transport="unix", wait_slice=_SERVER_WAIT_SECONDS,
                    inspect_run=self._inspect_run, legacy=daemon_control is None,
                ))
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
                result = dict(
                    operator.recover_unknown(
                        RecoverUnknownAssignment.from_dict(request)
                    )
                )
            elif operation == "recover_time":
                request = payload.get("request")
                if not isinstance(request, Mapping):
                    raise QueueServiceError("time recovery request must be a mapping")
                result = operator.recover_time(
                    TimeRecoveryRequest.from_dict(request)
                ).to_dict()
            elif operation == "replace_agent_session":
                request = payload.get("request")
                if not isinstance(request, Mapping):
                    raise QueueServiceError(
                        "session replacement request must be a mapping"
                    )
                result = dict(
                    operator.replace_agent_session(
                        SessionReplacementRequest.from_dict(request)
                    )
                )
            else:
                raise QueueServiceError("local daemon operation is unsupported")
            response: PlainData = {"ok": True, "result": result}
        except Exception as exc:  # Public responses retain stable safe legacy codes.
            diagnostic = _safe_error_code(exc)
            response = {"ok": False, "error": diagnostic, "message": diagnostic}
            if daemon_control == CONTROL_CAPABILITY:
                if isinstance(exc, CoordinatorClientError):
                    detail = exc
                else:
                    code = "capacity_exhausted" if isinstance(exc, _WaitCapacityError) else "invalid_request"
                    detail = control_error(code, operation, payload, boundary="coordinator")
                response["error_detail"] = detail.to_dict()
        try:
            connection.settimeout(30.0)
            _write_message(connection, cast(Mapping[str, PlainData], response))
        finally:
            connection.close()
            self._worker_slots.release()
            if long_poll_acquired:
                self._long_poll_slots.release()


class LocalDaemonSocketClient:
    """Compatibility adapter for established socket signatures and error classes."""

    def __init__(self, endpoint: str | Path, *, expected_coordinator_id: str | None = None) -> None:
        self.endpoint = Path(endpoint)
        self._client = NativeCoordinatorClient(
            UnixControlTransport(endpoint), expected_coordinator_id=expected_coordinator_id, legacy=True,
        )

    def submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        return self._client.submit(request)

    def status(self) -> DaemonStatus:
        return self._client.status()

    def admissions(self, *, limit: int = 100, cursor: str | None = None) -> AdmissionPage:
        return self._client.admissions(limit=limit, cursor=cursor)

    def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
        return self._client.admission(admission_id)

    def admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        return self._client.admission_for_queue_item(queue_item_id)

    def agents(self, *, limit: int = 100, cursor: str | None = None) -> AgentPage:
        return self._client.agents(limit=limit, cursor=cursor)

    def agent(self, agent_id: str) -> AgentProjection:
        return self._client.agent(agent_id)

    def operation(self, operation_id: str) -> LocalDaemonOperation:
        return self._client.operation(operation_id)

    def wait_operation(self, operation_id: str, *, timeout_seconds: float | None = None) -> OperationWaitResult:
        return cast(OperationWaitResult, self._client._wait_native(
            "wait_operation", {"operation_id": operation_id}, timeout_seconds, None, legacy=True,
        ))

    def wait_admission(self, admission_id: str, *, expected_revision: int, timeout: float | None = None) -> AdmissionWaitResult:
        return cast(AdmissionWaitResult, self._client._wait_native(
            "wait_admission", {"admission_id": admission_id, "expected_revision": expected_revision},
            timeout, None, legacy=True,
        ))

    def wait(self, queue_item_id: str, *, timeout_seconds: float | None = None) -> LocalDaemonAdmission:
        return self._client.wait(queue_item_id, timeout_seconds=timeout_seconds)

    def cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        return self._client.cancel(queue_item_id)

    def inspect_run(self, run_uri: str) -> Mapping[str, object]:
        """Retain the established unrestricted injected inspection entrypoint."""
        return cast(Mapping[str, object], self._client._native_call("inspect_run", {"run_uri": run_uri}))

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

    def recover_unknown(
        self, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        return cast(
            Mapping[str, PlainData],
            self._call({"operation": "recover_unknown", "request": request.to_dict()}),
        )

    def recover_time(self, request: TimeRecoveryRequest) -> TimeRecoveryReceipt:
        return TimeRecoveryReceipt.from_dict(
            self._call({"operation": "recover_time", "request": request.to_dict()})
        )

    def replace_agent_session(
        self, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        return cast(
            Mapping[str, PlainData],
            self._call(
                {"operation": "replace_agent_session", "request": request.to_dict()}
            ),
        )

    def _call(self, request: Mapping[str, PlainData]) -> Mapping[str, object]:
        # Operator operations retain their separate owner and legacy wire shape.
        operation = cast(str, request["operation"])
        payload = dict(request)
        payload.pop("operation")
        if self._client._expected_coordinator_id is not None:
            payload["expected_coordinator_id"] = self._client._expected_coordinator_id
        return self._client._exchange(operation, payload, time.monotonic() + 30.0, waiting=False)


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, CoordinatorClientError):
        return {
            "not_found": "local_daemon_admission_not_found",
            "conflict": "local_daemon_conflict",
            "invalid_request": "local_daemon_invalid_request",
        }.get(exc.code, "local_daemon_request_rejected")
    if isinstance(exc, AdmissionNotFoundError):
        return "local_daemon_admission_not_found"
    if isinstance(exc, QueueConflictError):
        return "local_daemon_conflict"
    if isinstance(exc, QueueValidationError):
        return "local_daemon_invalid_request"
    if isinstance(exc, _WaitCapacityError):
        return "local_daemon_wait_capacity_exhausted"
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


__all__ = ["LocalDaemonSocketClient", "LocalDaemonSocketServer"]
