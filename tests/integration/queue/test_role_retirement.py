"""Native retirement proofs precede downstream removal; no fixture data erased."""

from contextlib import contextmanager
import json
import sqlite3
from threading import Event, Thread
import time

import pytest

from loom.coordinator import RunRequest
from loom.preparation import CoordinatorPreparation
from loom.serialization import thaw_plain_data
from loom.queue import (
    AgentControl,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
)
from loom.queue.agent_session_transport import (
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import AgentControlKind, AgentRegistration
from loom.queue.deployment import (
    load_coordinator_service_config,
    load_outbound_agent_service_config,
    read_agent_spec,
    run_outbound_agent_service,
)
from loom.queue.errors import QueueError, QueueServiceError
from loom.queue.retirement import (
    retire_outbound_agent,
    retired_role_guard,
    retirement_receipt,
)
from tests.integration.queue.test_service_lifetime import (
    _mixed_selection,
    _request,
    _stop_fixture_supervisor,
)
from tests.integration.queue.test_agent_service_lifecycle import (
    remote_owner,
    remote_work,
)

remote_owner = remote_owner
remote_work = remote_work

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@contextmanager
def fleet(tmp_path):
    _mixed_selection(tmp_path, "persistent", "persistent")
    path = tmp_path / "coordinator.json"
    config = json.loads(path.read_text())
    config["agent_policy"]["local_owner"] = {
        "actions": ["scheduling_reload", "drain"],
        "agent_ids": ["worker"],
        "pools": ["default"],
    }
    path.write_text(json.dumps(config))
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    assert service.agent_server is not None
    http = LocalDaemonAgentHttpServer(daemon, service.agent_server)
    socket = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    http.start()
    socket.start()
    try:
        yield daemon, LocalDaemonSocketClient(service.daemon.endpoint)
    finally:
        socket.stop()
        http.stop()
        daemon.stop()


def test_coordinator_retirement_is_fenced_replayable_and_persistent(tmp_path):
    with fleet(tmp_path) as (daemon, client):
        identity = client.status().coordinator_id
        with pytest.raises(QueueError):
            client.retire("remove", "wrong-coordinator")
        assert retirement_receipt(daemon.config.coordinator_root) is None
        receipt = client.retire("remove", identity)
        assert client.retire("remove", identity) == receipt
        with pytest.raises(QueueError):
            client.retire("different-operation", identity)
        with pytest.raises(QueueError):
            client._client.start_run(RunRequest(_request(), "too-late"))
        root = daemon.config.coordinator_root
        with pytest.raises(QueueError):
            with retired_role_guard(root, receipt):
                pytest.fail("live coordinator must retain its ownership lock")
    with retired_role_guard(root, receipt):
        assert root.is_dir()
    with pytest.raises(QueueError, match="retired"):
        LocalDaemon(daemon.config).start()


def test_pending_work_prevents_retirement_without_fencing_acceptance(tmp_path):
    with fleet(tmp_path) as (daemon, client):
        daemon._lifetime.attach("startup", time.time() + 30)
        with pytest.raises(QueueError):
            client.retire("remove", client.status().coordinator_id)
        assert not daemon._lifetime.retiring
        assert retirement_receipt(daemon.config.coordinator_root) is None
        daemon._lifetime.release("startup")
        client.retire("remove", client.status().coordinator_id)


@pytest.mark.parametrize(
    "mode", ["service", "spec", "broken-workload", "lost-response", "legacy"]
)
def test_agent_clean_retirement_before_revoke_and_native_guard(
    tmp_path, monkeypatch, mode
):
    with fleet(tmp_path) as (daemon, operator):
        path = tmp_path / "agent.json"
        workload = tmp_path / "old-workload"
        if mode == "broken-workload":
            workload.mkdir()
            value = json.loads(path.read_text())
            value["resident_profiles"][0]["project_root"] = str(workload)
            path.write_text(json.dumps(value))
        service = load_outbound_agent_service_config(tmp_path / "agent.json")
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
        spec = read_agent_spec(path)
        retirement_config = service if mode == "service" else spec
        agent = LocalDaemonAgentHttpClient(service.client)
        try:
            handshake = agent.handshake()
            coordinator_id = handshake["coordinator_id"]
            coordinator_epoch = handshake["coordinator_epoch"]
            assert isinstance(coordinator_id, str)
            assert isinstance(coordinator_epoch, str)
            reg = service.registration
            session = agent.register(
                AgentRegistration(
                    "register",
                    coordinator_id,
                    coordinator_epoch,
                    agent.agent_root_id,
                    reg.config_revision,
                    reg.inventory_revision,
                    reg.availability_revision,
                    reg.pools,
                    reg.capabilities,
                )
            )
            args = dict(
                operation_id="remove-worker",
                expected_coordinator_id=session.coordinator_id,
                expected_session_id=session.session_id,
            )
            assert operator.agent_retirement_ready("worker", session.session_id)
            with pytest.raises(QueueError):
                retire_outbound_agent(retirement_config, **args)
            with pytest.raises(QueueError):
                operator.retire("remove-fleet", session.coordinator_id)
        finally:
            agent.close()
        root = spec.agent_root
        if mode == "legacy":
            with sqlite3.connect(root / "control.sqlite") as conn:
                conn.execute(
                    "DELETE FROM root_metadata WHERE key='declaration_binding'"
                )
        elif mode != "service":
            if mode == "broken-workload":
                workload.rmdir()
                with pytest.raises(QueueError):
                    load_outbound_agent_service_config(path)

            def forbidden(*_args, **_kwargs):
                pytest.fail(
                    "bound retirement requalified or started an old workload owner"
                )

            monkeypatch.setattr("loom.queue.deployment.qualify_agent_spec", forbidden)
            monkeypatch.setattr(
                "loom.queue._agent_process_supervisor._profile_from_value", forbidden
            )
            monkeypatch.setattr(
                "loom.queue.agent_session_transport.LocalDaemonAgentHttpClient",
                forbidden,
            )
        if mode == "lost-response":
            from loom.queue import agent_session_transport as transport

            original = transport._exchange_agent_request
            lost = True

            def exchange(*call_args, **kwargs):
                nonlocal lost
                result = original(*call_args, **kwargs)
                if call_args[1] == "retire" and lost:
                    lost = False
                    raise QueueServiceError(
                        "response lost after coordinator retirement"
                    )
                return result

            monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
            with pytest.raises(QueueError, match="response lost"):
                retire_outbound_agent(retirement_config, **args)
            assert retirement_receipt(root) is None
            assert operator.agent("worker").state == "RETIRED_CLEAN"
        receipt = retire_outbound_agent(retirement_config, **args)
        assert operator.agent("worker").state == "RETIRED_CLEAN"
        assert retire_outbound_agent(retirement_config, **args) == receipt
        with pytest.raises(QueueError):
            retire_outbound_agent(
                retirement_config, **{**args, "expected_session_id": "stale"}
            )
        agent_root = service.client.agent_root
        assert agent_root is not None
        with retired_role_guard(agent_root, receipt):
            assert agent_root.is_dir()
        with pytest.raises(QueueError, match="retired"):
            run_outbound_agent_service(service, stop=Event())
        operator.retire("remove-fleet", session.coordinator_id)


def test_retirement_cli_has_explicit_identity_fences(capsys):
    from loom.cli.main import main

    assert main(["queue", "agent-retire", "--help"]) == 0
    help_text = capsys.readouterr().out
    assert "--expected-coordinator-id" in help_text and "--session-id" in help_text


def test_busy_stopped_agent_cannot_retire_or_lose_native_state(remote_work):
    work = remote_work
    service = work.services[0]
    service.stop.set()
    service.thread.join(timeout=10)
    assert not service.thread.is_alive()
    session = work.daemon.agent("agent-a")
    root = work.service_config.client.agent_root
    with pytest.raises(QueueError, match="retained work"):
        retire_outbound_agent(
            work.service_config,
            operation_id="remove-busy",
            expected_coordinator_id=work.daemon.status().coordinator_id,
            expected_session_id=session.session_id,
        )
    assert retirement_receipt(root) is None
    assert root.is_dir()
    assert work.daemon.agent("agent-a").state == "ACTIVE"


def _poll_rows(root):
    with sqlite3.connect(root / "control.sqlite") as conn:
        return conn.execute(
            "SELECT sequence,state,result_json FROM agent_poll_state_local"
        ).fetchall()


@contextmanager
def stopped_idle_poll(tmp_path, monkeypatch, *, drain=True, outcome="committed"):
    """Stop with a lost idle reply, retaining and settling the drain receipt."""
    from loom.queue import agent_session_transport as transport

    committed, release, stop = Event(), Event(), Event()
    original = transport._exchange_agent_request
    errors = []
    if outcome == "fenced":
        from loom.queue.agent_sessions import AgentSessionService

        def interrupt_delivery(*args, **kwargs):
            # A failed native delivery lookup leaves a reserved, inactive poll
            # with no result; its lost error response still needs confirmation.
            raise QueueServiceError("delivery lookup interrupted")

        monkeypatch.setattr(
            AgentSessionService, "_take_targeted_delivery", interrupt_delivery
        )

    def exchange(*args, **kwargs):
        try:
            reply = original(*args, **kwargs)
        except QueueError:
            if args[1] != "poll" or outcome != "fenced":
                raise
            committed.set()
            assert release.wait(15)
            raise transport._IndeterminateAgentProtocolError(
                "fenced reply was lost"
            ) from None
        if args[1] == "poll" and not committed.is_set():
            assert reply.value["result"] == "wait"
            committed.set()
            assert release.wait(15)
            reply.connection.close()
            raise transport._IndeterminateAgentProtocolError("idle reply was lost")
        return reply

    monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
    with fleet(tmp_path) as (daemon, operator):
        service = load_outbound_agent_service_config(tmp_path / "agent.json")
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)

        def serve():
            try:
                run_outbound_agent_service(service, stop=stop)
            except BaseException as exc:
                errors.append(exc)

        thread = Thread(target=serve, daemon=True)
        thread.start()
        try:
            assert committed.wait(15), errors
            session = operator.agent("worker")
            if drain:
                operator.control_agent(
                    AgentControl(
                        "drain-worker",
                        AgentControlKind.DRAIN,
                        "worker",
                        session.session_id,
                        session.config_revision,
                        None,
                        False,
                        "retirement test",
                    )
                )
            stop.set()
            release.set()
            thread.join(10)
            assert not thread.is_alive(), errors
            assert errors == []
            assert _poll_rows(service.client.agent_root)[0][1:] == ("PENDING", None)
            # Settle the explicit control after stopping the held response. This
            # does not replay the work poll or obtain another execution offer.
            if drain:
                owner = LocalDaemonAgentHttpClient(service.client)
                try:
                    assert owner.poll_control(session.session_id) is not None
                finally:
                    owner.close()
                assert (
                    operator.wait_operation(
                        "drain-worker", timeout_seconds=10
                    ).operation.state
                    == "applied"
                )
                assert _poll_rows(service.client.agent_root)[0][1:] == ("FENCED", None)
            assert operator.agent_retirement_ready("worker", session.session_id)
            yield daemon, operator, service
        finally:
            stop.set()
            release.set()
            thread.join(10)
            _stop_fixture_supervisor(service.client.agent_root)
            assert not thread.is_alive(), errors


