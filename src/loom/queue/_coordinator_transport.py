"""Bounded native control I/O, independent of worker journals and scheduling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import http.client
from pathlib import Path
import socket
import ssl
from threading import BoundedSemaphore, Event, Lock, Thread
import time
from typing import Iterator
from urllib.parse import urlsplit

from loom.serialization import PlainData

from ._coordinator_control import (
    CONTROL_CAPABILITY,
    MAX_RESPONSE_BYTES,
    CoordinatorClientError,
    decode_envelope,
    decode_result,
    control_error,
    decode_wire,
    encode_wire,
)


REQUEST_BUDGET_SECONDS = 30.0
HTTP_CALL_SECONDS = 10.0
CLIENT_CAPACITY = 8
CLIENT_WAIT_CAPACITY = 6


class _ResponseTooLarge(ValueError):
    """The transport received more than the native response byte limit."""


def remaining(deadline: float) -> float:
    duration = deadline - time.monotonic()
    if duration <= 0:
        raise TimeoutError("coordinator request deadline exceeded")
    return duration


class ControlCapacity:
    """Bound concurrent work while retaining ordinary-call capacity."""

    def __init__(
        self, total: int = CLIENT_CAPACITY, waits: int = CLIENT_WAIT_CAPACITY
    ) -> None:
        self._requests = BoundedSemaphore(total)
        self._waits = BoundedSemaphore(waits)

    @contextmanager
    def acquire(self, *, waiting: bool, deadline: float) -> Iterator[None]:
        wait_acquired = request_acquired = False
        try:
            if waiting:
                wait_acquired = self._waits.acquire(
                    timeout=max(0.0, deadline - time.monotonic())
                )
                if not wait_acquired:
                    raise TimeoutError("coordinator wait capacity deadline exceeded")
            request_acquired = self._requests.acquire(
                timeout=max(0.0, deadline - time.monotonic())
            )
            if not request_acquired:
                raise TimeoutError("coordinator request capacity deadline exceeded")
            yield
        finally:
            if request_acquired:
                self._requests.release()
            if wait_acquired:
                self._waits.release()


class _Exchange:
    """One I/O attempt; its commitment evidence outlives a waiting caller."""

    def __init__(
        self, operation: str, payload: Mapping[str, PlainData], deadline: float
    ) -> None:
        self.operation = operation
        self.payload = payload
        self.deadline = deadline
        self.sent = False
        self.cancelled = Event()
        self.completed = Event()
        self.lock = Lock()
        self.socket: socket.socket | None = None
        self.result: Mapping[str, object] | None = None
        self.error: BaseException | None = None

    def attach(self, connection: socket.socket) -> None:
        with self.lock:
            if self.cancelled.is_set() or time.monotonic() >= self.deadline:
                connection.close()
                raise TimeoutError("coordinator request deadline exceeded")
            self.socket = connection
            connection.settimeout(remaining(self.deadline))

    def before_send(self) -> None:
        with self.lock:
            if self.cancelled.is_set():
                raise TimeoutError("coordinator request deadline exceeded")
            if self.socket is not None:
                self.socket.settimeout(remaining(self.deadline))
            self.sent = True

    def expire(self) -> None:
        with self.lock:
            self.cancelled.set()
            connection = self.socket
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def failure(
        self, code: str, *, boundary: str = "connection"
    ) -> CoordinatorClientError:
        with self.lock:
            return control_error(
                code,
                self.operation,
                self.payload,
                boundary=boundary,
                dispatched=self.sent,
            )


def https_connection(
    url: str,
    server_ca_path: str | Path,
    certificate_path: str | Path,
    private_key_path: str | Path,
    *,
    timeout: float,
) -> http.client.HTTPSConnection:
    """Build the common CA/name-verified, client-authenticated HTTPS connection."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("coordinator HTTPS endpoint is invalid")
    context = ssl.create_default_context(cafile=server_ca_path)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate_path, private_key_path)
    return http.client.HTTPSConnection(
        parsed.hostname, parsed.port or 443, context=context, timeout=timeout
    )


