"""Stopped bootstrap receives native retirement authority over mutual TLS."""

from dataclasses import replace
import io
import json
from types import SimpleNamespace

import pytest

from loom.queue import _profile_promotion as promotion
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.agent_sessions import AgentControlKind, LocalOwnerOperatorPolicy
from loom.queue.deployment import load_outbound_agent_service_config, read_agent_spec
from loom.queue.errors import QueueConflictError, QueueError
from tests.integration.queue.test_agent_profile_promotion import request, close
from tests.integration.queue.test_agent_session_transport import native_control_endpoint, _request  # noqa: F401
from tests.integration.queue.test_maintenance_admission import change, operator
from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("host_failure", [None, "conversion", "receipt"])
def test_stopped_tls_delivery_retries_lost_reply_and_preserves_acknowledgement(tmp_path, monkeypatch, native_control_endpoint, host_failure):  # noqa: F811
    from loom.queue import agent_session_transport as transport

    daemon, server, _, credentials = native_control_endpoint
    capabilities = ("python", "remote-stage-execution-v4", "regular-file-relay-v1",
                    "shared-execution-v1", "shared-assignment-reference-v1", "submitted-container-execution-v1")
    daemon.replace_agent_policy(replace(daemon.config.agent_policy,
        agents=(replace(daemon.config.agent_policy.agents[0], capabilities=capabilities),),
        local_owner=LocalOwnerOperatorPolicy(("drain", "maintenance"), ("agent-a",), ("default",))))
    policy, _, _, _ = _submitted(tmp_path)
    source = _agent_config(tmp_path)
    before = json.loads(source.read_text())
    before.update(url=f"https://localhost:{server.port}",
        server_ca_path=str(credentials["ca"].with_suffix(".crt")),
        certificate_path=str(credentials["agent"].with_suffix(".crt")),
        private_key_path=str(credentials["agent"].with_suffix(".key")),
        resources={"cpu_capacity": 1, "memory_capacity_bytes": 0,
                   "gpu": {"provider": "nvidia", "devices": "none"}},
        container_policies=[policy.to_dict()])
    before["resident_profiles"][0]["descriptor"]["profile_id"] = "work"
    before["registration"]["capabilities"] = list(capabilities)
    obsolete = tmp_path / "obsolete-data"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"images")
    before["container_policies"][0]["shared_roots"]["obsolete"] = {
        **before["container_policies"][0]["shared_roots"]["workloads"],
        "host_path": str(obsolete),
    }
    _write_protected(source, before)
    candidate = _write_protected(tmp_path / "candidate.json", {
        **before, "resident_profiles": [], "container_policies": [policy.to_dict()],
    })
    old = load_outbound_agent_service_config(source).client
    target = load_outbound_agent_service_config(candidate).client
    LocalDaemonAgentHttpClient.initialize_agent_root(old)
    client = LocalDaemonAgentHttpClient(old)
    try:
        session = client.register(replace(_request(client.handshake(), client.agent_root_id),
                                          declared_capabilities=capabilities))
        change(daemon, "close", owner="upgrade")
        control = request(old, old, client.agent_root_id, session=session.session_id, revision=session.config_revision)
        control = replace(control, promotion={
            **{key: value for key, value in control.promotion.items()
               if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
            "maintenance_intent_digest": "intent-upgrade", "retire_configuration": True,
            "candidate_source": str(candidate), "target_immutable": target.deployment_configuration_fingerprint,
            "target_active": target.active_configuration_fingerprint,
        })
        drain = replace(control, operation_id="drain", kind=AgentControlKind.DRAIN, promotion=None)
        operator(daemon).control_agent(drain)
        assert client.poll_control(session.session_id) == drain
        operator(daemon).control_agent(control)
    finally:
        close(client)
    # Combined bootstrap replaces the coordinator before converting agents.
    # Delivery must reconcile the retained old epoch before local revisions change.
    daemon.stop()
    daemon.start()
    (obsolete / "challenge").unlink()
    obsolete.rmdir()
    with pytest.raises(QueueError):
        load_outbound_agent_service_config(source)
    spec = read_agent_spec(source)
    with pytest.raises(QueueConflictError, match="session or native identity"):
        promotion.receive_stopped(spec, control, expected_coordinator_id="wrong")
    changed = replace(control, promotion={**control.promotion, "target_active": "f" * 64})
    with pytest.raises(QueueConflictError, match="authorized coordinator control"):
        promotion.receive_stopped(spec, changed, expected_coordinator_id=session.coordinator_id)
    exchange = transport._exchange_agent_request
    lost = []

    def lose_reply(config, operation, *args):
        result = exchange(config, operation, *args)
        if operation == "control" and not lost:
            lost.append(True)
            raise TimeoutError("lost delivered control reply")
        return result

    monkeypatch.setattr(transport, "_exchange_agent_request", lose_reply)
    with pytest.raises(TimeoutError, match="lost delivered"):
        promotion.receive_stopped(spec, control, expected_coordinator_id=session.coordinator_id)
    assert source.read_text() == json.dumps(before)
    assert promotion.receive_stopped(spec, control, expected_coordinator_id=session.coordinator_id) == control
    monkeypatch.setattr(transport, "_exchange_agent_request", lambda *args: pytest.fail("retained delivery must replay locally"))
    assert promotion.receive_stopped(spec, control, expected_coordinator_id=session.coordinator_id) == control
    if host_failure is None:
        effect = promotion.apply_stopped(spec, control)
        assert effect.code == "applied"
    else:
        from loom.fleet import _host, _workload_host, ssh_operations

        admin = tmp_path / "admin"
        admin.mkdir(mode=0o700)
        host_request = {
            "action": "workload-stopped-retire", "name": "agent-a",
            "admin": str(admin), "request_id": "retire-stopped",
            "root": str(spec.agent_root), "config": str(source),
            "expected_root_id": session.agent_root_id,
            "source_release": "old-runtime", "release": "target-runtime",
            "expected_declaration": _host.digest(before),
            "coordinator_id": session.coordinator_id, "control": control.value(),
        }
        _host.atomic(admin / "service.json", {
            **host_request, "release": "old-runtime",
        })
        with pytest.raises(QueueConflictError, match="service binding differs"):
            _workload_host.retire_stopped({**host_request, "source_release": "another-runtime"})
        with pytest.raises(QueueConflictError, match="declaration changed"):
            _workload_host.retire_stopped({**host_request, "expected_declaration": "stale"})

        original = promotion._finish if host_failure == "conversion" else _host.atomic
        failures = []

        def interrupt(*args, **kwargs):
            if not failures and (host_failure == "conversion" or args[0].name == "receipt.json"):
                failures.append(True)
                raise RuntimeError("interrupted stopped host action")
            return original(*args, **kwargs)

        monkeypatch.setattr(promotion if host_failure == "conversion" else _host,
                            "_finish" if host_failure == "conversion" else "atomic", interrupt)

        def host_invoke(value):
            monkeypatch.setattr(_host.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(value).encode())))
            return _host.main()

        sent = []

        def ssh(host, value):
            sent.append(value)
            try:
                return host_invoke({**value, "admin": str(admin)})
            except QueueError:
                raise
            except RuntimeError as exc:
                raise ssh_operations.SshUnavailable(str(exc)) from exc

        monkeypatch.setattr(ssh_operations, "ssh", ssh)
        monkeypatch.setattr(ssh_operations, "verify_release", lambda _: "target-runtime")
        controller_root = tmp_path / "controller"
        controller_root.mkdir(mode=0o700)
        controller_intent = {
            "operation_id": "retire-stopped", "release": "target-runtime",
            "hosts": {"agent-a": {**host_request, "host": "local", "env_file": None, "env_sha256": None}},
            "inputs": {str(source): ssh_operations._file_hash(source)},
            "declarations": {"agent-a": before},
        }

        def invoke():
            # Reconstruct the controller each time; only its retained evidence
            # and native publication may bridge the changed source bytes.
            operation = ssh_operations._Operation(
                SimpleNamespace(runtime_release="target-runtime"), controller_root, controller_intent)
            return operation.call("agent-a", "workload-stopped-retire", **{
                key: host_request[key] for key in (
                    "control", "coordinator_id", "expected_root_id", "source_release")})

        with pytest.raises(ssh_operations.SshUnavailable, match="interrupted stopped"):
            invoke()
        assert promotion.publication_state(spec.agent_root, control.operation_id) == (
            "pending" if host_failure == "conversion" else "applied")
        with pytest.raises(QueueConflictError, match="control"):
            promotion.publication_declaration(read_agent_spec(source), changed)
        published = source.read_bytes()
        altered = json.loads(published)
        altered["reconnect_seconds"] = 0.7
        _write_protected(source, altered)
        with pytest.raises(QueueError):
            invoke()
        assert json.loads(source.read_text()) == altered
        source.write_bytes(published)
        result = invoke()
        assert result["effect"]["code"] == "applied"
        assert result["activation"] == "runtime_start_required"
        assert result["declaration"]["resident_profiles"] == []
        assert "obsolete" not in result["declaration"]["container_policies"][0]["shared_roots"]
        assert invoke() == result
        assert any(value["action"] == "receipt" for value in sent)
        assert _host.read(controller_root / "accepted-inputs.json")[str(source)] == ssh_operations._file_hash(source)
        with pytest.raises(QueueConflictError, match="immutable intent"):
            host_invoke({**sent[0], "admin": str(admin), "coordinator_id": "changed"})
    monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
    restarted = LocalDaemonAgentHttpClient(load_outbound_agent_service_config(source).client)
    try:
        assert restarted.agent_root_id == session.agent_root_id
        assert restarted.poll_control(session.session_id) == control
        assert restarted._require_journal().next_unacknowledged_control() is None
        assert operator(daemon).observe_maintenance()["state"] == "closed"
    finally:
        close(restarted)