@pytest.mark.parametrize(
    "mode,drain,outcome",
    [
        ("spec", True, "committed"),
        ("service", True, "committed"),
        ("spec", False, "committed"),
        ("spec", True, "fenced"),
    ],
)
def test_stopped_service_retires_after_lost_idle_poll(
    tmp_path, monkeypatch, mode, drain, outcome
):
    from loom.queue import agent_session_transport as transport

    with stopped_idle_poll(tmp_path, monkeypatch, drain=drain, outcome=outcome) as (
        _,
        operator,
        service,
    ):
        root = service.client.agent_root
        spec = read_agent_spec(tmp_path / "agent.json")
        session = operator.agent("worker")
        sequence = _poll_rows(root)[0][0]
        operations = []
        original = transport._exchange_agent_request

        def exchange(*args, **kwargs):
            operations.append(args[1])
            assert args[1] in {"recover_poll", "retire"}
            return original(*args, **kwargs)

        monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
        if mode != "service":

            def forbidden(*args, **kwargs):
                pytest.fail("bound retirement must not requalify old software")

            monkeypatch.setattr("loom.queue.deployment.qualify_agent_spec", forbidden)
            monkeypatch.setattr(
                "loom.queue._agent_process_supervisor._profile_from_value", forbidden
            )
        config = service if mode == "service" else spec
        args = dict(
            operation_id="retire-idle",
            expected_coordinator_id=operator.status().coordinator_id,
            expected_session_id=session.session_id,
        )
        receipt = retire_outbound_agent(config, **args)
        assert operations == ["recover_poll", "retire"]
        assert operator.agent("worker").state == "RETIRED_CLEAN"
        # Retirement fences a committed receipt; an unanswered fenced request
        # already has the explicit authority-confirmed watermark.
        assert _poll_rows(root)[0][:2] == (
            sequence,
            "FENCED" if outcome == "committed" else "RECONCILED",
        )
        if outcome == "committed":
            assert json.loads(_poll_rows(root)[0][2])["result"] == "wait"
        else:
            assert _poll_rows(root)[0][2] is None
        assert retire_outbound_agent(config, **args) == receipt
        assert operations == ["recover_poll", "retire"]
        with retired_role_guard(root, receipt):
            assert root.is_dir()


