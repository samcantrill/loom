"""Causal native-client boundary tests with real Unix peers and bounded stalls."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import json
from pathlib import Path
import socket
from threading import Event, Thread
import time

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError
from loom.queue import LocalDaemonSocketClient
from loom.queue import _coordinator_transport as control_io
from loom.queue._coordinator_control import (
    CONTROL_CAPABILITY,
    MAX_RESPONSE_BYTES,
    encode_wire,
)
from loom.queue.deployment import load_coordinator_connection_file
from loom.queue.errors import QueueConfigError
from loom.serialization import PlainData


_DESCRIPTION: dict[str, PlainData] = {
    "protocol_version": "1",
    "transport": "unix",
    "coordinator_id": "coordinator-a",
    "coordinator_epoch": "epoch-a",
    "capabilities": [CONTROL_CAPABILITY],
    "source_modes": [],
    "preparation_profiles": [],
    "source_roots": [],
}


@contextmanager
def _peer(
    endpoint: Path,
    respond: Callable[[socket.socket, Mapping[str, object]], None],
    *,
    handshake: bool = True,
) -> Iterator[list[Mapping[str, object]]]:
    """Serve a controllable peer; requests still use the real client framing/I/O."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(endpoint))
    listener.listen()
    listener.settimeout(0.05)
    stopped = Event()
    requests: list[Mapping[str, object]] = []
    errors: list[BaseException] = []

    def serve() -> None:
        while not stopped.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                try:
                    value = control_io.read_unix_message(
                        connection, deadline=time.monotonic() + 3
                    )
                    requests.append(value)
                    if handshake and value.get("operation") == "handshake":
                        connection.sendall(
                            encode_wire({"ok": True, "result": _DESCRIPTION}) + b"\n"
                        )
                    else:
                        respond(connection, value)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when the client enforces a deadline or byte bound.
                except BaseException as exc:
                    errors.append(exc)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield requests
    finally:
        stopped.set()
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not errors


def test_factory_is_lazy_and_connection_failure_preserves_submission_identity(
    tmp_path: Path,
) -> None:
    endpoint = tmp_path / "absent" / "service.sock"
    client = CoordinatorClient.from_unix_socket(endpoint)
    assert not endpoint.parent.exists()
    with pytest.raises(CoordinatorClientError) as caught:
        client.cancel("same-item")
    assert caught.value.code == "unavailable"
    assert caught.value.mutation_outcome == "not_applied"
    assert caught.value.ids["queue_item_id"] == "same-item"
    assert not endpoint.parent.exists()


@pytest.mark.parametrize("duration", [-1, 26, float("nan"), float("inf"), True, None])
def test_invalid_observation_is_rejected_before_connection(
    tmp_path: Path, duration: object
) -> None:
    client = CoordinatorClient.from_unix_socket(tmp_path / "absent.sock")
    with pytest.raises(CoordinatorClientError) as caught:
        client.wait_operation("operation-a", timeout_seconds=duration)  # type: ignore[arg-type]
    assert caught.value.code == "invalid_request"
    assert caught.value.ids["operation_id"] == "operation-a"
    assert caught.value.mutation_outcome is None


@pytest.mark.parametrize(
    "raw",
    [
        b'{"ok":true,"result":{}}',
        b'{"ok":true,"ok":false}',
        b'{"ok":false,"error":[]}',
        b'{"ok":true,"result":{"number":1e999}}',
        b"not-json",
    ],
)
def test_bad_mutation_reply_is_unknown_without_retry(
    tmp_path: Path, raw: bytes
) -> None:
    endpoint = tmp_path / "service.sock"
    with _peer(
        endpoint, lambda connection, _: connection.sendall(raw + b"\n")
    ) as requests:
        with CoordinatorClient.from_unix_socket(endpoint) as client:
            with pytest.raises(CoordinatorClientError) as caught:
                client.cancel("original-item")
        assert caught.value.code == "invalid_response"
        assert caught.value.mutation_outcome == "unknown"
        assert caught.value.ids["queue_item_id"] == "original-item"
        assert [row["operation"] for row in requests] == ["handshake", "cancel"]


def test_oversized_reply_is_explicit_and_preserves_unknown_mutation(
    tmp_path: Path,
) -> None:
    endpoint = tmp_path / "service.sock"
    with _peer(
        endpoint,
        lambda connection, _: connection.sendall(b" " * (MAX_RESPONSE_BYTES + 1)),
    ):
        with pytest.raises(CoordinatorClientError) as caught:
            CoordinatorClient.from_unix_socket(endpoint).cancel("original-item")
    assert caught.value.code == "result_too_large"
    assert caught.value.mutation_outcome == "unknown"
    assert caught.value.ids["queue_item_id"] == "original-item"


