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

from loom.coordinator import CoordinatorClient, CoordinatorClientError, CoordinatorOperatorClient
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
    "capabilities": [CONTROL_CAPABILITY, "operator-observations-v1"],
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
                    if handshake and value.get("operation") in {"handshake", "operator_handshake"}:
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


def test_old_coordinator_rejects_context_before_sending_submission(tmp_path: Path) -> None:
    from loom.queue.preparation import PreparationSource, PrepareRunRequest
    from loom.runs import SubmissionContext

    endpoint = tmp_path / "old.sock"
    request = PrepareRunRequest("operation", "run", PreparationSource("shared", "project", ".", ("pipeline.yaml",)),
                                "pipeline.yaml", "profile", context=SubmissionContext("reason"))
    with _peer(endpoint, lambda *_: pytest.fail("submission reached an old server")) as requests:
        with CoordinatorClient.from_unix_socket(endpoint) as client:
            with pytest.raises(CoordinatorClientError) as error:
                client.prepare_run(request)
            assert error.value.code == "unsupported"
            assert error.value.mutation_outcome == "not_applied"
        assert [item["operation"] for item in requests] == ["handshake"]


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


def test_native_page_defaults_and_explicit_limit_share_decoding(tmp_path: Path) -> None:
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
        assert CoordinatorClient.from_unix_socket(endpoint).admissions(limit=100).admissions == ()
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


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, EOFError])
def test_run_observation_interruption_returns_known_reference_without_cancellation(tmp_path, interruption):
    operation = {"operation_id": "run-original", "kind": "run", "state": "pending", "code": None,
                 "result": {"coordinator_id": "coordinator-a", "queue_item_id": "queue-original", "admission": None}}
    def respond(connection, request):
        assert request["operation"] == "operation"
        connection.sendall(encode_wire({"ok": True, "result": operation}) + b"\n")
    with _peer(tmp_path / "service.sock", respond) as requests:
        client = CoordinatorClient.from_unix_socket(tmp_path / "service.sock")
        def interrupt(*args, **kwargs):
            raise interruption()
        client._wait_native = interrupt
        observed = client.observe_run("run-original")
        assert observed.operation is not None
        assert observed.operation.operation_id == "run-original"
        assert observed.admission is None
        assert observed.connection.coordinator_id == "coordinator-a"
        assert not any(row["operation"] in {"cancel", "cancel_run_operation", "submit"} for row in requests)


@pytest.mark.parametrize("delay_at", ["operation", "wait_operation"])
def test_run_observation_deadline_bounds_reads_and_detaches_with_reference(tmp_path, delay_at):
    operation = {"operation_id": "original", "kind": "run", "state": "pending", "code": None,
                 "result": {"coordinator_id": "coordinator-a", "queue_item_id": "original-queue", "admission": None}}
    def respond(connection, request):
        if request["operation"] == delay_at:
            # A peer which remains connected without completing its reply must
            # not gain a new transport budget after every observation call.
            time.sleep(0.3)
        result = operation if request["operation"] == "operation" else {"kind": "TIMEOUT", "operation": operation}
        connection.sendall(encode_wire({"ok": True, "result": result}) + b"\n")
    with _peer(tmp_path / "service.sock", respond) as requests:
        client = CoordinatorClient.from_unix_socket(tmp_path / "service.sock")
        started = time.monotonic()
        observed = client.observe_run("original", timeout_seconds=0.08)
        elapsed = time.monotonic() - started
        assert elapsed < 0.25
        assert observed.operation_id == "original"
        assert observed.connection.coordinator_id == "coordinator-a"
        assert (observed.operation is None) is (delay_at == "operation")
        assert not any(row["operation"] in {"cancel", "cancel_run_operation"} for row in requests)