@pytest.mark.parametrize("failure", ["active", "unsupported", "lost-response"])
def test_retirement_keeps_unconfirmed_poll_when_recovery_is_unavailable(
    tmp_path, monkeypatch, failure
):
    from loom.queue import agent_session_transport as transport
    from loom.queue.agent_sessions import AgentPollActiveError
    from loom.queue.errors import QueueConflictError

    with stopped_idle_poll(tmp_path, monkeypatch) as (_, operator, service):
        spec = read_agent_spec(tmp_path / "agent.json")
        session = operator.agent("worker")
        before = _poll_rows(spec.agent_root)
        original = transport._exchange_agent_request
        operations = []

        def unavailable(*args, **kwargs):
            operations.append(args[1])
            assert args[1] == "recover_poll"
            if failure == "active":
                raise AgentPollActiveError("work poll is already active")
            if failure == "unsupported":
                raise QueueConflictError("current-epoch poll must use ordinary replay")
            reply = original(*args, **kwargs)
            reply.connection.close()
            raise transport._IndeterminateAgentProtocolError("recovery reply was lost")

        monkeypatch.setattr(transport, "_exchange_agent_request", unavailable)
        args = dict(
            operation_id="retire-retry",
            expected_coordinator_id=operator.status().coordinator_id,
            expected_session_id=session.session_id,
        )
        with pytest.raises(QueueConflictError, match="cannot confirm unanswered poll"):
            retire_outbound_agent(spec, **args)
        assert operations == ["recover_poll"]
        assert _poll_rows(spec.agent_root) == before
        assert retirement_receipt(spec.agent_root) is None
        assert operator.agent("worker").state == "ACTIVE"
        monkeypatch.setattr(transport, "_exchange_agent_request", original)
        assert retire_outbound_agent(spec, **args)["state"] == "retired"