def test_inspected_failure_is_a_successful_native_read(tmp_path: Path) -> None:
    endpoint = tmp_path / "service.sock"
    result: dict[str, PlainData] = {"schema_version": 1, "code": "not_found"}
    with _peer(
        endpoint,
        lambda connection, _: connection.sendall(
            encode_wire({"ok": True, "result": result}) + b"\n"
        ),
    ):
        observed = CoordinatorClient.from_unix_socket(endpoint).inspect_run(
            "file:///managed/run"
        )
    assert observed.to_dict() == result


@pytest.mark.parametrize("during_handshake", [False, True])
def test_trickle_does_not_restart_cumulative_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    during_handshake: bool,
) -> None:
    monkeypatch.setattr(control_io, "REQUEST_BUDGET_SECONDS", 0.2)
    endpoint = tmp_path / "service.sock"

    def trickle(connection: socket.socket, _request: Mapping[str, object]) -> None:
        for byte in b'{"ok":true,"result":{}}\n':
            connection.sendall(bytes([byte]))
            time.sleep(0.04)

    with _peer(endpoint, trickle, handshake=not during_handshake) as requests:
        started = time.monotonic()
        with pytest.raises(CoordinatorClientError) as caught:
            CoordinatorClient.from_unix_socket(endpoint).cancel("original-item")
        elapsed = time.monotonic() - started
        assert elapsed < 0.8
        assert caught.value.code == "deadline_exceeded"
        assert caught.value.mutation_outcome == (
            "not_applied" if during_handshake else "unknown"
        )
        assert caught.value.ids["queue_item_id"] == "original-item"
        if during_handshake:
            assert [row["operation"] for row in requests] == ["handshake"]


def test_legacy_inspection_needs_no_new_handshake_or_metadata(tmp_path: Path) -> None:
    endpoint = tmp_path / "old.sock"
    with _peer(
        endpoint,
        lambda connection, _: connection.sendall(
            b'{"ok":true,"result":{"old":true}}\n'
        ),
        handshake=False,
    ) as requests:
        assert LocalDaemonSocketClient(endpoint).inspect_run(
            "file:///unmanaged/run"
        ) == {"old": True}
        assert requests == [
            {"operation": "inspect_run", "run_uri": "file:///unmanaged/run"}
        ]


def test_connection_config_uses_relative_protected_files_and_optional_guard(
    tmp_path: Path,
) -> None:
    for name in ("ca.crt", "client.crt", "client.key"):
        file = tmp_path / name
        file.write_text("TLS material is loaded only when connecting")
        file.chmod(0o600)
    path = tmp_path / "client.yaml"
    value = {
        "schema_version": 1,
        "kind": "loom.coordinator-client",
        "transport": {
            "kind": "https",
            "url": "https://localhost:8443",
            "server_ca_path": "ca.crt",
            "certificate_path": "client.crt",
            "private_key_path": "client.key",
        },
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    loaded = load_coordinator_connection_file(path)
    assert loaded.expected_coordinator_id is None
    assert loaded.private_key_path == tmp_path / "client.key"
    with CoordinatorClient.from_connection_file(path):
        pass  # Constructing a client must not parse certificates or contact TLS.
    (tmp_path / "client.key").chmod(0o644)
    with pytest.raises(QueueConfigError, match="owner-protected"):
        load_coordinator_connection_file(path)


def test_native_and_legacy_page_defaults_share_decoding(tmp_path: Path) -> None:
    endpoint = tmp_path / "service.sock"
    result: dict[str, PlainData] = {"admissions": [], "next_cursor": None}
    with _peer(
        endpoint,
        lambda connection, _: connection.sendall(
            encode_wire({"ok": True, "result": result}) + b"\n"
        ),
    ) as requests:
        assert (
            CoordinatorClient.from_unix_socket(endpoint).admissions().admissions == ()
        )
        assert LocalDaemonSocketClient(endpoint).admissions().admissions == ()
        assert [
            row["limit"] for row in requests if row["operation"] == "admissions"
        ] == [20, 100]


def test_old_application_handshake_refuses_dependent_mutation_as_unsupported(
    tmp_path: Path,
) -> None:
    endpoint = tmp_path / "old.sock"
    legacy: dict[str, PlainData] = {
        "protocol_version": "1",
        "capabilities": ["authenticated-application-v1"],
        "coordinator_id": "coordinator-a",
        "coordinator_epoch": "epoch-a",
        "role": "client",
    }
    with _peer(
        endpoint,
        lambda connection, _: connection.sendall(
            encode_wire({"ok": True, "result": legacy}) + b"\n"
        ),
        handshake=False,
    ) as requests:
        with pytest.raises(CoordinatorClientError) as caught:
            CoordinatorClient.from_unix_socket(endpoint).cancel("original-item")
        assert caught.value.code == "unsupported"
        assert caught.value.mutation_outcome == "not_applied"
        assert caught.value.ids["queue_item_id"] == "original-item"
        assert [request["operation"] for request in requests] == ["handshake"]
