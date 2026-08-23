"""Small mutual-TLS adapter for the restricted agent-session view.

The adapter derives a configured credential ID from the verified client
certificate's DER fingerprint.  It never accepts an actor, principal, agent,
or session selector from the HTTP path as transport identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import http.client
import json
from pathlib import Path
import ssl
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .agent_sessions import (
    AgentOffer,
    AgentRegistration,
    AgentSession,
    ScopedAuthorizer,
    _session_from_value,
)
from .errors import QueueConflictError, QueueError, QueueServiceError
from .local_daemon import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)


_MAX_BODY_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class AgentTlsServerConfig:
    host: str
    port: int
    certificate_path: Path
    private_key_path: Path
    client_ca_path: Path
    credential_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.host or not 0 <= self.port <= 65535:
            raise QueueServiceError("agent TLS server endpoint is invalid")
        if not self.credential_fingerprints:
            raise QueueServiceError("agent TLS credential map is required")
        for fingerprint, credential in self.credential_fingerprints.items():
            if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
                raise QueueServiceError("TLS certificate fingerprint is invalid")
            if not credential:
                raise QueueServiceError("TLS credential ID is invalid")


@dataclass(frozen=True, slots=True)
class AgentTlsClientConfig:
    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
            raise QueueServiceError("agent TLS URL must be one HTTPS service identity")


class LocalDaemonAgentHttpServer:
    """Loopback/deployment server; it exposes no inbound agent listener."""

    def __init__(self, daemon: LocalDaemon, config: AgentTlsServerConfig) -> None:
        self._daemon = daemon
        self._config = config
        self._server: _MutualTlsHttpServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise QueueServiceError("agent TLS server is not started")
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            raise QueueServiceError("agent TLS server is already started")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(self._config.certificate_path, self._config.private_key_path)
        context.load_verify_locations(cafile=self._config.client_ca_path)
        server = _MutualTlsHttpServer(
            (self._config.host, self._config.port), context, self._daemon,
            dict(self._config.credential_fingerprints),
        )
        self._server = server
        self._thread = Thread(target=server.serve_forever, daemon=True, name="loom-agent-mtls")
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None


class LocalDaemonAgentHttpClient:
    """A no-redirect persistent HTTPS caller for one configured service name."""

    def __init__(self, config: AgentTlsClientConfig) -> None:
        self._config = config
        self._connection: http.client.HTTPSConnection | None = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    def handshake(self) -> Mapping[str, PlainData]:
        return self._call("handshake", {})

    def register(self, request: AgentRegistration) -> AgentSession:
        return _session_from_value(self._call("register", request.value()))

    def reconcile(self, session_id: str, coordinator_epoch: str) -> AgentSession:
        return _session_from_value(self._call("reconcile", {"session_id": session_id, "coordinator_epoch": coordinator_epoch}))

    def publish_offer(self, offer: AgentOffer, *, idempotency_key: str) -> Mapping[str, PlainData]:
        return self._call("offer", {"offer": offer.value(), "idempotency_key": idempotency_key})

    def wait_for_work(self, session_id: str, availability_revision: str, *, poll_id: str) -> Mapping[str, PlainData]:
        return self._call("poll", {"session_id": session_id, "availability_revision": availability_revision, "poll_id": poll_id})

    def retire_clean(self, session_id: str, *, idempotency_key: str) -> Mapping[str, PlainData]:
        return self._call("retire", {"session_id": session_id, "idempotency_key": idempotency_key})

    def call_application(
        self, role: str, operation: str, value: Mapping[str, PlainData]
    ) -> Mapping[str, PlainData]:
        """Call the authenticated client/operator view selected by its certificate."""
        if role not in {"client", "operator"}:
            raise QueueServiceError("authenticated application role is invalid")
        return self._call(operation, value, role=role)

    def _call(
        self, operation: str, value: Mapping[str, PlainData], *, role: str = "agent"
    ) -> Mapping[str, PlainData]:
        parsed = urlsplit(self._config.url)
        assert parsed.hostname is not None
        context = ssl.create_default_context(cafile=self._config.server_ca_path)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self._config.certificate_path, self._config.private_key_path)
        connection = self._connection
        if connection is None:
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=context, timeout=5)
            self._connection = connection
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        try:
            connection.request("POST", f"/v1/{role}/{operation}", body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(_MAX_BODY_BYTES + 1)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            self.close()
            raise QueueServiceError("agent protocol outcome is indeterminate") from exc
        if len(raw) > _MAX_BODY_BYTES:
            raise QueueServiceError("agent protocol response is too large")
        payload = _decode(raw)
        if response.status != 200 or payload.get("ok") is not True:
            code = payload.get("error")
            raise QueueServiceError(str(code) if isinstance(code, str) else "agent protocol request failed")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise QueueServiceError("agent protocol response is invalid")
        return freeze_plain_data(result, path="agent HTTP response")


class _MutualTlsHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: ssl.SSLContext, daemon: LocalDaemon, credential_fingerprints: Mapping[str, str]) -> None:
        self._context = context
        self.daemon_owner = daemon
        self.credential_fingerprints = credential_fingerprints
        super().__init__(address, _Handler)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        connection, address = super().get_request()
        try:
            return self._context.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    @property
    def _daemon_server(self) -> _MutualTlsHttpServer:
        return cast(_MutualTlsHttpServer, self.server)

    def log_message(self, format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        try:
            certificate = cast(ssl.SSLSocket, self.connection).getpeercert(binary_form=True)
            if certificate is None:
                raise QueueServiceError("agent TLS peer is unavailable")
            fingerprint = hashlib.sha256(certificate).hexdigest()
            credential = self._daemon_server.credential_fingerprints.get(fingerprint)
            if credential is None:
                raise QueueServiceError("agent TLS credential is not accepted")
            principal_id, mapped_role = ScopedAuthorizer(
                self._daemon_server.daemon_owner._agent_policy
            ).transport_principal(credential)
            if self.headers.get("Content-Type") != "application/json":
                raise QueueServiceError("agent protocol content type is invalid")
            length = self.headers.get("Content-Length")
            if length is None or not length.isdecimal() or int(length) > _MAX_BODY_BYTES:
                raise QueueServiceError("agent protocol body is invalid")
            payload = _decode(self.rfile.read(int(length)))
            segments = self.path.split("/")
            if len(segments) != 4 or segments[0] or segments[1] != "v1":
                raise QueueServiceError("agent protocol operation is unsupported")
            role_name, operation = segments[2:]
            if role_name != mapped_role:
                raise QueueServiceError("agent TLS credential is not authorized")
            principal = LocalDaemonPrincipal(
                principal_id, LocalDaemonRole(mapped_role), credential
            )
            if role_name == "agent":
                if operation not in {"handshake", "register", "reconcile", "offer", "poll", "retire"}:
                    raise QueueServiceError("agent protocol operation is unsupported")
                result = _dispatch(self._daemon_server.daemon_owner.agent_view(principal), operation, payload)
            else:
                result = _dispatch_application(self._daemon_server.daemon_owner, principal, role_name, operation, payload)
            self._reply(200, {"ok": True, "result": result})
        except QueueConflictError:
            self._reply(409, {"ok": False, "error": "agent_protocol_conflict"})
        except QueueError:
            self._reply(403, {"ok": False, "error": "agent_protocol_rejected"})
        except Exception:
            self._reply(400, {"ok": False, "error": "agent_protocol_invalid"})

    def _reply(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(
            thaw_plain_data(payload, path="agent HTTP response"),
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _dispatch(view: Any, operation: str, value: Mapping[str, object]) -> Mapping[str, PlainData]:
    if operation == "handshake":
        _exact(value, set())
        return view.handshake()
    if operation == "register":
        return view.register(_registration(value)).value()
    if operation == "reconcile":
        _exact(value, {"session_id", "coordinator_epoch"})
        return view.reconcile(_string(value, "session_id"), _string(value, "coordinator_epoch")).value()
    if operation == "offer":
        _exact(value, {"offer", "idempotency_key"})
        offer = value["offer"]
        if not isinstance(offer, Mapping):
            raise QueueServiceError("agent offer is invalid")
        return view.publish_offer(_offer(offer), idempotency_key=_string(value, "idempotency_key"))
    if operation == "poll":
        _exact(value, {"session_id", "availability_revision", "poll_id"})
        return view.wait_for_work(_string(value, "session_id"), _string(value, "availability_revision"), poll_id=_string(value, "poll_id"))
    _exact(value, {"session_id", "idempotency_key"})
    return view.retire_clean(_string(value, "session_id"), idempotency_key=_string(value, "idempotency_key"))


def _dispatch_application(
    daemon: LocalDaemon,
    principal: LocalDaemonPrincipal,
    role: str,
    operation: str,
    value: Mapping[str, object],
) -> Mapping[str, PlainData]:
    if role == "client":
        view = daemon.client_view(principal)
        if operation == "status":
            _exact(value, set())
            return view.status().to_dict()
        if operation == "cancel":
            _exact(value, {"queue_item_id"})
            return view.cancel(_string(value, "queue_item_id")).to_dict()
        if operation == "submit":
            request = value.get("request")
            if not isinstance(request, Mapping):
                raise QueueServiceError("client admission request is invalid")
            return view.submit(LocalDaemonAdmissionRequest.from_dict(request)).to_dict()
    elif role == "operator":
        view = daemon.operator_view(principal)
        if operation == "status":
            _exact(value, set())
            return view.status().to_dict()
        if operation == "reconcile":
            _exact(value, set())
            return {"admissions": [admission.to_dict() for admission in view.reconcile_once()]}
    raise QueueServiceError("daemon protocol operation is unsupported")


def _registration(value: Mapping[str, object]) -> AgentRegistration:
    _exact(value, {"idempotency_key", "coordinator_id", "coordinator_epoch", "config_revision", "inventory_revision", "availability_revision", "declared_capabilities", "session_id"})
    capabilities = value["declared_capabilities"]
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise QueueServiceError("agent capabilities are invalid")
    session_id = value["session_id"]
    if session_id is not None and not isinstance(session_id, str):
        raise QueueServiceError("agent session ID is invalid")
    return AgentRegistration(
        idempotency_key=_string(value, "idempotency_key"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        declared_capabilities=tuple(capabilities),
        session_id=session_id,
    )


def _offer(value: Mapping[str, object]) -> AgentOffer:
    _exact(value, {"session_id", "coordinator_epoch", "config_revision", "inventory_revision", "availability_revision", "cpu", "memory_bytes", "ttl_seconds", "reflected_claim_ids"})
    claims = value["reflected_claim_ids"]
    if not isinstance(claims, list) or any(not isinstance(item, str) for item in claims):
        raise QueueServiceError("agent reflected claims are invalid")
    numeric = (value["cpu"], value["memory_bytes"], value["ttl_seconds"])
    if any(isinstance(item, bool) or not isinstance(item, int) for item in numeric):
        raise QueueServiceError("agent offer quantities are invalid")
    return AgentOffer(
        session_id=_string(value, "session_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        cpu=cast(int, numeric[0]),
        memory_bytes=cast(int, numeric[1]),
        ttl_seconds=cast(int, numeric[2]),
        reflected_claim_ids=tuple(claims),
    )


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise QueueServiceError(f"agent protocol {key} is invalid")
    return item


def _exact(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise QueueServiceError("agent protocol fields are invalid")


def _decode(raw: bytes) -> Mapping[str, object]:
    if len(raw) > _MAX_BODY_BYTES:
        raise QueueServiceError("agent protocol body is too large")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueueServiceError("agent protocol JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent protocol body is not an object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON value")


__all__ = ["AgentTlsClientConfig", "AgentTlsServerConfig", "LocalDaemonAgentHttpClient", "LocalDaemonAgentHttpServer"]