@pytest.mark.parametrize("operation", [
    "operator_retire", "operator_scheduling_reload", "operator_recover_unknown",
    "operator_recover_time", "operator_replace_agent_session", "operator_reconcile",
])
def test_operator_administration_is_guarded_and_retains_unknown_outcomes(tmp_path, operation):
    from loom.queue import (
        CoordinatorSchedulingReload, ManagedRecoveryTarget, RecoverUnknownAssignment,
        SessionReplacementRequest, TimeRecoveryRequest,
    )

    def invoke(client):
        if operation == "operator_retire":
            return client.retire("retire-1")
        if operation == "operator_scheduling_reload":
            return client.reload_scheduling(CoordinatorSchedulingReload("reload-1", "epoch-1", "reload"))
        if operation == "operator_recover_time":
            return client.recover_time(TimeRecoveryRequest("time-1", 1, "epoch-1", "clock recovered"))
        if operation == "operator_replace_agent_session":
            return client.replace_agent_session(SessionReplacementRequest("replace-1", "agent-a", "contained"))
        if operation == "operator_reconcile":
            return client.reconcile_once()
        return client.recover_unknown(RecoverUnknownAssignment(
            recovery_id="recovery-1", run_uri="file:///runs/run", stage_name="train",
            attempt=1, stage_work_id="work-1", assignment_id="assignment-1",
            process_execution_id="process-1", execution_fence="fence-1",
            target=ManagedRecoveryTarget("agent-a", "session-a"),
            expected_state_version=1, requested_outcome="failed", consider_retry=True,
            reason="verified containment",
        ))

    endpoint = tmp_path / "operator.sock"
    # A lost reply follows dispatch. No operation is automatically repeated.
    with _peer(endpoint, lambda connection, request: None) as requests:
        with CoordinatorOperatorClient.from_unix_socket(endpoint) as unbound:
            with pytest.raises(CoordinatorClientError) as missing:
                invoke(unbound)
        assert missing.value.code == "invalid_request"
        assert missing.value.mutation_outcome == "not_applied"
        assert requests == []
        with CoordinatorOperatorClient.from_unix_socket(endpoint, expected_coordinator_id="coordinator-a") as bound:
            with pytest.raises(CoordinatorClientError) as lost:
                invoke(bound)
        assert lost.value.mutation_outcome == "unknown"
        assert lost.value.operation == operation
        assert lost.value.ids["expected_coordinator_id"] == "coordinator-a"
        assert [request["operation"] for request in requests] == ["operator_handshake", operation]
        assert all(request["daemon_control"] == CONTROL_CAPABILITY for request in requests)


def test_operator_recovery_and_readiness_decode_current_typed_results(tmp_path):
    from loom.queue import TimeRecoveryRequest, TimeRecoveryReceipt

    receipt = TimeRecoveryReceipt("time-1", "digest-1", "2026-10-16T00:00:00Z", "old-epoch", "new-epoch", 2)
    responses = {"operator_recover_time": receipt.to_dict(), "operator_agent_retirement_ready": {"ready": True}}
    endpoint = tmp_path / "operator.sock"
    with _peer(endpoint, lambda connection, request: connection.sendall(
        encode_wire({"ok": True, "result": responses[str(request["operation"])]}) + b"\n"
    )):
        with CoordinatorOperatorClient.from_unix_socket(endpoint, expected_coordinator_id="coordinator-a") as client:
            assert client.recover_time(TimeRecoveryRequest("time-1", 1, "old-epoch", "recovered")) == receipt
            assert client.agent_retirement_ready("agent-a", "session-a") is True


def test_recovery_cleanup_clients_preserve_selection_and_coordinator_guard(tmp_path):
    def respond(connection, request):
        from loom.queue._coordinator_control import validate_request
        operation = str(request["operation"])
        payload = {k: v for k, v in request.items() if k not in {"operation", "daemon_control"}}
        validate_request(operation, payload)
        result = ({"run_uri": "run", "entries": []} if operation == "preview_recovery_cleanup"
                  else {"run_uri": "run", "assignment_id": "assignment-1", "state": "deleted"})
        connection.sendall(encode_wire({"ok": True, "result": result}) + b"\n")

    with _peer(tmp_path / "service.sock", respond) as requests:
        client = CoordinatorClient.from_unix_socket(tmp_path / "service.sock")
        assert client.preview_recovery_cleanup("run") == {"run_uri": "run", "entries": []}
        operator = CoordinatorOperatorClient.from_unix_socket(tmp_path / "service.sock")
        result = operator.release_recovery("run", "assignment-1", operation_id="release-1",
                                           reason="published", expected_coordinator_id="coordinator-a")
        assert result["state"] == "deleted"
    released = next(row for row in requests if row["operation"] == "operator_release_recovery")
    assert released["expected_coordinator_id"] == "coordinator-a"
    assert released["assignment_id"] == "assignment-1"
    assert released["operation_id"] == "release-1"
