"""Native retirement proofs precede downstream removal; no fixture data erased."""

from contextlib import contextmanager
import json
from threading import Event
import time

import pytest

from loom.coordinator import RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketClient, LocalDaemonSocketServer
from loom.queue.agent_session_transport import (
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import AgentRegistration
from loom.queue.deployment import (
    load_coordinator_service_config,
    load_outbound_agent_service_config,
    run_outbound_agent_service,
)
from loom.queue.errors import QueueError
from loom.queue.retirement import (
    retire_outbound_agent,
    retired_role_guard,
    retirement_receipt,
)
from tests.integration.queue.test_service_lifetime import _mixed_selection, _request
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


def test_agent_clean_retirement_before_revoke_and_native_guard(tmp_path):
    with fleet(tmp_path) as (daemon, operator):
        service = load_outbound_agent_service_config(tmp_path / "agent.json")
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
        agent = LocalDaemonAgentHttpClient(service.client)
        try:
            handshake = agent.handshake()
            reg = service.registration
            session = agent.register(
                AgentRegistration(
                    "register",
                    handshake["coordinator_id"],
                    handshake["coordinator_epoch"],
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
                retire_outbound_agent(service, **args)
            with pytest.raises(QueueError):
                operator.retire("remove-fleet", session.coordinator_id)
        finally:
            agent.close()
        receipt = retire_outbound_agent(service, **args)
        assert operator.agent("worker").state == "RETIRED_CLEAN"
        assert retire_outbound_agent(service, **args) == receipt
        with pytest.raises(QueueError):
            retire_outbound_agent(service, **{**args, "expected_session_id": "stale"})
        with retired_role_guard(service.client.agent_root, receipt):
            assert service.client.agent_root.is_dir()
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