class ControlTransport:
    """Finite I/O calls with bounded detached work even during DNS/TLS stalls.

    Socket deadlines are refreshed from one absolute budget. The waiting caller
    is also bounded when an OS resolver or TLS setup stalls before a socket can
    be interrupted. Such work retains its bounded slot, cannot send after expiry,
    and does not keep the client process alive.
    """

    kind: str

    def __init__(self) -> None:
        self._capacity = ControlCapacity()
        self._active: set[_Exchange] = set()
        self._lock = Lock()
        self._closed = False

    def _exchange(self, exchange: _Exchange) -> Mapping[str, object]:
        raise NotImplementedError

    def _exchange_for(self, operation: str):
        return self._exchange

    def call(
        self,
        operation: str,
        payload: Mapping[str, PlainData],
        deadline: float,
        *,
        waiting: bool = False,
    ) -> Mapping[str, object]:
        # Admission belongs to the same budget; a stalled exchange retains its
        # slot after the caller returns instead of growing an unbounded queue.
        context = self._capacity.acquire(waiting=waiting, deadline=deadline)
        try:
            context.__enter__()
        except TimeoutError as exc:
            raise control_error(
                "capacity_exhausted", operation, payload, boundary="connection"
            ) from exc
        exchange_deadline = (
            min(deadline, time.monotonic() + HTTP_CALL_SECONDS)
            if self.kind == "https"
            else deadline
        )
        exchange = _Exchange(operation, payload, exchange_deadline)
        with self._lock:
            if self._closed:
                context.__exit__(None, None, None)
                raise control_error(
                    "unavailable", operation, payload, boundary="connection"
                )
            self._active.add(exchange)

        perform_exchange = self._exchange_for(operation)

        def execute() -> None:
            try:
                remaining(exchange.deadline)
                exchange.result = perform_exchange(exchange)
            except BaseException as exc:
                exchange.error = exc
            finally:
                context.__exit__(None, None, None)
                with self._lock:
                    self._active.discard(exchange)
                exchange.completed.set()

        worker = Thread(target=execute, name="loom-coordinator-io", daemon=True)
        worker.start()
        if not exchange.completed.wait(max(0.0, exchange.deadline - time.monotonic())):
            exchange.expire()
            raise exchange.failure("deadline_exceeded")
        error = exchange.error
        if error is not None:
            if isinstance(error, CoordinatorClientError):
                raise error
            if isinstance(error, (TimeoutError, socket.timeout)):
                raise exchange.failure("deadline_exceeded") from error
            if isinstance(error, ssl.SSLError) and not exchange.sent:
                raise exchange.failure(
                    "unauthorized", boundary="authentication"
                ) from error
            if isinstance(error, (OSError, http.client.HTTPException)):
                raise exchange.failure("unavailable") from error
            if isinstance(error, _ResponseTooLarge):
                raise exchange.failure(
                    "result_too_large", boundary="client_protocol"
                ) from error
            if isinstance(error, (ValueError, TypeError, RecursionError, UnicodeError)):
                raise exchange.failure(
                    "invalid_response", boundary="client_protocol"
                ) from error
            raise exchange.failure(
                "internal_error", boundary="client_protocol"
            ) from error
        if exchange.result is None:
            raise exchange.failure("invalid_response", boundary="client_protocol")
        return exchange.result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            exchanges = tuple(self._active)
        for exchange in exchanges:
            exchange.expire()


class UnixControlTransport(ControlTransport):
    kind = "unix"

    def __init__(self, endpoint: str | Path) -> None:
        super().__init__()
        self.endpoint = Path(endpoint)

    def _exchange(self, exchange: _Exchange) -> Mapping[str, object]:
        envelope: dict[str, PlainData] = {
            "operation": exchange.operation,
            **exchange.payload,
        }
        envelope["daemon_control"] = CONTROL_CAPABILITY
        raw = encode_wire(envelope)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise exchange.failure("invalid_request", boundary="client_protocol")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            exchange.attach(connection)
            connection.connect(str(self.endpoint))
            exchange.before_send()
            connection.sendall(raw + b"\n")
            return read_unix_message(connection, deadline=exchange.deadline)
        finally:
            connection.close()


def read_unix_message(
    connection: socket.socket, *, deadline: float | None = None
) -> Mapping[str, object]:
    chunks: list[bytes] = []
    size = 0
    while True:
        if deadline is not None:
            connection.settimeout(remaining(deadline))
        chunk = connection.recv(min(65_536, MAX_RESPONSE_BYTES + 1 - size))
        if not chunk:
            break
        content, separator, _tail = chunk.partition(b"\n")
        chunks.append(content)
        size += len(content)
        if size > MAX_RESPONSE_BYTES:
            raise _ResponseTooLarge("control response is too large")
        if separator:
            break
    return decode_wire(b"".join(chunks))


