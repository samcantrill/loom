"""Maintenance races, retained continuation and operator trust boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import sqlite3
from threading import Event

import pytest

from loom.coordinator import (
    CoordinatorClient,
    CoordinatorClientError,
    CoordinatorOperatorClient,
    RunRequest,
)
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.agent_sessions import LocalOwnerOperatorPolicy
from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
from loom.queue._maintenance import MaintenanceInProgress
from loom.queue.errors import QueueConflictError
from tests.integration.queue.test_preparation_operations import _service, _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def service(tmp_path, *, local=True):
    selected = _service(tmp_path, local=local)
    return replace(
        selected,
        daemon=replace(
            selected.daemon,
            agent_policy=replace(
                selected.daemon.agent_policy,
                local_owner=LocalOwnerOperatorPolicy(
                    ("maintenance",), (selected.daemon.machine_id,), ("default",)
                ),
            ),
        ),
    )


def operator(daemon):
    return daemon.operator_view(
        LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR)
    )


def control(
    daemon, action, *, revision=None, operation_id=None, owner="maint-1", check=None
):
    view = operator(daemon)
    return {
        "operation_id": operation_id or f"{owner}-{action}",
        "maintenance_id": owner,
        "maintenance_intent_digest": f"intent-{owner}",
        "action": action,
        "expected_revision": view.observe_maintenance()["revision"]
        if revision is None
        else revision,
        "check": check,
    }


def change(daemon, action, **kwargs):
    return operator(daemon).maintenance(
        control(daemon, action, **kwargs),
        expected_coordinator_id=daemon.status().coordinator_id,
    )


@pytest.fixture
def owner(tmp_path):
    selected = service(tmp_path)
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    try:
        yield daemon
    finally:
        daemon.stop()


def counts(daemon):
    with sqlite3.connect(daemon.config.control_database) as conn:
        return tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("managed_admissions", "preparation_operations")
        )


def test_closed_refusal_is_not_acceptance_and_same_id_can_succeed(owner):
    change(owner, "close")
    before = counts(owner)
    for req in (
        _request(),
        replace(_request(), run_options={"tags": {"maintenance": "maint-1"}}),
    ):
        with pytest.raises(MaintenanceInProgress) as caught:
            owner.prepare_run(req, principal_id="caller")
        assert caught.value.operation_id == "prepare-1"
        assert caught.value.maintenance_id == "maint-1"
    assert counts(owner) == before
    assert not (owner.config.run_store_root / "target-1").exists()
    change(owner, "open")
    accepted = owner.prepare_run(_request(), principal_id="caller")
    assert accepted.operation_id == "prepare-1"


def test_exact_replay_conflict_and_cancellation_while_closed(owner):
    request = _request()
    accepted = owner.prepare_run(request, principal_id="caller")
    change(owner, "close")
    assert (
        owner.prepare_run(request, principal_id="caller").operation_id
        == accepted.operation_id
    )
    with pytest.raises(QueueConflictError):
        owner.prepare_run(
            replace(request, overrides=("runtime.tags.changed=true",)),
            principal_id="caller",
        )
    assert owner.operation(accepted.operation_id).operation_id == accepted.operation_id
    assert (
        owner.cancel_preparation(
            accepted.operation_id, principal_id="caller"
        ).operation_id
        == accepted.operation_id
    )


def test_gate_owner_revision_and_exact_mutation_survive_restart(owner):
    view = operator(owner)
    request = control(owner, "close")
    receipt = view.maintenance(
        request, expected_coordinator_id=owner.status().coordinator_id
    )
    assert (
        view.maintenance(request, expected_coordinator_id=owner.status().coordinator_id)
        == receipt
    )
    with pytest.raises(QueueConflictError):
        view.maintenance(
            {**request, "maintenance_intent_digest": "changed"},
            expected_coordinator_id=owner.status().coordinator_id,
        )
    owner.stop()
    owner.start()
    assert operator(owner).observe_maintenance()["maintenance_id"] == "maint-1"
    assert operator(owner).maintenance_operation(request["operation_id"]) == receipt
    with pytest.raises(QueueConflictError):
        change(owner, "open", owner="other")
    with pytest.raises(QueueConflictError):
        change(owner, "open", revision=0)
    change(owner, "open")


@pytest.mark.parametrize("winner", ("accept", "close"))
def test_close_and_accept_share_atomic_owner(owner, monkeypatch, winner):
    from loom.queue import _maintenance

    entered, release = Event(), Event()
    original = _maintenance.classify

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(_maintenance, "classify", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        if winner == "close":
            change(owner, "close")
        accept = pool.submit(owner.prepare_run, _request(), principal_id="caller")
        assert entered.wait(10)
        close = pool.submit(change, owner, "close") if winner == "accept" else None
        release.set()
        if winner == "accept":
            assert accept.result().operation_id == "prepare-1"
            assert close is not None
            assert close.result()["gate"]["state"] == "closed"
        else:
            with pytest.raises(MaintenanceInProgress):
                accept.result()
            assert counts(owner) == (0, 0)


def test_inflight_preparation_and_two_stage_pipeline_continue_closed(tmp_path):
    selected = service(tmp_path)
    path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(path.read_text())
    first = config["pipeline"]["stages"][0]
    config["pipeline"]["stages"].append(
        {**first, "name": "later", "depends_on": ["produce"]}
    )
    path.write_text(json.dumps(config))
    entered, release = Event(), Event()

    class HeldPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            report = super().read_report(*args, **kwargs)
            entered.set()
            assert release.wait(25)
            return report

    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=HeldPreparation(selected))
    daemon.start()
    try:
        request = RunRequest(_request(), "queue-1")
        daemon.start_run(request, principal_id="caller")
        assert entered.wait(25)
        change(daemon, "close")
        release.set()
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == "applied", completed
        admission = daemon._wait("queue-1", timeout_seconds=25)
        assert admission.state.value == "SUCCEEDED", admission
        from loom.pipeline.stores import LocalRunStore

        store = LocalRunStore(daemon.config.run_store_root)
        assert (
            store.read_stage_worker_result(admission.run_uri, "later", attempt=1)
            is not None
        )
        assert operator(daemon).observe_maintenance()["state"] == "closed"
    finally:
        release.set()
        daemon.stop()


def test_unix_codec_mutation_outcomes_unknown_operation_and_cli(owner, capsys):
    from loom.cli.main import main

    server = LocalDaemonSocketServer(owner, owner.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(
            owner.config.endpoint
        ) as client:
            request = control(owner, "close")
            receipt = client.maintenance(
                request, expected_coordinator_id=owner.status().coordinator_id
            )
            assert client.maintenance_operation(request["operation_id"]) == receipt
            with pytest.raises(CoordinatorClientError) as missing:
                client.maintenance_operation("unknown")
            assert missing.value.code == "not_found"
            assert (
                client.maintenance(
                    request, expected_coordinator_id=owner.status().coordinator_id
                )
                == receipt
            )
        with CoordinatorClient.from_unix_socket(owner.config.endpoint) as client:
            with pytest.raises(CoordinatorClientError) as refused:
                client.prepare_run(_request())
            assert refused.value.code == "maintenance_in_progress"
            assert refused.value.mutation_outcome == "not_applied"
            assert refused.value.ids["maintenance_id"] == "maint-1"
        assert (
            main(
                [
                    "queue",
                    "daemon-maintenance",
                    "--endpoint",
                    str(owner.config.endpoint),
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["result"]["state"] == "closed"
    finally:
        server.stop()


def check_binding(owner, request):
    profile = owner.config.preparation_policy.select(request.preparation)["profile"][
        "profile_descriptor"
    ]
    from loom.pipeline.resources import ResourceRequest, ResourceEntry

    resources = ResourceRequest({"cpu": ResourceEntry("cpu", 1, "count")}).to_dict()
    return {
        "request": request.to_dict(),
        "principal_id": "caller",
        "agent_id": owner.config.machine_id,
        "pool": "default",
        "profile": profile,
        "resources": resources,
        "preparation_resources": resources,
        "max_stages": 1,
        "previous_check_id": None,
    }


@pytest.mark.parametrize("mismatch", (None, "preparation", "target"))
def test_exact_authorized_check_constrains_both_handoffs(owner, mismatch):
    request = RunRequest(_request(), "check-queue")
    change(owner, "close")
    binding = check_binding(owner, request)
    if mismatch is not None:
        from loom.pipeline.resources import ResourceRequest, ResourceEntry

        key = "preparation_resources" if mismatch == "preparation" else "resources"
        binding[key] = ResourceRequest(
            {"cpu": ResourceEntry("cpu", 2, "count")}
        ).to_dict()
    authorization = control(owner, "authorize", check=binding)
    receipt = operator(owner).maintenance(
        authorization, expected_coordinator_id=owner.status().coordinator_id
    )
    assert (
        operator(owner).maintenance(
            authorization, expected_coordinator_id=owner.status().coordinator_id
        )
        == receipt
    )
    with pytest.raises(QueueConflictError):
        operator(owner).maintenance(
            {**authorization, "check": {**binding, "max_stages": 2}},
            expected_coordinator_id=owner.status().coordinator_id,
        )
    if mismatch is None:
        owner.stop()
        owner.start()
        assert operator(owner).observe_maintenance()["checks"]["prepare-1"] == binding
    with pytest.raises(QueueConflictError):
        owner.start_run(
            replace(request, queue_item_id="different"), principal_id="caller"
        )
    with pytest.raises(QueueConflictError):
        owner.start_run(request, principal_id="another-caller")
    assert counts(owner) == (0, 0)
    owner.start_run(request, principal_id="caller")
    completed = owner.wait_operation("prepare-1", timeout=25).operation
    if mismatch is None:
        assert completed.state == "applied", completed
        assert owner._wait("check-queue", timeout_seconds=25).state.value == "SUCCEEDED"
    else:
        assert completed.state in {"failed", "conflict"}, completed
        assert counts(owner)[0] == (0 if mismatch == "preparation" else 1)
    with pytest.raises(QueueConflictError):
        change(owner, "open")
    change(owner, "revoke", check="prepare-1")
    change(owner, "open")


def test_new_reconciled_observer_and_retry_refused_for_shared_target(tmp_path):
    from tests.integration.queue.test_reconciled_runs import (
        _reconciled_service,
        _reconciled_request,
    )

    selected = _reconciled_service(tmp_path)
    selected = replace(
        selected,
        daemon=replace(
            selected.daemon,
            agent_policy=replace(
                selected.daemon.agent_policy,
                local_owner=LocalOwnerOperatorPolicy(("maintenance",)),
            ),
        ),
    )
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    try:
        first = _reconciled_request("first")
        daemon.start_run(first, principal_id="caller")
        done = daemon.wait_operation("first", timeout=25).operation
        assert done.state == "applied", done
        change(daemon, "close")
        before = counts(daemon)
        assert daemon.start_run(first, principal_id="caller").state == "applied"
        for retry in (False, True):
            with pytest.raises(MaintenanceInProgress):
                daemon.start_run(
                    _reconciled_request("observer", retry=retry), principal_id="caller"
                )
        assert counts(daemon) == before
    finally:
        daemon.stop()


@pytest.mark.parametrize("transport", ("unix", "https"))
def test_transport_lost_close_reply_role_scope_and_wrong_owner(
    tmp_path, monkeypatch, transport
):
    import socket
    from collections.abc import Mapping
    from loom.queue.agent_sessions import TransportPrincipalPolicy
    from loom.queue.agent_session_transport import (
        LocalDaemonAgentHttpServer,
        AgentTlsServerConfig,
    )
    from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
    import loom.queue.local_daemon_transport as unix
    import loom.queue.agent_session_transport as https

    selected = service(tmp_path)
    selected = replace(
        selected,
        daemon=replace(
            selected.daemon,
            agent_policy=replace(
                selected.daemon.agent_policy,
                principals=(
                    TransportPrincipalPolicy(
                        "operator", "operator", "operator", ("maintenance",)
                    ),
                    TransportPrincipalPolicy("client", "client", "client"),
                ),
            ),
        ),
    )
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    dropped = []
    if transport == "unix":
        server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
        client = CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint)
        ordinary = CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint)
        original = unix._write_message

        def reply_unix(connection, value):
            result = value.get("result")
            if (
                isinstance(result, Mapping)
                and result.get("operation_id") == "maint-1-close"
                and not dropped
            ):
                dropped.append(True)
                connection.shutdown(socket.SHUT_RDWR)
                return
            original(connection, value)

        monkeypatch.setattr(unix, "_write_message", reply_unix)
    else:
        credentials = mutual_tls_credentials(tmp_path / "tls")
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    certificate_fingerprint(
                        credentials["query"].with_suffix(".crt")
                    ): "operator",
                    certificate_fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "client",
                },
            ),
        )
        server.start()

        def connection(name):
            path = tmp_path / f"{name}.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "loom.coordinator-client",
                        "transport": {
                            "kind": "https",
                            "url": f"https://localhost:{server.port}",
                            "server_ca_path": str(
                                credentials["ca"].with_suffix(".crt")
                            ),
                            "certificate_path": str(
                                credentials[name].with_suffix(".crt")
                            ),
                            "private_key_path": str(
                                credentials[name].with_suffix(".key")
                            ),
                        },
                    }
                )
            )
            path.chmod(0o600)
            return path

        client = CoordinatorOperatorClient.from_connection_file(connection("query"))
        ordinary = CoordinatorOperatorClient.from_connection_file(connection("other"))
        original = https._Handler._reply

        def reply_https(handler, status, value):
            result = value.get("result")
            if (
                isinstance(result, Mapping)
                and result.get("operation_id") == "maint-1-close"
                and not dropped
            ):
                dropped.append(True)
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            original(handler, status, value)

        monkeypatch.setattr(https._Handler, "_reply", reply_https)
    if transport == "unix":
        server.start()
    try:
        request = control(daemon, "close")
        identity = daemon.status().coordinator_id
        with pytest.raises(CoordinatorClientError) as wrong:
            client.maintenance(request, expected_coordinator_id="wrong")
        assert wrong.value.code == "conflict"
        assert wrong.value.mutation_outcome == "not_applied"
        if transport == "https":
            with pytest.raises(CoordinatorClientError) as denied:
                ordinary.maintenance(request, expected_coordinator_id=identity)
            assert denied.value.code == "unauthorized"
            assert denied.value.mutation_outcome == "not_applied"
        assert operator(daemon).observe_maintenance()["revision"] == 0
        with pytest.raises(CoordinatorClientError) as lost:
            client.maintenance(request, expected_coordinator_id=identity)
        assert dropped
        assert lost.value.mutation_outcome == "unknown"
        receipt = client.maintenance_operation("maint-1-close")
        gate = receipt["gate"]
        assert isinstance(gate, Mapping)
        assert gate["revision"] == 1
        assert client.maintenance(request, expected_coordinator_id=identity) == receipt
    finally:
        client.close()
        ordinary.close()
        server.stop()
        daemon.stop()


def test_fresh_run_is_new_work_while_closed(tmp_path):
    from tests.integration.queue.test_installed_node_contracts import _text_service
    from tests.integration.queue.test_reconciled_runs import _reconciled_request

    selected = _text_service(tmp_path, qualify_actions=True)
    selected = replace(
        selected,
        daemon=replace(
            selected.daemon,
            agent_policy=replace(
                selected.daemon.agent_policy,
                local_owner=LocalOwnerOperatorPolicy(("maintenance",)),
            ),
        ),
    )
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    try:
        change(daemon, "close")
        with pytest.raises(MaintenanceInProgress):
            daemon.start_run(
                replace(_reconciled_request("fresh"), fresh_stages=("author",)),
                principal_id="caller",
            )
        assert counts(daemon) == (0, 0)
    finally:
        daemon.stop()


def test_submit_retry_refusal_and_already_accepted_retry_continuation(
    tmp_path, monkeypatch
):
    from weave import compose_config
    from loom.queue import LocalDaemonAdmissionRequest
    from loom.queue.managed_local_preparation import prepare_managed_run
    from loom.pipeline.orchestration import ExecutionRequirement
    from loom.queue import _coordinator_admission

    selected = service(tmp_path)
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    stage = authored["pipeline"]["stages"][0]
    stage["factory"]["_target_"] = (
        "tests.support.pipeline_execution_stages.FailOnceThenProduceStage"
    )
    stage["config"] = {"marker_path": str(tmp_path / "failed-once")}
    path.write_text(json.dumps(authored))
    assert selected.daemon.resident_worker_launch_profile is not None
    descriptor = selected.daemon.resident_worker_launch_profile.descriptor
    prepared = prepare_managed_run(
        selected,
        compose_config(path),
        "retry-target",
        execution_requirements={
            "produce": ExecutionRequirement(
                str(descriptor["project_fingerprint"]),
                str(descriptor["environment_fingerprint"]),
                str(descriptor["executor_fingerprint"]),
            )
        },
    )
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon)
    daemon.start()
    try:
        request = LocalDaemonAdmissionRequest("retry-queue", prepared.run_uri)
        change(daemon, "close")
        with pytest.raises(MaintenanceInProgress):
            daemon._submit(request)
        assert counts(daemon) == (0, 0)
        change(daemon, "open")
        daemon._submit(request)
        failed = daemon._wait("retry-queue", timeout_seconds=25)
        assert failed.state.value == "FAILED"
        change(daemon, "close", owner="maint-2")
        assert daemon._submit(request) == failed
        retry = replace(request, retry_failed_revision=failed.revision)
        with pytest.raises(MaintenanceInProgress):
            daemon._submit(retry)
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM daemon_metadata WHERE key LIKE 'admission-retry:%'"
                ).fetchone()[0]
                == 0
            )
        change(daemon, "open", owner="maint-2")
        original = _coordinator_admission._apply_admission_retry

        def close_after_acceptance(*args, **kwargs):
            change(daemon, "close", owner="maint-3")
            return original(*args, **kwargs)

        monkeypatch.setattr(
            _coordinator_admission, "_apply_admission_retry", close_after_acceptance
        )
        daemon._submit(retry)
        succeeded = daemon._wait("retry-queue", timeout_seconds=25)
        assert succeeded.state.value == "SUCCEEDED", succeeded
        assert daemon._submit(retry) == succeeded
    finally:
        daemon.stop()


def test_portable_check_child_uses_retained_operator_placement(tmp_path):
    from loom.queue.local_daemon_execution import load_managed_local_intent

    selected = service(tmp_path, local=False)
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    authored["pipeline"]["stages"][0]["placement"] = {
        "target": selected.daemon.machine_id
    }
    path.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    try:
        request = RunRequest(_request(), "portable-check")
        change(daemon, "close")
        change(daemon, "authorize", check=check_binding(daemon, request))
        daemon.start_run(request, principal_id="caller")
        done = daemon.wait_operation("prepare-1", timeout=25).operation
        assert done.state == "applied", done
        assert (
            daemon._wait("portable-check", timeout_seconds=25).state.value
            == "SUCCEEDED"
        )
        with daemon._connection() as conn:
            child_id = conn.execute(
                "SELECT child_admission_id FROM preparation_operations WHERE operation_id = 'prepare-1'"
            ).fetchone()[0]
        child = daemon._admission(child_id)
        intent = load_managed_local_intent(daemon.config, child.run_uri)
        assert intent.placements["prepare"].target == selected.daemon.machine_id
    finally:
        daemon.stop()


def test_missing_maintenance_capability_refuses_before_dispatch(owner, monkeypatch):
    from loom.queue import _coordinator_control

    original = _coordinator_control._connection_description

    def old_capabilities(*args, **kwargs):
        description = original(*args, **kwargs)
        return replace(
            description,
            capabilities=tuple(
                item
                for item in description.capabilities
                if item != "maintenance-admission-v1"
            ),
        )

    monkeypatch.setattr(
        _coordinator_control, "_connection_description", old_capabilities
    )
    server = LocalDaemonSocketServer(owner, owner.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(
            owner.config.endpoint
        ) as client:
            with pytest.raises(CoordinatorClientError) as caught:
                client.maintenance(
                    control(owner, "close"),
                    expected_coordinator_id=owner.status().coordinator_id,
                )
            assert caught.value.code == "unsupported_capability"
            assert caught.value.mutation_outcome == "not_applied"
        assert operator(owner).observe_maintenance()["revision"] == 0
    finally:
        server.stop()


def test_maintenance_owner_and_check_identity_remain_immutable_after_revocation(owner):
    request = RunRequest(_request(), "check-queue")
    change(owner, "close")
    binding = check_binding(owner, request)
    change(owner, "authorize", check=binding)
    change(owner, "revoke", check="prepare-1")
    with pytest.raises(QueueConflictError):
        change(
            owner,
            "authorize",
            operation_id="changed-check",
            check={**binding, "max_stages": 2},
        )
    change(owner, "open")
    changed_owner = {
        **control(owner, "close", operation_id="new-close"),
        "maintenance_intent_digest": "changed",
    }
    with pytest.raises(QueueConflictError):
        operator(owner).maintenance(
            changed_owner, expected_coordinator_id=owner.status().coordinator_id
        )
    assert operator(owner).observe_maintenance()["state"] == "open"