def test_retirement_preserves_job_from_lost_poll_reply(remote_owner, monkeypatch):
    from loom.queue import agent_session_transport as transport

    work = remote_owner
    coordinator = work.daemon.client_view(
        LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    )
    coordinator.submit(LocalDaemonAdmissionRequest("lifecycle", work.run_uri))
    delivered = Event()
    original = transport._exchange_agent_request
    delivery = []

    def lose_delivery(*args, **kwargs):
        reply = original(*args, **kwargs)
        if args[1] == "poll" and reply.value.get("result") == "assignment":
            delivery.append(thaw_plain_data(reply.value))
            work.services[-1].stop.set()
            delivered.set()
            reply.connection.close()
            raise transport._IndeterminateAgentProtocolError("job reply was lost")
        return reply

    monkeypatch.setattr(transport, "_exchange_agent_request", lose_delivery)
    service = work.start_agent()
    assert delivered.wait(15), service.errors
    service.thread.join(10)
    assert not service.thread.is_alive(), service.errors
    assert service.errors == []
    assert work.launches() == ()
    root = work.service_config.client.agent_root
    assert _poll_rows(root)[0][1:] == ("PENDING", None)
    session = work.daemon.agent("agent-a")
    with pytest.raises(QueueError, match="retained work"):
        retire_outbound_agent(
            work.service_config,
            operation_id="retire-lost-job",
            expected_coordinator_id=work.daemon.status().coordinator_id,
            expected_session_id=session.session_id,
        )
    assert _poll_rows(root)[0][1] == "DELIVERED"
    assert json.loads(_poll_rows(root)[0][2]) == delivery[0]
    with sqlite3.connect(root / "control.sqlite") as conn:
        (reference, resolved) = conn.execute(
            "SELECT reference_json,resolved FROM agent_session_references "
            "WHERE reference_kind='delivery'"
        ).fetchone()
    assert json.loads(reference) == delivery[0]["request"]
    assert resolved == 0
    assert work.launches() == ()
    assert retirement_receipt(root) is None
    assert work.daemon.agent("agent-a").state == "ACTIVE"