class HttpsControlTransport(ControlTransport):
    kind = "https"

    def __init__(
        self,
        url: str,
        server_ca_path: Path,
        certificate_path: Path,
        private_key_path: Path,
        *, role: str = "client",
    ) -> None:
        super().__init__()
        self._role = role
        self._credentials = (server_ca_path, certificate_path, private_key_path)
        self._range_session: ContextVar[_RangeConnections | None] = ContextVar("artifact_reads", default=None)
        self._range_owners: set[_RangeConnections] = set()
        self._connection: Callable[[float], http.client.HTTPSConnection] = (
            lambda timeout: https_connection(
                url,
                server_ca_path,
                certificate_path,
                private_key_path,
                timeout=timeout,
            )
        )

    @property
    def negotiating_ranges(self) -> bool:
        return self._range_session.get() is not None

    @contextmanager
    def range_reads(self):
        owner = _RangeConnections(self)
        with self._lock:
            if self._closed:
                raise control_error("unavailable", "read_artifact_chunk", {})
            self._range_owners.add(owner)
        token = self._range_session.set(owner)
        try:
            yield
        finally:
            self._range_session.reset(token)
            with self._lock:
                self._range_owners.discard(owner)
            owner.close()

    def close(self):
        super().close()
        with self._lock:
            owners = tuple(self._range_owners)
        for owner in owners:
            owner.close()

    def _exchange_for(self, operation: str):
        owner = self._range_session.get()
        if owner is not None and operation == "read_artifact_chunk":
            return owner.exchange
        return self._exchange

    def _connect(self, exchange):
        connection = self._connection(remaining(exchange.deadline))
        try:
            connection.connect()
            if connection.sock is None:
                raise OSError("coordinator connection has no socket")
            exchange.attach(connection.sock)
            return connection
        except BaseException:
            connection.close()
            raise

    def _exchange(self, exchange: _Exchange) -> Mapping[str, object]:
        raw = self._body(exchange, exchange.payload)
        connection = self._connect(exchange)
        try:
            return self._request(connection, exchange, exchange.operation, raw)
        finally:
            connection.close()

    @staticmethod
    def _body(exchange, payload):
        raw = encode_wire(payload)
        if len(raw) > 65_536:
            raise exchange.failure("invalid_request", boundary="client_protocol")
        return raw

    def _request(self, connection, exchange, operation, raw):
        call_deadline = exchange.deadline
        exchange.before_send()
        connection.sock.settimeout(remaining(call_deadline))
        connection.request(
            "POST",
            f"/v1/{self._role}/{operation}",
            body=raw,
            headers={
                "Content-Type": "application/json",
                "X-Loom-Client": CONTROL_CAPABILITY,
            },
        )
        # Header parsing can perform many socket reads; the separate caller
        # deadline still interrupts the socket if a peer trickles headers.
        connection.sock.settimeout(remaining(call_deadline))
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise exchange.failure("invalid_response", boundary="client_protocol")
        blocks: list[bytes] = []
        size = 0
        while not response.isclosed():
            if exchange.socket is not None:
                exchange.socket.settimeout(remaining(call_deadline))
            block = response.read1(min(65_536, MAX_RESPONSE_BYTES + 1 - size))
            if not block:
                break
            blocks.append(block)
            size += len(block)
            if size > MAX_RESPONSE_BYTES:
                raise exchange.failure(
                    "result_too_large", boundary="client_protocol"
                )
        return decode_wire(b"".join(blocks))



class _RangeConnections:
    """Lease a negotiated socket exclusively to one authenticated range exchange."""

    def __init__(self, transport: HttpsControlTransport):
        self.transport = transport
        self.principal_certificate = self._certificate_digest()
        self.lock = Lock()
        self.idle: list[tuple[http.client.HTTPSConnection, tuple]] = []
        self.closed = False

    def _certificate_digest(self):
        return hashlib.sha256(self.transport._credentials[1].read_bytes()).digest()

    def _credential_version(self):
        return tuple((s.st_dev, s.st_ino, s.st_size, s.st_ctime_ns)
                     for s in (path.stat() for path in self.transport._credentials))

    def exchange(self, exchange: _Exchange):
        transport = self.transport
        raw = transport._body(exchange, exchange.payload)
        version = self._credential_version()
        with self.lock:
            if self.closed:
                raise exchange.failure("unavailable")
            borrowed = self.idle.pop() if self.idle else None
        connection = None
        try:
            if borrowed is not None:
                candidate, previous = borrowed
                if previous == version and candidate.sock is not None:
                    connection = candidate
                    exchange.attach(candidate.sock)
                else:
                    candidate.close()
            if connection is None:
                connection = transport._connect(exchange)
                guard = {"expected_coordinator_id": exchange.payload["expected_coordinator_id"]}
                response = transport._request(connection, exchange, "handshake", transport._body(exchange, guard))
                value = decode_envelope(response, "handshake", guard)
                peer = decode_result("handshake", value)
                if peer.coordinator_id != guard["expected_coordinator_id"]:
                    raise exchange.failure("conflict")
                if peer.protocol_version != "1" or not {
                    CONTROL_CAPABILITY, "artifact-read-v1"
                }.issubset(peer.capabilities):
                    raise exchange.failure("unsupported")
                if self._credential_version() != version:
                    raise exchange.failure("unavailable")
                if self._certificate_digest() != self.principal_certificate:
                    raise exchange.failure("conflict")
                if connection.sock is None:
                    # A peer that closed after the handshake uses the existing
                    # separate-connection exchange. Never cache its negotiation.
                    return transport._exchange(exchange)
            result = transport._request(connection, exchange, exchange.operation, raw)
            if connection.sock is not None and result.get("ok") is True:
                # A caller expiring the old exchange must never close a socket
                # already leased to a different range.
                with exchange.lock:
                    reusable = not exchange.cancelled.is_set()
                    exchange.socket = None
                with self.lock:
                    if reusable and not self.closed:
                        self.idle.append((connection, version))
                        connection = None
            return result
        finally:
            if connection is not None:
                connection.close()

    def close(self):
        with self.lock:
            self.closed = True
            idle, self.idle = self.idle, []
        for connection, _ in idle:
            connection.close()
