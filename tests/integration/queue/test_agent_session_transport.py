"""TLS authentication, request limits, and native HTTP protocol tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import socket
import ssl
import sqlite3
from collections.abc import Mapping
from threading import Event
from time import monotonic, sleep
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError
import loom.queue.agent_session_transport as agent_session_transport
from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionResult,
    RunInspectionStage,
    RunInspectionTruncation,
    decode_run_inspection_response,
)
from loom.pipeline.stores import (
    LocalRunStore,
)
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    RunInspectionHttpClient,
    RunInspectionTlsClientConfig,
)
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueServiceError
from loom.serialization import PlainData
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.agent_sessions import (
    _shutdown_detached_remote_supervisors as _shutdown_detached_remote_supervisors,
    _failure_report,
    _local_launch_profile,
    _nested_report_detail,
    _policy,
    _prepare_remote_producer_run,
    _remote_agent_root,
    _request,
    _slurm_bootstrap_profile,
    native_control_endpoint as native_control_endpoint,
)


def test_repeated_pending_slurm_connections_retire_request_threads(tmp_path, monkeypatch):
    """Transport lifetime coverage; real storage ownership is tested separately."""
    from http.client import HTTPSConnection
    from threading import Condition
    from loom.queue.agent_sessions import AgentSessionService
    from loom.queue.agent_session_transport import _Handler

    credentials = _credentials(tmp_path / 'tls')
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / 'coordinator', agent_root=None,
        run_store_root=tmp_path / 'runs', resident_worker_launch_profile=None,
        cpu_capacity=0, agent_policy=_policy(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        'localhost', 0, credentials['server'].with_suffix('.crt'),
        credentials['server'].with_suffix('.key'), credentials['ca'].with_suffix('.crt'),
        {_fingerprint(credentials['agent'].with_suffix('.crt')): 'agent-credential'},
    ))
    condition = Condition()
    active = completed = 0
    original = _Handler.handle

    def tracked(handler):
        nonlocal active, completed
        with condition:
            active += 1
        try:
            return original(handler)
        finally:
            with condition:
                active -= 1
                completed += 1
                condition.notify_all()

    monkeypatch.setattr(_Handler, 'handle', tracked)
    monkeypatch.setattr(AgentSessionService, 'slurm_work', lambda *args, **kwargs: {
        'assignment_id': 'A', 'sequence': 1, 'disposition': 'pending',
        'reason': 'recovery_retention', 'retry_after_seconds': 5,
    })
    server.start()
    context = ssl.create_default_context(cafile=str(credentials['ca'].with_suffix('.crt')))
    context.load_cert_chain(credentials['agent'].with_suffix('.crt'), credentials['agent'].with_suffix('.key'))
    try:
        for number in range(40):
            connection = HTTPSConnection('localhost', server.port, context=context, timeout=5)
            try:
                connection.request('POST', '/v1/agent/slurm_work', body=json.dumps({
                    'session_id': 'session', 'coordinator_epoch': 'epoch',
                    'evidence': None, 'cursor': None,
                }), headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                body = json.loads(response.read())
                assert response.status == 200, body
                assert body['result']['disposition'] == 'pending'
            finally:
                connection.close()
            with condition:
                assert condition.wait_for(lambda: completed == number + 1, timeout=5)
                assert active == 0
    finally:
        server.stop()
        daemon.stop()


def test_loopback_rejects_unmapped_client_certificate_and_wrong_service_ca(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential"
            },
        ),
    )
    server.start()
    rejected = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    wrong_ca = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["server"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    wrong_service = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://127.0.0.1:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            rejected.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_ca.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_service.handshake()
    finally:
        rejected.close()
        wrong_ca.close()
        wrong_service.close()
        server.stop()
        daemon.stop()


def test_loopback_operator_scope_denial_matches_direct_before_persistence(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator-principal",
                "operator",
                actions=("drain",),
                agent_ids=("another-agent",),
                pools=("default",),
            ),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(credentials["agent"].with_suffix(".crt")): (
                    "agent-credential"
                ),
                _fingerprint(credentials["other"].with_suffix(".crt")): (
                    "operator-credential"
                ),
            },
        ),
    )
    server.start()
    agent = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            _remote_agent_root(tmp_path),
        )
    )
    from loom.coordinator import CoordinatorOperatorClient
    from loom.queue._coordinator_transport import HttpsControlTransport

    operator = CoordinatorOperatorClient(
        HttpsControlTransport(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
            role="operator",
        ),
        expected_coordinator_id=daemon.status().coordinator_id,
    )
    try:
        handshake = agent.handshake()
        session = agent.register(_request(handshake, agent.agent_root_id))
        control = AgentControl(
            operation_id="denied-control",
            kind=AgentControlKind.DRAIN,
            agent_id=session.agent_id,
            expected_session_id=session.session_id,
            expected_config_revision=session.config_revision,
            pool="default",
            cancel_active=False,
            reason="outside exact agent scope",
        )
        direct = daemon.operator_view(
            LocalDaemonPrincipal(
                "operator-principal",
                LocalDaemonRole.OPERATOR,
                "operator-credential",
            )
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            direct.control_agent(control)
        operator.describe_connection()
        with pytest.raises(CoordinatorClientError) as denied:
            operator.control_agent(control)
        assert denied.value.code == "unauthorized"
        assert denied.value.mutation_outcome == "not_applied"
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_controls").fetchone()[0] == 0
            )
    finally:
        agent.close()
        operator.close()
        server.stop()
        daemon.stop()


def test_native_https_wait_saturation_keeps_client_and_worker_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Lock

    credentials = _credentials(tmp_path / "tls")
    store = LocalRunStore(tmp_path / "runs")
    run_uri, _authority = _prepare_remote_producer_run(
        store,
        run_name="wait-capacity",
        machine_id="agent-a",
        value=1,
    )
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        store.root,
        None,
        cpu_capacity=0,
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "client-credential",
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential",
            },
        ),
    )
    server.start()
    connection_path = tmp_path / "client.yaml"
    connection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.coordinator-client",
                "transport": {
                    "kind": "https",
                    "url": f"https://localhost:{server.port}",
                    "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                    "certificate_path": str(credentials["other"].with_suffix(".crt")),
                    "private_key_path": str(credentials["other"].with_suffix(".key")),
                },
            }
        )
    )
    connection_path.chmod(0o600)
    client = CoordinatorClient.from_connection_file(connection_path)
    worker = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    admitted = client.submit(LocalDaemonAdmissionRequest("waiting-item", run_uri))
    original = daemon.wait_admission
    entered = Event()
    release = Event()
    lock = Lock()
    active = maximum = 0

    def paused(admission_id: str, *, expected_revision: int, timeout: float | None):  # type: ignore[no-untyped-def]
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 6:
                entered.set()
        try:
            assert release.wait(10), (
                "ordinary control failed to release the observation fixture"
            )
            return original(
                admission_id, expected_revision=expected_revision, timeout=0
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(daemon, "wait_admission", paused)
    observers = [
        CoordinatorClient.from_connection_file(connection_path) for _ in range(8)
    ]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(
                    observer.wait_admission,
                    admitted.admission_id,
                    admitted.revision,
                    0.5,
                )
                for observer in observers
            ]
            try:
                assert entered.wait(8), [
                    repr(future.exception()) for future in futures if future.done()
                ]
                assert client.status().coordinator_id == daemon._coordinator_id
                assert worker.handshake()["coordinator_id"] == daemon._coordinator_id
                cancelled = client.cancel("waiting-item")
                assert cancelled.cancellation_operation_id is not None
                assert maximum == 6
            finally:
                release.set()
            for future in futures:
                assert (
                    future.result(timeout=10).admission.queue_item_id == "waiting-item"
                )
    finally:
        release.set()
        for observer in observers:
            observer.close()
        client.close()
        worker.close()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("location", ["headers", "body"])
def test_native_https_trickle_consumes_one_http_call_budget(
    native_control_endpoint,
    monkeypatch: pytest.MonkeyPatch,
    location: str,  # type: ignore[no-untyped-def]
) -> None:
    from loom.queue import _coordinator_transport as control_io

    _daemon, _server, connection_path, _credentials = native_control_endpoint
    monkeypatch.setattr(control_io, "HTTP_CALL_SECONDS", 0.5)
    monkeypatch.setattr(control_io, "REQUEST_BUDGET_SECONDS", 3.0)
    original = agent_session_transport._Handler._reply
    finished = Event()
    stop = Event()

    def trickle(
        handler: agent_session_transport._Handler,
        status: int,
        payload: Mapping[str, object],
    ) -> None:
        if status != 200 or handler.path != "/v1/client/status":
            original(handler, status, payload)
            return
        handler.close_connection = True
        try:
            if location == "headers":
                handler.wfile.write(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
            else:
                handler.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
            for _ in range(100):
                handler.wfile.write(b"x")
                if stop.wait(0.04):
                    break
        except OSError:
            pass  # The client closes its socket when the cumulative budget expires.
        finally:
            finished.set()

    monkeypatch.setattr(agent_session_transport._Handler, "_reply", trickle)
    started = monotonic()
    try:
        with CoordinatorClient.from_connection_file(connection_path) as client:
            with pytest.raises(CoordinatorClientError) as caught:
                client.status()
        assert caught.value.code == "deadline_exceeded"
        assert caught.value.mutation_outcome is None
        assert (
            monotonic() - started < 1.5
        )  # Separate HTTP cap, below the 3-second overall budget.
    finally:
        stop.set()
        assert finished.wait(2)


@pytest.mark.parametrize("connection_kind", ["unix", "https"])
def test_coordinator_cli_submit_inspect_cancel_and_wait_with_either_connection(
    native_control_endpoint,
    connection_kind: str,  # type: ignore[no-untyped-def]
) -> None:
    import io

    from loom.cli.main import main
    from loom.queue import LocalDaemonSocketServer

    daemon, _http_server, connection_path, _credentials = native_control_endpoint
    run_uri, _authority = _prepare_remote_producer_run(
        LocalRunStore(daemon.config.run_store_root),
        run_name="cli-workflow",
        machine_id="agent-a",
        value=3,
    )
    socket_server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    socket_server.start()
    options = (
        ["--endpoint", str(daemon.config.endpoint)]
        if connection_kind == "unix"
        else ["--connection", str(connection_path)]
    )

    def cli(command: str, *arguments: str) -> Mapping[str, Any]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = main(
            [
                "queue",
                command,
                *options,
                "--expected-coordinator-id",
                daemon._coordinator_id,
                *arguments,
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        assert code == 0, stderr.getvalue()
        return json.loads(stdout.getvalue())["result"]

    try:
        admission = cli("daemon-submit", "cli-item", run_uri)
        assert cli("daemon-status")["coordinator_id"] == daemon._coordinator_id
        assert cli("daemon-admissions")["admissions"][0]["queue_item_id"] == "cli-item"
        assert (
            cli("daemon-admission", admission["admission_id"])["admission"]["run_uri"]
            == run_uri
        )
        assert cli("daemon-agents")["agents"] == []
        cancellation = cli("daemon-cancel", "cli-item")
        assert cancellation["cancellation_operation_id"] is not None
        terminal = cli("daemon-wait", "cli-item", "--timeout", "5")
        assert terminal["admission_id"] == admission["admission_id"]
        assert terminal["state"] in {"CANCELLED", "BLOCKED"}
    finally:
        socket_server.stop()


def test_native_client_bounds_stalled_setup_and_does_not_dispatch_after_expiry(
    native_control_endpoint,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from threading import Lock
    from loom.queue import _coordinator_transport as control_io

    daemon, _server, connection_path, _credentials = native_control_endpoint
    client = CoordinatorClient.from_connection_file(connection_path)
    # Smaller private counts make the causal capacity test fast. Stalled work
    # must retain a slot even after its original caller has timed out.
    client._transport._capacity = control_io.ControlCapacity(total=2, waits=1)
    monkeypatch.setattr(control_io, "REQUEST_BUDGET_SECONDS", 0.5)
    original = control_io.https_connection
    entered = Event()
    release = Event()
    lock = Lock()
    started = 0

    def delayed(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal started
        with lock:
            started += 1
            if started == 2:
                entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(control_io, "https_connection", delayed)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(client.cancel, f"original-{index}")
                for index in range(2)
            ]
            assert entered.wait(2)
            for index, future in enumerate(futures):
                with pytest.raises(CoordinatorClientError) as caught:
                    future.result(timeout=2)
                assert caught.value.code == "deadline_exceeded"
                assert caught.value.mutation_outcome == "not_applied"
                assert caught.value.ids["queue_item_id"] == f"original-{index}"
            with pytest.raises(CoordinatorClientError) as saturated:
                client.status()
            assert saturated.value.code == "capacity_exhausted"
            assert started == 2
            pending = tuple(client._transport._active)
            release.set()
            assert all(exchange.completed.wait(2) for exchange in pending)
        assert daemon.admissions().admissions == ()
    finally:
        release.set()
        client.close()


def test_native_submit_error_after_commit_does_not_claim_refusal(
    native_control_endpoint,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from loom.queue.errors import QueueStorageError

    daemon, _server, connection_path, _credentials = native_control_endpoint
    run_uri, _authority = _prepare_remote_producer_run(
        LocalRunStore(daemon.config.run_store_root),
        run_name="post-commit-read-fault",
        machine_id="agent-a",
        value=9,
    )
    submit = daemon._submit

    def failed_receipt(request: LocalDaemonAdmissionRequest, *, direct_principal: str):
        submit(request, direct_principal=direct_principal)
        raise QueueStorageError("post-commit admission receipt read failed")

    monkeypatch.setattr(daemon, "_submit", failed_receipt)
    with CoordinatorClient.from_connection_file(connection_path) as client:
        with pytest.raises(CoordinatorClientError) as caught:
            client.submit(LocalDaemonAdmissionRequest("same-item", run_uri))
        assert caught.value.code == "unavailable"
        assert caught.value.mutation_outcome == "unknown"
        assert caught.value.ids["queue_item_id"] == "same-item"
        assert client.admission_for_queue_item("same-item").run_uri == run_uri
        assert len(daemon.admissions().admissions) == 1


def test_native_admission_preserves_nested_failures_and_refuses_oversized_projection(
    native_control_endpoint,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from loom.queue._coordinator_control import MAX_RESPONSE_BYTES

    daemon, _server, connection_path, _credentials = native_control_endpoint
    run_uri, _authority = _prepare_remote_producer_run(
        LocalRunStore(daemon.config.run_store_root),
        run_name="failure-projection",
        machine_id="agent-a",
        value=2,
    )
    failure = _failure_report({"worker_detail": _nested_report_detail(50)}).failure
    assert failure is not None
    owner: dict[str, PlainData] = {
        "availability": "available",
        "failures": [failure.to_dict()],
    }
    inspect_admission = daemon.admission

    def projection(admission_id: str):  # type: ignore[no-untyped-def]
        observed = inspect_admission(admission_id)
        return replace(observed, owners={**observed.owners, "run_result": owner})

    monkeypatch.setattr(daemon, "admission", projection)
    with CoordinatorClient.from_connection_file(connection_path) as client:
        admitted = client.submit(LocalDaemonAdmissionRequest("failure-item", run_uri))
        decoded = client.admission(admitted.admission_id)
        assert (
            cast(Mapping[str, object], decoded.to_dict()["owners"])["run_result"]
            == owner
        )
        owner["extra_evidence"] = "x" * MAX_RESPONSE_BYTES
        with pytest.raises(CoordinatorClientError) as caught:
            client.admission(admitted.admission_id)
        assert caught.value.code == "result_too_large"
        assert caught.value.mutation_outcome is None
        assert caught.value.ids["admission_id"] == admitted.admission_id


@pytest.mark.parametrize("rejection", ["wrong_ca", "worker_role"])
def test_native_https_authentication_rejects_before_mutation(
    native_control_endpoint,
    rejection: str,  # type: ignore[no-untyped-def]
) -> None:
    daemon, _server, connection_path, credentials = native_control_endpoint
    settings = json.loads(connection_path.read_text())
    if rejection == "wrong_ca":
        settings["transport"]["server_ca_path"] = str(
            credentials["agent"].with_suffix(".crt")
        )
    else:
        settings["transport"]["certificate_path"] = str(
            credentials["agent"].with_suffix(".crt")
        )
        settings["transport"]["private_key_path"] = str(
            credentials["agent"].with_suffix(".key")
        )
    connection_path.write_text(json.dumps(settings))
    with CoordinatorClient.from_connection_file(connection_path) as client:
        with pytest.raises(CoordinatorClientError) as caught:
            client.cancel("original-item")
    assert caught.value.code == "unauthorized"
    assert caught.value.boundary == "authentication"
    assert caught.value.mutation_outcome == "not_applied"
    assert caught.value.ids["queue_item_id"] == "original-item"
    assert daemon.admissions().admissions == ()


def test_independent_authenticated_client_completes_while_negotiation_is_paused(native_control_endpoint, monkeypatch):
    daemon, server, _, credentials = native_control_endpoint
    entered, release = Event(), Event()
    handshake = ssl.SSLSocket.do_handshake

    def pause_first(sock, *args, **kwargs):
        if sock.server_side and not entered.is_set():
            entered.set()
            assert release.wait(8)
        return handshake(sock, *args, **kwargs)

    monkeypatch.setattr(ssl.SSLSocket, "do_handshake", pause_first)
    config = AgentTlsClientConfig(
        f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key"),
    )

    def observed():
        client = LocalDaemonAgentHttpClient(config)
        try:
            return client.handshake()["coordinator_id"]
        finally:
            client.close()

    with ThreadPoolExecutor() as callers:
        first = callers.submit(observed)
        try:
            assert entered.wait(3)
            assert callers.submit(observed).result(3) == daemon._coordinator_id
            assert not first.done()
        finally:
            release.set()
        assert first.result(3) == daemon._coordinator_id


def test_handshake_capacity_and_shutdown_own_queued_sockets(native_control_endpoint, monkeypatch):
    _, listener, _, _ = native_control_endpoint
    server = listener._server
    release, closing = Event(), Event()
    authenticate = server._authenticate_connection
    shutdown = server._handshakes.shutdown

    def held(*args):
        assert release.wait(8)
        authenticate(*args)

    def shutting_down(*args, **kwargs):
        closing.set()
        return shutdown(*args, **kwargs)

    monkeypatch.setattr(server, "_authenticate_connection", held)
    monkeypatch.setattr(server._handshakes, "shutdown", shutting_down)
    pairs = [socket.socketpair() for _ in range(9)]
    try:
        for connection, _ in pairs:
            server.process_request(connection, ("localhost", 0))
        assert len(server._negotiating) == 8
        assert pairs[-1][0].fileno() == -1
        with ThreadPoolExecutor() as callers:
            stopped = callers.submit(listener.stop)
            try:
                assert closing.wait(3)
                assert all(connection.fileno() == -1 for connection, _ in pairs)
            finally:
                release.set()
            stopped.result(3)
        assert not server._negotiating
    finally:
        release.set()
        for connection, peer in pairs:
            connection.close()
            peer.close()


def test_worker_keepalive_remains_usable_after_the_tls_accept_deadline(
    native_control_endpoint,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    daemon, server, _connection_path, credentials = native_control_endpoint
    monkeypatch.setattr(agent_session_transport, "_HTTP_TIMEOUT_SECONDS", 1.0)
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        assert client.handshake()["coordinator_id"] == daemon._coordinator_id
        sleep(1.2)
        assert client.handshake()["coordinator_id"] == daemon._coordinator_id
    finally:
        client.close()


def test_loopback_exposes_client_and_operator_views_only_to_configured_roles(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential",
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "client-credential",
            },
        ),
    )
    server.start()
    from loom.coordinator import CoordinatorOperatorClient

    connection_path = tmp_path / "coordinator-client.json"
    settings = {
        "schema_version": 1,
        "kind": "loom.coordinator-client",
        "transport": {
            "kind": "https",
            "url": f"https://localhost:{server.port}",
            "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
            "certificate_path": str(credentials["other"].with_suffix(".crt")),
            "private_key_path": str(credentials["other"].with_suffix(".key")),
        },
        "expected_coordinator_id": daemon._coordinator_id,
    }
    connection_path.write_text(json.dumps(settings))
    connection_path.chmod(0o600)
    facade = CoordinatorClient.from_connection_file(connection_path)
    operator = CoordinatorOperatorClient.from_connection_file(connection_path)
    try:
        handshake = facade.describe_connection()
        assert handshake.transport == "https"
        assert handshake.capabilities == (
            "authenticated-application-v1", "daemon-control-v1", "agent-offer-capacity-v1", "queue-list-v1",
            "operator-observations-v1", "conditional-agent-control-v1",
            "quiescent-profile-promotion-v2", "quiescent-source-promotion-v1",
            "quiescent-configuration-retirement-v1", "quiescent-coordinator-retirement-v1",
            "quiescent-container-policy-addition-v1", "quiescent-publication-budget-increase-v1",
            "quiescent-agent-gpu-policy-contraction-v1", "quiescent-agent-gpu-policy-expansion-v1",
            "maintenance-admission-v1", "maintenance-submitted-check-v1", "run-context-v1", "run-query-v1",
            "output-query-v1", "lineage-query-v1", "artifact-read-v1",
            "bounded-run-logs-v1",
        )
        remote_status = facade.status()
        direct_status = daemon.client_view(LocalDaemonPrincipal(
            "client-principal", LocalDaemonRole.CLIENT, "client-credential"
        )).status()
        assert remote_status.coordinator_id == direct_status.coordinator_id
        assert remote_status.coordinator_epoch == direct_status.coordinator_epoch
        assert remote_status.active_admissions == direct_status.active_admissions == 0
        assert remote_status.waiting_admissions == direct_status.waiting_admissions == 0
        with pytest.raises(CoordinatorClientError, match="conflict"):
            CoordinatorClient.from_connection_file(connection_path, expected_coordinator_id="different-coordinator")
        with pytest.raises(CoordinatorClientError) as client_role:
            operator.observe_status()
        assert client_role.value.code == "unauthorized"

        daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2", agents=policy.agents))
        with pytest.raises(CoordinatorClientError) as revoked:
            facade.status()
        assert revoked.value.code == "unauthorized"
        assert revoked.value.boundary == "authentication"
        assert revoked.value.mutation_outcome is None
        daemon.replace_agent_policy(AgentPolicyConfig(
            revision="policy-3", agents=policy.agents,
            principals=(TransportPrincipalPolicy("client-credential", "operator-principal", "operator"),),
        ))
        assert operator.describe_connection().coordinator_id == daemon._coordinator_id
        with pytest.raises(CoordinatorClientError) as wrong_role:
            facade.cancel("never-admitted")
        assert wrong_role.value.code == "unauthorized"
        assert wrong_role.value.mutation_outcome == "not_applied"
        remote_operator = operator.observe_status()
        direct_operator = daemon.operator_view(LocalDaemonPrincipal(
            "operator-principal", LocalDaemonRole.OPERATOR, "client-credential"
        )).observe_status()
        assert remote_operator.owner == direct_operator.owner
        assert {k: v for k, v in remote_operator.value.items() if k != "as_of"} == {
            k: v for k, v in direct_operator.value.items() if k != "as_of"
        }
        assert operator.reconcile_once() == ()

        settings["transport"]["certificate_path"] = str(credentials["agent"].with_suffix(".crt"))
        settings["transport"]["private_key_path"] = str(credentials["agent"].with_suffix(".key"))
        connection_path.write_text(json.dumps(settings))
        with CoordinatorClient.from_connection_file(connection_path) as wrong_agent:
            with pytest.raises(CoordinatorClientError) as denied:
                wrong_agent.cancel("never-admitted")
        assert denied.value.code == "unauthorized"
        assert denied.value.mutation_outcome == "not_applied"
        assert daemon.admissions().admissions == ()
    finally:
        facade.close()
        operator.close()
        server.stop()
        daemon.stop()


def test_loopback_query_role_is_read_only_current_policy_and_capability_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        principals=(
            TransportPrincipalPolicy("query-credential", "query-principal", "query"),
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
            TransportPrincipalPolicy(
                "operator-credential", "operator-principal", "operator"
            ),
        )
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    inspected: list[str] = []
    admission_reads: list[str] = []
    owner_view_calls: list[str] = []

    def admission_for_run_uri(run_uri: str) -> object:
        admission_reads.append(run_uri)
        if run_uri != "file:///runs/known":
            raise LookupError("run is not admitted")
        return object()

    def forbidden_view(name: str) -> Any:
        def open_view(*_args: object, **_kwargs: object) -> object:
            owner_view_calls.append(name)
            raise AssertionError(f"{name} view was reached")

        return open_view

    monkeypatch.setattr(daemon, "admission_for_run_uri", admission_for_run_uri)
    for view_name in (
        "client_view",
        "operator_view",
        "agent_view",
        "slurm_bootstrap_view",
    ):
        monkeypatch.setattr(daemon, view_name, forbidden_view(view_name))
    server_config = AgentTlsServerConfig(
        "localhost",
        0,
        credentials["server"].with_suffix(".crt"),
        credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"),
        {
            _fingerprint(credentials["query"].with_suffix(".crt")): "query-credential",
            _fingerprint(credentials["other"].with_suffix(".crt")): "client-credential",
            _fingerprint(
                credentials["agent"].with_suffix(".crt")
            ): "operator-credential",
        },
    )
    server = LocalDaemonAgentHttpServer(
        daemon,
        server_config,
        inspect_run=lambda run_uri: (
            inspected.append(run_uri) or {"schema_version": 1, "code": "not_found"}
        ),
    )
    server.start()
    query = RunInspectionHttpClient(
        RunInspectionTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["query"].with_suffix(".crt"),
            credentials["query"].with_suffix(".key"),
        )
    )
    mutation_client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["query"].with_suffix(".crt"),
            credentials["query"].with_suffix(".key"),
        )
    )
    wrong_role = RunInspectionHttpClient(
        RunInspectionTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    wrong_operator_role = RunInspectionHttpClient(
        RunInspectionTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    legacy_server = LocalDaemonAgentHttpServer(daemon, server_config)
    legacy_server.start()
    legacy = RunInspectionHttpClient(
        RunInspectionTlsClientConfig(
            f"https://localhost:{legacy_server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["query"].with_suffix(".crt"),
            credentials["query"].with_suffix(".key"),
        )
    )
    try:
        assert query.inspect_run("file:///runs/known") == {
            "schema_version": 1,
            "code": "not_found",
        }
        assert inspected == ["file:///runs/known"]
        assert admission_reads == ["file:///runs/known"]

        assert query.inspect_run("not-a-run-uri") == {
            "schema_version": 1,
            "code": "invalid_request",
        }
        assert query.inspect_run("file:///runs/\ud800") == {
            "schema_version": 1,
            "code": "invalid_request",
        }
        assert query.inspect_run("file:///runs/unadmitted") == {
            "schema_version": 1,
            "code": "not_found",
        }
        assert inspected == ["file:///runs/known"]
        assert admission_reads == ["file:///runs/known", "file:///runs/unadmitted"]

        with pytest.raises(QueueServiceError, match="agent protocol request failed"):
            mutation_client._call(  # noqa: SLF001 - trust-boundary negative.
                "inspect_run",
                {"run_uri": "file:///runs/known", "principal": "spoofed"},
                role="query",
            )
        for role, operation, value in (
            ("client", "submit", {"request": {}}),
            ("client", "prepare_run", {"request": {}}),
            ("client", "cancel", {"queue_item_id": "item"}),
            ("operator", "scheduling_reload", {"request": {}}),
            ("slurm_bootstrap", "register", {}),
        ):
            with pytest.raises(
                QueueServiceError, match="agent protocol request failed"
            ):
                mutation_client._call(operation, value, role=role)
        # The generic application client excludes QUERY roles locally; exercise
        # the actual authenticated read-only server boundary with its envelope.
        with pytest.raises(QueueServiceError, match="agent protocol request failed"):
            mutation_client._call("prepare_run", {"request": {}}, role="query")
        with pytest.raises(QueueServiceError, match="agent protocol request failed"):
            mutation_client.handshake(role="agent")
        assert owner_view_calls == []

        for client in (wrong_role, wrong_operator_role):
            assert client.inspect_run("file:///runs/known") == {
                "schema_version": 1,
                "code": "unauthorized",
            }
        assert inspected == ["file:///runs/known"]
        assert legacy.inspect_run("file:///runs/known") == {
            "schema_version": 1,
            "code": "unavailable",
        }
        assert admission_reads == ["file:///runs/known", "file:///runs/unadmitted"]

        normal_decode = agent_session_transport._decode

        def reject_handshake_response(raw: bytes) -> Mapping[str, object]:
            if raw == b"{}":
                return normal_decode(raw)
            raise QueueServiceError("malformed handshake response")

        with monkeypatch.context() as context:
            context.setattr(
                agent_session_transport, "_decode", reject_handshake_response
            )
            assert query.inspect_run("file:///runs/known") == {
                "schema_version": 1,
                "code": "unavailable",
            }
        assert inspected == ["file:///runs/known"]

        context = query.get_run_context("file:///runs/known")
        assert context["run_uri"] == "file:///runs/known"
        assert context["annotations"] is None
        assert "authority_unavailable" in cast(list[str], context["unavailable"])
        assert owner_view_calls == []
        assert inspected == ["file:///runs/known", "file:///runs/known"]

        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-2",
                principals=(
                    TransportPrincipalPolicy(
                        "client-credential", "client-principal", "client"
                    ),
                ),
            )
        )
        assert query.inspect_run("file:///runs/revoked") == {
            "schema_version": 1,
            "code": "unauthorized",
        }
        assert query.get_run_context("file:///runs/revoked")["code"] == "unauthorized"
        assert inspected == ["file:///runs/known", "file:///runs/known"]
        assert owner_view_calls == []
    finally:
        mutation_client.close()
        legacy_server.stop()
        server.stop()
        daemon.stop()


def test_loopback_query_preserves_a_256_record_phase_one_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        principals=(
            TransportPrincipalPolicy("query-credential", "query-principal", "query"),
        )
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    result = RunInspectionResult(
        run_uri="file:///runs/known",
        as_of="2026-08-30T00:00:00Z",
        summary="RUNNING",
        queue_item_id="queue-known",
        admission_id="admission-known",
        axes=tuple(
            RunInspectionAxis(
                name,
                "test",
                "available",
                "RUNNING",
                1,
                "2026-08-30T00:00:00Z",
                "current",
            )
            for name in RunInspectionAxisName
        ),
        stages=tuple(
            RunInspectionStage(f"stage-{index}", "RUNNING", 1) for index in range(256)
        ),
        locations=(),
        truncation=(
            RunInspectionTruncation("stages", 256, 256),
            RunInspectionTruncation("locations", 0, 0),
        ),
    )
    monkeypatch.setattr(daemon, "admission_for_run_uri", lambda _uri: object())
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["query"].with_suffix(".crt")
                ): "query-credential",
            },
        ),
        inspect_run=lambda _run_uri: result.to_dict(),
    )
    server.start()
    client = RunInspectionHttpClient(
        RunInspectionTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["query"].with_suffix(".crt"),
            credentials["query"].with_suffix(".key"),
        )
    )
    try:
        remote = client.inspect_run(result.run_uri)
    finally:
        server.stop()
        daemon.stop()

    assert decode_run_inspection_response(remote) == result


def test_loopback_maps_slurm_certificate_only_to_fixed_bootstrap_role(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    profile = _slurm_bootstrap_profile(tmp_path)
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "slurm-credential"
            },
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    try:
        handshake = client.handshake(role="slurm_bootstrap")
        assert handshake["role"] == "slurm_bootstrap"
        assert handshake["profile_id"] == "training"
        assert handshake["credential_policy_revision"] == "slurm-policy-1"
        capabilities = handshake["capabilities"]
        assert isinstance(capabilities, (list, tuple))
        assert "slurm-ready-stage-bootstrap-v1" in capabilities
        with pytest.raises(QueueServiceError, match="role-exclusive"):
            daemon.replace_agent_policy(
                AgentPolicyConfig(
                    agents=(
                        AgentPrincipalPolicy(
                            "slurm-credential",
                            "agent-principal",
                            "agent-a",
                            ("default",),
                            ("python",),
                        ),
                    )
                )
            )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client._call("handshake", {}, role="client")
    finally:
        client.close()
        server.stop()
        daemon.stop()
