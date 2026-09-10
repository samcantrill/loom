"""Direct, bounded control of one Loom coordinator.

The facade deliberately owns only connection selection, native request envelopes
and result decoding.  Admission and scheduling truth remain in ``loom.queue``;
diagnostic projection remains in ``loom.diagnostics``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import http.client
import json
from pathlib import Path
import socket
import ssl
import time
from typing import cast
from urllib.parse import urlsplit

from loom.diagnostics.run_inspection import RunInspectionResponse, decode_run_inspection_response
from loom.queue.errors import QueueConfigError, QueueServiceError
from loom.queue.local_daemon import (
    AdmissionPage,
    AdmissionWaitResult,
    AgentPage,
    AgentProjection,
    DaemonStatus,
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    LocalDaemonAdmissionRequest,
    LocalDaemonOperation,
    OperationWaitResult,
)
from loom.serialization import PlainData


_MAX_MESSAGE_BYTES = 1_048_576
_REQUEST_BUDGET_SECONDS = 30.0
_MAX_OBSERVATION_SECONDS = 25.0


class CoordinatorClientError(QueueServiceError):
    """A classified failure at a direct coordinator-client boundary."""

    def __init__(
        self,
        code: str,
        *,
        boundary: str,
        operation: str,
        ids: Mapping[str, PlainData] | None = None,
        evidence_refs: tuple[str, ...] = (),
        mutation_outcome: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or f"coordinator {operation} failed: {code}")
        self.code = code
        self.boundary = boundary
        self.operation = operation
        self.ids = dict(ids or {})
        self.evidence_refs = evidence_refs
        self.mutation_outcome = mutation_outcome


@dataclass(frozen=True, slots=True)
class CoordinatorConnectionDescription:
    protocol_version: str
    transport: str
    coordinator_id: str
    coordinator_epoch: str
    capabilities: tuple[str, ...]
    source_modes: tuple[str, ...]
    preparation_profiles: tuple[str, ...]
    source_roots: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CoordinatorConnectionDescription":
        required = {
            "protocol_version", "transport", "coordinator_id", "coordinator_epoch",
            "capabilities", "source_modes", "preparation_profiles", "source_roots",
        }
        if set(value) != required:
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="handshake")
        strings = ("protocol_version", "transport", "coordinator_id", "coordinator_epoch")
        if any(not isinstance(value[key], str) or not value[key] for key in strings):
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="handshake")
        sequences: list[tuple[str, ...]] = []
        for key in ("capabilities", "source_modes", "preparation_profiles", "source_roots"):
            item = value[key]
            if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
                raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="handshake")
            sequences.append(tuple(item))
        return cls(*(cast(str, value[key]) for key in strings), *sequences)


@dataclass(frozen=True, slots=True)
class CoordinatorConnectionFile:
    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path
    expected_coordinator_id: str | None


class _Transport:
    def call(self, operation: str, payload: Mapping[str, PlainData], deadline: float) -> Mapping[str, object]:
        raise NotImplementedError

    def close(self) -> None:
        return


class _UnixTransport(_Transport):
    def __init__(self, endpoint: str | Path) -> None:
        self.endpoint = Path(endpoint)

    def call(self, operation: str, payload: Mapping[str, PlainData], deadline: float) -> Mapping[str, object]:
        request = {"operation": operation, **payload}
        raw = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(raw) > _MAX_MESSAGE_BYTES:
            raise CoordinatorClientError("result_too_large", boundary="client_protocol", operation=operation)
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            remaining = _remaining(deadline, operation)
            connection.settimeout(remaining)
            connection.connect(str(self.endpoint))
            connection.sendall(raw)
            chunks: list[bytes] = []
            total = 0
            while True:
                connection.settimeout(_remaining(deadline, operation))
                block = connection.recv(min(65_536, _MAX_MESSAGE_BYTES + 1 - total))
                if not block:
                    break
                chunks.append(block)
                total += len(block)
                if total > _MAX_MESSAGE_BYTES:
                    raise CoordinatorClientError("result_too_large", boundary="client_protocol", operation=operation)
                if b"\n" in block:
                    break
        except CoordinatorClientError:
            raise
        except (OSError, TimeoutError) as exc:
            raise CoordinatorClientError("unavailable", boundary="connection", operation=operation, mutation_outcome="unknown" if operation in {"submit", "cancel"} else None) from exc
        finally:
            connection.close()
        try:
            response = json.loads(b"".join(chunks).split(b"\n", 1)[0])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation=operation) from exc
        return _result_or_error(response, operation)


class _HttpsTransport(_Transport):
    def __init__(self, config: CoordinatorConnectionFile) -> None:
        self._config = config
        parsed = urlsplit(config.url)
        self._host = cast(str, parsed.hostname)
        self._port = parsed.port or 443

    def call(self, operation: str, payload: Mapping[str, PlainData], deadline: float) -> Mapping[str, object]:
        context = ssl.create_default_context(cafile=self._config.server_ca_path)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self._config.certificate_path, self._config.private_key_path)
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        connection = http.client.HTTPSConnection(self._host, self._port, context=context, timeout=min(10.0, _remaining(deadline, operation)))
        try:
            connection.request("POST", f"/v1/client/{operation}", body=body, headers={"Content-Type": "application/json", "X-Loom-Client": "daemon-control-v1"})
            response = connection.getresponse()
            raw = response.read(_MAX_MESSAGE_BYTES + 1)
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
            raise CoordinatorClientError("unavailable", boundary="connection", operation=operation, mutation_outcome="unknown" if operation in {"submit", "cancel"} else None) from exc
        finally:
            connection.close()
        if len(raw) > _MAX_MESSAGE_BYTES:
            raise CoordinatorClientError("result_too_large", boundary="client_protocol", operation=operation)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation=operation) from exc
        return _result_or_error(value, operation)


class CoordinatorClient:
    """Unified local or mTLS client for coordinator-owned control operations."""

    def __init__(self, transport: _Transport, *, expected_coordinator_id: str | None = None) -> None:
        self._transport = transport
        self._expected_coordinator_id = _optional_id(expected_coordinator_id)
        self._description: CoordinatorConnectionDescription | None = None

    @classmethod
    def from_unix_socket(cls, path: str | Path, *, expected_coordinator_id: str | None = None) -> "CoordinatorClient":
        return cls(_UnixTransport(path), expected_coordinator_id=expected_coordinator_id)

    @classmethod
    def from_connection_file(cls, path: str | Path, *, expected_coordinator_id: str | None = None) -> "CoordinatorClient":
        config = load_coordinator_connection_file(path)
        guard = _merge_guard(config.expected_coordinator_id, expected_coordinator_id)
        return cls(_HttpsTransport(config), expected_coordinator_id=guard)

    def __enter__(self) -> "CoordinatorClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def describe_connection(self, *, expected_coordinator_id: str | None = None) -> CoordinatorConnectionDescription:
        result = self._call("handshake", {}, expected_coordinator_id=expected_coordinator_id)
        description = CoordinatorConnectionDescription.from_dict(result)
        if "daemon-control-v1" not in description.capabilities:
            raise CoordinatorClientError("unsupported", boundary="client_protocol", operation="handshake")
        self._description = description
        return description

    def status(self, *, expected_coordinator_id: str | None = None) -> DaemonStatus:
        return DaemonStatus.from_dict(self._call("status", {}, expected_coordinator_id=expected_coordinator_id))

    def admissions(self, limit: int = 20, cursor: str | None = None, *, expected_coordinator_id: str | None = None) -> AdmissionPage:
        _limit(limit)
        result = self._call("admissions", {"limit": limit, "cursor": cursor}, expected_coordinator_id=expected_coordinator_id)
        return _admission_page(result)

    def admission(self, admission_id: str, *, expected_coordinator_id: str | None = None) -> LocalDaemonAdmissionDetail:
        return LocalDaemonAdmissionDetail.from_dict(self._call("admission", {"admission_id": admission_id}, expected_coordinator_id=expected_coordinator_id))

    def admission_for_queue_item(self, queue_item_id: str, *, expected_coordinator_id: str | None = None) -> LocalDaemonAdmission:
        return LocalDaemonAdmission.from_dict(self._call("admission_for_queue_item", {"queue_item_id": queue_item_id}, expected_coordinator_id=expected_coordinator_id))

    def agents(self, limit: int = 20, cursor: str | None = None, *, expected_coordinator_id: str | None = None) -> AgentPage:
        _limit(limit)
        return AgentPage.from_dict(self._call("agents", {"limit": limit, "cursor": cursor}, expected_coordinator_id=expected_coordinator_id))

    def agent(self, agent_id: str, *, expected_coordinator_id: str | None = None) -> AgentProjection:
        return AgentProjection.from_dict(self._call("agent", {"agent_id": agent_id}, expected_coordinator_id=expected_coordinator_id))

    def inspect_run(self, run_uri: str, *, expected_coordinator_id: str | None = None) -> RunInspectionResponse:
        return decode_run_inspection_response(self._call("inspect_run", {"run_uri": run_uri}, expected_coordinator_id=expected_coordinator_id))

    def operation(self, operation_id: str, *, expected_coordinator_id: str | None = None) -> LocalDaemonOperation:
        return LocalDaemonOperation.from_dict(self._call("operation", {"operation_id": operation_id}, expected_coordinator_id=expected_coordinator_id))

    def wait_operation(self, operation_id: str, timeout_seconds: float = 25, *, expected_coordinator_id: str | None = None) -> OperationWaitResult:
        timeout = _observation_timeout(timeout_seconds)
        return OperationWaitResult.from_dict(self._call("wait_operation", {"operation_id": operation_id, "timeout": timeout}, expected_coordinator_id=expected_coordinator_id))

    def submit(self, request: LocalDaemonAdmissionRequest, *, expected_coordinator_id: str | None = None) -> LocalDaemonAdmission:
        if not isinstance(request, LocalDaemonAdmissionRequest):
            raise CoordinatorClientError("invalid_request", boundary="client_protocol", operation="submit")
        return LocalDaemonAdmission.from_dict(self._call("submit", {"request": request.to_dict()}, expected_coordinator_id=expected_coordinator_id))

    def wait_admission(self, admission_id: str, expected_revision: int, timeout_seconds: float = 25, *, expected_coordinator_id: str | None = None) -> AdmissionWaitResult:
        timeout = _observation_timeout(timeout_seconds)
        value = self._call("wait_admission", {"admission_id": admission_id, "expected_revision": expected_revision, "timeout": timeout}, expected_coordinator_id=expected_coordinator_id)
        kind, admission, revision = value.get("kind"), value.get("admission"), value.get("revision")
        if not isinstance(kind, str) or not isinstance(admission, Mapping) or isinstance(revision, bool) or not isinstance(revision, int):
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="wait_admission")
        from loom.queue.local_daemon import AdmissionWaitKind
        try:
            return AdmissionWaitResult(AdmissionWaitKind(kind), LocalDaemonAdmission.from_dict(admission), revision)
        except ValueError as exc:
            raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="wait_admission") from exc

    def cancel(self, queue_item_id: str, *, expected_coordinator_id: str | None = None) -> LocalDaemonAdmission:
        return LocalDaemonAdmission.from_dict(self._call("cancel", {"queue_item_id": queue_item_id}, expected_coordinator_id=expected_coordinator_id))

    def wait(self, queue_item_id: str, timeout_seconds: float | None = None, *, expected_coordinator_id: str | None = None) -> LocalDaemonAdmission:
        if timeout_seconds is not None and (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds < 0):
            raise CoordinatorClientError("invalid_request", boundary="client_protocol", operation="wait")
        deadline = None if timeout_seconds is None else time.monotonic() + float(timeout_seconds)
        admission = self.admission_for_queue_item(queue_item_id, expected_coordinator_id=expected_coordinator_id)
        while True:
            remaining = _MAX_OBSERVATION_SECONDS if deadline is None else max(0.0, min(_MAX_OBSERVATION_SECONDS, deadline - time.monotonic()))
            observed = self.wait_admission(admission.admission_id, admission.revision, remaining, expected_coordinator_id=expected_coordinator_id)
            admission = observed.admission
            if observed.kind.value == "TERMINAL":
                return admission
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("managed local admission did not reach terminal state")

    def _call(self, operation: str, payload: Mapping[str, PlainData], *, expected_coordinator_id: str | None) -> Mapping[str, object]:
        expected = _merge_guard(self._expected_coordinator_id, expected_coordinator_id)
        if operation != "handshake" and self._description is None:
            # The facade is deliberately unavailable on an old service before a
            # caller can make a dependent read or mutation.
            self.describe_connection(expected_coordinator_id=expected)
        envelope: dict[str, PlainData] = dict(payload)
        if expected is not None:
            envelope["expected_coordinator_id"] = expected
        result = self._transport.call(operation, envelope, time.monotonic() + _REQUEST_BUDGET_SECONDS)
        return result


def load_coordinator_connection_file(path: str | Path) -> CoordinatorConnectionFile:
    """Load the strict protected ``loom.coordinator-client`` v1 file."""
    from loom.queue.deployment import _load_protected_config

    source, _environment, payload, _fingerprint = _load_protected_config(path)
    required = {"schema_version", "kind", "transport", "expected_coordinator_id"}
    if set(payload) != required or payload.get("schema_version") != 1 or payload.get("kind") != "loom.coordinator-client":
        raise QueueConfigError("coordinator client config is invalid")
    expected = payload["expected_coordinator_id"]
    if expected is not None and (not isinstance(expected, str) or not expected):
        raise QueueConfigError("coordinator client expected coordinator ID is invalid")
    transport = payload["transport"]
    if not isinstance(transport, Mapping) or set(transport) != {"kind", "url", "server_ca_path", "certificate_path", "private_key_path"} or transport.get("kind") != "https":
        raise QueueConfigError("coordinator client transport is invalid")
    base = source.parent
    try:
        values = {key: transport[key] for key in ("url", "server_ca_path", "certificate_path", "private_key_path")}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError
        result = CoordinatorConnectionFile(cast(str, values["url"]), *(base / cast(str, values[key]) if not Path(cast(str, values[key])).is_absolute() else Path(cast(str, values[key])) for key in ("server_ca_path", "certificate_path", "private_key_path")), cast(str | None, expected))
        parsed = urlsplit(result.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise QueueConfigError("coordinator client transport is invalid") from None


def _result_or_error(value: object, operation: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation=operation)
    if value.get("ok") is True and isinstance(value.get("result"), Mapping):
        return cast(Mapping[str, object], value["result"])
    detail = value.get("error_detail")
    if isinstance(detail, Mapping):
        return _raise_detail(detail, operation)
    code = value.get("error")
    raise CoordinatorClientError(str(code) if isinstance(code, str) else "invalid_response", boundary="client_protocol", operation=operation)


def _raise_detail(detail: Mapping[str, object], fallback_operation: str) -> Mapping[str, object]:
    required = {"schema_version", "code", "boundary", "operation", "ids", "evidence_refs", "mutation_outcome"}
    if set(detail) != required or detail.get("schema_version") != 1:
        raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation=fallback_operation)
    code, boundary, operation = detail.get("code"), detail.get("boundary"), detail.get("operation")
    ids, refs, outcome = detail.get("ids"), detail.get("evidence_refs"), detail.get("mutation_outcome")
    if not all(isinstance(item, str) and item for item in (code, boundary, operation)) or not isinstance(ids, Mapping) or not isinstance(refs, list) or any(not isinstance(item, str) for item in refs) or outcome not in (None, "not_applied", "applied", "unknown"):
        raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation=fallback_operation)
    raise CoordinatorClientError(cast(str, code), boundary=cast(str, boundary), operation=cast(str, operation), ids=cast(Mapping[str, PlainData], ids), evidence_refs=tuple(refs), mutation_outcome=cast(str | None, outcome))


def _remaining(deadline: float, operation: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CoordinatorClientError("deadline_exceeded", boundary="connection", operation=operation)
    return remaining


def _optional_id(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not value):
        raise CoordinatorClientError("invalid_request", boundary="client_protocol", operation="connection")
    return value


def _merge_guard(configured: str | None, call: str | None) -> str | None:
    call = _optional_id(call)
    if configured is not None and call is not None and configured != call:
        raise CoordinatorClientError("conflict", boundary="client_protocol", operation="connection", ids={"configured_expected_coordinator_id": configured, "expected_coordinator_id": call})
    return configured if configured is not None else call


def _limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise CoordinatorClientError("invalid_request", boundary="client_protocol", operation="page")


def _observation_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= _MAX_OBSERVATION_SECONDS or value != value or value in (float("inf"), float("-inf")):
        raise CoordinatorClientError("invalid_request", boundary="client_protocol", operation="observation")
    return float(value)


def _admission_page(value: Mapping[str, object]) -> AdmissionPage:
    records, cursor = value.get("admissions"), value.get("next_cursor")
    if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records) or (cursor is not None and not isinstance(cursor, str)):
        raise CoordinatorClientError("invalid_response", boundary="client_protocol", operation="admissions")
    return AdmissionPage(tuple(LocalDaemonAdmission.from_dict(item) for item in records), cursor)


__all__ = ["CoordinatorClient", "CoordinatorClientError", "CoordinatorConnectionDescription", "CoordinatorConnectionFile", "load_coordinator_connection_file"]