def test_retirement_reconciles_rejected_legacy_poll_without_replaying_work(
    tmp_path, monkeypatch
):
    from loom.queue import agent_session_transport as transport
    from loom.queue.deployment import _OUTBOUND_POLL_WAIT_MS

    with fleet(tmp_path) as (_, operator):
        service = load_outbound_agent_service_config(tmp_path / "agent.json")
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
        owner = LocalDaemonAgentHttpClient(service.client)
        try:
            handshake = owner.handshake()
            registration = service.registration
            session = owner.register(
                AgentRegistration(
                    "register-rejected",
                    handshake["coordinator_id"],
                    handshake["coordinator_epoch"],
                    owner.agent_root_id,
                    registration.config_revision,
                    registration.inventory_revision,
                    registration.availability_revision,
                    registration.pools,
                    registration.capabilities,
                )
            )
            # A supported pre-reservation rejection (no current offer) retained
            # the exact intent; the old client's fence did not prove consumption.
            with pytest.raises(QueueError):
                owner.wait_for_work(
                    session.session_id,
                    session.availability_revision,
                    sequence=1,
                    wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
                )
            owner._require_journal().fence_poll(session.session_id, 1)
        finally:
            owner.close()
        spec = read_agent_spec(tmp_path / "agent.json")
        assert _poll_rows(spec.agent_root) == [(1, "FENCED", None)]
        operations = []
        original = transport._exchange_agent_request

        def exchange(*args, **kwargs):
            operations.append(args[1])
            assert args[1] in {"recover_poll", "retire"}
            return original(*args, **kwargs)

        monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
        try:
            receipt = retire_outbound_agent(
                spec,
                operation_id="retire-rejected",
                expected_coordinator_id=session.coordinator_id,
                expected_session_id=session.session_id,
            )
            assert receipt["state"] == "retired"
            assert operations == ["recover_poll", "retire"]
            assert _poll_rows(spec.agent_root) == []
            assert operator.agent("worker").state == "RETIRED_CLEAN"
        finally:
            _stop_fixture_supervisor(spec.agent_root)
