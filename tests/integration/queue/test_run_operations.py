"""Durable run continuation, exact replay and independent cancellation settlement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import Any
import hashlib
import socket
import sqlite3
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.diagnostics.run_inspection import RunInspectionProjection
from loom.pipeline.stores import LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer, LocalDaemonAdmissionRequest
from loom.queue.agent_sessions import TransportPrincipalPolicy
from loom.queue.agent_session_transport import (
    AgentTlsServerConfig,
    LocalDaemonAgentHttpServer,
)
from loom.queue.errors import QueueConflictError
from loom.queue._preparation_operations import PreparationNotAccepted
from loom.serialization import stable_json_bytes
from tests.integration.queue.test_preparation_operations import _service, _request
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _result(operation) -> Mapping[str, Any]:
    assert isinstance(operation.result, Mapping)
    return operation.result


def _two_stage_service(tmp_path: Path, *, failing: bool = False):
    service = _service(tmp_path)
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    stage = authored["pipeline"]["stages"][0]
    authored["pipeline"]["stages"].append(
        {**stage, "name": "second", "depends_on": ["produce"]}
    )
    if failing:
        stage["factory"] = {
            "_target_": "tests.support.pipeline_execution_stages.FailingStage"
        }
        stage["config"] = {}
    path.write_text(json.dumps(authored))
    return service


@pytest.mark.parametrize("transport", ["unix", "https"])
def test_lost_run_acceptance_detach_reconnect_and_two_stage_settlement(
    tmp_path, monkeypatch, transport
):
    import loom.queue.local_daemon_transport as unix
    import loom.queue.agent_session_transport as https

    service = _two_stage_service(tmp_path)
    policy = replace(
        service.daemon.agent_policy,
        principals=(TransportPrincipalPolicy("client", "caller", "client"),),
    )
    service = replace(service, daemon=replace(service.daemon, agent_policy=policy))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    inspection = RunInspectionProjection(
        run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon
    )
    dropped = Event()

    def should_drop(value):
        result = value.get("result")
        if (
            isinstance(result, Mapping)
            and result.get("kind") == "run"
            and not dropped.is_set()
        ):
            dropped.set()
            return True
        return False

    if transport == "unix":
        server = LocalDaemonSocketServer(
            daemon,
            service.daemon.endpoint,
            inspect_run=lambda uri: inspection.inspect(uri).to_dict(),
        )
        server.start()

        def factory():
            return CoordinatorClient.from_unix_socket(service.daemon.endpoint)

        original = unix._write_message

        def write(connection, value):
            if should_drop(value):
                connection.shutdown(socket.SHUT_RDWR)
                return
            original(connection, value)

        monkeypatch.setattr(unix, "_write_message", write)
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
                        credentials["other"].with_suffix(".crt")
                    ): "client"
                },
            ),
            inspect_run=lambda uri: inspection.inspect(uri).to_dict(),
        )
        server.start()
        path = tmp_path / "connection.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "transport": {
                        "kind": "https",
                        "url": f"https://localhost:{server.port}",
                        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                        "certificate_path": str(
                            credentials["other"].with_suffix(".crt")
                        ),
                        "private_key_path": str(
                            credentials["other"].with_suffix(".key")
                        ),
                    },
                }
            )
        )
        path.chmod(0o600)

        def factory():
            return CoordinatorClient.from_connection_file(path)

        original = https._Handler._reply

        def reply(handler, status, value):
            if should_drop(value):
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            original(handler, status, value)

        monkeypatch.setattr(https._Handler, "_reply", reply)
    request = RunRequest(_request(), "target-admission")
    try:
        with factory() as client:
            owner = client.describe_connection().coordinator_id
            with pytest.raises(CoordinatorClientError) as wrong:
                client.start_run(request, expected_coordinator_id="wrong")
            assert wrong.value.mutation_outcome == "not_applied"
            with pytest.raises(CoordinatorClientError) as lost:
                client.start_run(request)
            assert lost.value.mutation_outcome == "unknown"
            assert lost.value.ids["operation_id"] == "prepare-1"
            assert lost.value.ids["queue_item_id"] == "target-admission"
            assert lost.value.ids["expected_coordinator_id"] == owner
        with factory() as client:
            accepted = client.start_run(request, expected_coordinator_id=owner)
            assert accepted.kind == "run" and accepted.state == "pending"
            detached = client.observe_run(
                accepted.operation_id, wait=False, expected_coordinator_id=owner
            )
            assert detached.admission is None
            assert detached.connection.coordinator_id == owner
            assert detached.to_dict()["cleanup"] == {"coordinator": "borrowed"}
            assert (
                client.observe_run(
                    accepted.operation_id, timeout_seconds=0
                ).operation_id
                == accepted.operation_id
            )
        daemon._preparations._reconcile_lock.release()
        with factory() as client:
            completed = client.observe_run(
                "prepare-1", timeout_seconds=25, expected_coordinator_id=owner
            )
            assert completed.operation is not None
            assert completed.operation.state == "applied", completed
            assert (
                completed.admission is not None
                and completed.admission.state.value == "SUCCEEDED"
            ), completed
            assert completed.inspection is not None
            assert client.start_run(request) == completed.operation
            cancelled = client.cancel_run_operation("prepare-1")
            assert (
                cancelled.kind == "cancel_run" and cancelled.operation_id != "prepare-1"
            )
            settled = client.wait_operation(cancelled.operation_id, 10).operation
            assert settled.state == "applied"
            assert (
                _result(settled)["admission"]
                == _result(completed.operation)["admission"]
            )
            assert client.operation("prepare-1").state == "applied"
            assert len(stable_json_bytes(settled.to_dict())) <= 64 * 1024
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 2
            )
    finally:
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("boundary", ["published", "retained", "admitted"])
def test_crash_recovery_never_replans_after_admission(tmp_path, boundary):
    service = _two_stage_service(tmp_path)
    reached = Event()

    class InterruptedPreparation(CoordinatorPreparation):
        def publish_target(self, *args, **kwargs):
            receipt = super().publish_target(*args, **kwargs)
            if boundary == "published":
                reached.set()
                raise RuntimeError("lost publication receipt")
            return receipt

    class InterruptedDaemon(LocalDaemon):
        def _submit(self, *args, **kwargs):
            if kwargs.get("run_operation_id") and boundary == "retained":
                reached.set()
                raise RuntimeError("crash before admission")
            admission = super()._submit(*args, **kwargs)
            if kwargs.get("run_operation_id") and boundary == "admitted":
                reached.set()
                raise RuntimeError("lost admission reply")
            return admission

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = InterruptedDaemon(
        service.daemon, preparation=InterruptedPreparation(service)
    )
    daemon.start()
    request = RunRequest(_request(), "target-admission")
    try:
        daemon.start_run(request, principal_id="caller")
        assert reached.wait(25), daemon.operation("prepare-1")
        if boundary == "admitted":
            assert (
                daemon._wait("target-admission", timeout_seconds=25).state.value
                == "SUCCEEDED"
            )
    finally:
        daemon.stop()
    calls = []

    class RecoveryPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            calls.append("report")
            assert boundary == "published", (
                "retained publication must bypass report/planner"
            )
            return super().read_report(*args, **kwargs)

        def publish_target(self, *args, **kwargs):
            calls.append("publish")
            assert boundary == "published", "executed target must never be replanned"
            return super().publish_target(*args, **kwargs)

    recovered = LocalDaemon(service.daemon, preparation=RecoveryPreparation(service))
    recovered.start()
    try:
        applied = recovered.wait_operation("prepare-1", timeout=25).operation
        assert applied.kind == "run" and applied.state == "applied", applied
        assert (
            recovered._wait("target-admission", timeout_seconds=25).state.value
            == "SUCCEEDED"
        )
        assert recovered.start_run(request, principal_id="caller") == applied
        assert bool(calls) is (boundary == "published")
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM managed_admissions WHERE queue_item_id = 'target-admission'"
                ).fetchone()[0]
                == 1
            )
    finally:
        recovered.stop()


@pytest.mark.parametrize("boundary", ["capture", "publication", "admission"])
def test_cancellation_serializes_and_settles_its_own_control(tmp_path, boundary):
    service = _two_stage_service(tmp_path)
    entered, release = Event(), Event()

    class PausedPreparation(CoordinatorPreparation):
        def publish_target(self, *args, **kwargs):
            if boundary == "publication":
                entered.set()
                assert release.wait(25)
            return super().publish_target(*args, **kwargs)

    class PausedDaemon(LocalDaemon):
        def _submit(self, *args, **kwargs):
            admission = super()._submit(*args, **kwargs)
            if kwargs.get("run_operation_id") and boundary == "admission":
                entered.set()
                assert release.wait(25)
                raise RuntimeError("admission reply lost while cancellation waits")
            return admission

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = PausedDaemon(service.daemon, preparation=PausedPreparation(service))
    if boundary == "capture":
        daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    try:
        daemon.start_run(
            RunRequest(_request(), "target-admission"), principal_id="caller"
        )
        if boundary != "capture":
            assert entered.wait(25)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                daemon.cancel_run_operation, "prepare-1", principal_id="caller"
            )
            if boundary == "admission":
                # The call cannot acknowledge suppression until admission's
                # critical section and its uncertain response have finished.
                assert not pending.done()
                release.set()
            cancellation = pending.result(timeout=5)
        assert cancellation.kind == "cancel_run" and cancellation.state == "pending"
        if boundary == "capture":
            daemon._preparations._reconcile_lock.release()
        release.set()
        completed = daemon.wait_operation(
            cancellation.operation_id, timeout=25
        ).operation
        assert completed.state == "applied", completed
        original = daemon.operation("prepare-1")
        assert original.state == (
            "applied" if boundary == "admission" else "cancelled"
        ), original
        assert (
            _result(original)["cancellation_operation_id"] == cancellation.operation_id
        )
        assert (
            daemon.cancel_run_operation("prepare-1", principal_id="caller") == completed
        )
        assert bool(_result(completed)["admission"]) is (boundary == "admission")
        if boundary == "publication":
            assert _result(original)["prepared_run"] is not None
            with pytest.raises(QueueConflictError, match="belongs to a run operation"):
                daemon._submit(
                    LocalDaemonAdmissionRequest(
                        "target-admission", _result(original)["prepared_run"]["run_uri"]
                    )
                )
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM managed_admissions WHERE queue_item_id = 'target-admission'"
            ).fetchone()[0] == (1 if boundary == "admission" else 0)
    finally:
        release.set()
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


def test_run_identity_ownership_and_projection_refusal_before_effects(tmp_path):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    request = RunRequest(_request(), "target-admission")
    try:
        reserved_id = (
            "cancel-run-"
            + hashlib.sha256(request.preparation.operation_id.encode()).hexdigest()
        )
        reserved_request = replace(
            _request(), operation_id=reserved_id, run_name="other-target"
        )
        with pytest.raises(QueueConflictError, match="namespace is reserved"):
            daemon.prepare_run(reserved_request, principal_id="caller")
        accepted = daemon.start_run(request, principal_id="caller")
        with pytest.raises(QueueConflictError, match="namespace is reserved"):
            daemon.prepare_run(reserved_request, principal_id="caller")
        assert daemon.start_run(request, principal_id="caller") == accepted
        for changed, principal in [
            (request, "other"),
            (replace(request, queue_item_id="changed"), "caller"),
            (
                replace(
                    request, preparation=replace(_request(), config_path="changed.yaml")
                ),
                "caller",
            ),
        ]:
            with pytest.raises(QueueConflictError):
                daemon.start_run(changed, principal_id=principal)
        with pytest.raises(QueueConflictError):
            daemon.prepare_run(_request(), principal_id="caller")
        with pytest.raises(QueueConflictError, match="cancel_run_operation"):
            daemon.cancel_preparation("prepare-1", principal_id="caller")
        with pytest.raises(QueueConflictError, match="principal"):
            daemon.cancel_run_operation("prepare-1", principal_id="other")
        with pytest.raises(PreparationNotAccepted, match="result_too_large"):
            daemon.start_run(
                RunRequest(
                    replace(_request(), operation_id="huge", run_name="huge"),
                    "q" * 40000,
                ),
                principal_id="caller",
            )
        assert not (service.daemon.run_store_root / "huge").exists()
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 0
            )
    finally:
        daemon._preparations._reconcile_lock.release()
        daemon.stop()


def test_failed_run_replay_never_authorizes_retry(tmp_path, monkeypatch):
    service = _two_stage_service(tmp_path, failing=True)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    request = RunRequest(_request(), "target-admission")
    try:
        daemon.start_run(request, principal_id="caller")
        original = daemon.wait_operation("prepare-1", timeout=25).operation
        assert original.state == "applied", original
        failed = daemon._wait("target-admission", timeout_seconds=25)
        assert failed.state.value == "FAILED"

        def forbidden(*args, **kwargs):
            pytest.fail("same-ID replay called publisher or submit/retry")

        monkeypatch.setattr(daemon, "_submit", forbidden)
        for _ in range(3):
            assert daemon.start_run(request, principal_id="caller") == original
        assert daemon.admission_for_queue_item("target-admission") == failed
        monkeypatch.undo()
        retried = daemon._submit(
            LocalDaemonAdmissionRequest(
                "target-admission",
                failed.run_uri,
                retry_failed_revision=failed.revision,
            )
        )
        assert retried.admission_id == failed.admission_id
        assert retried.revision > failed.revision
        assert (
            daemon._wait("target-admission", timeout_seconds=25).state.value == "FAILED"
        )
    finally:
        daemon.stop()


@pytest.mark.parametrize("admitted", [False, True])
def test_cancel_control_survives_restart_before_settlement(tmp_path, admitted):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    if not admitted:
        daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    request = RunRequest(_request(), "target-admission")
    try:
        daemon.start_run(request, principal_id="caller")
        if admitted:
            assert (
                daemon.wait_operation("prepare-1", timeout=25).operation.state
                == "applied"
            )
            daemon._preparations._reconcile_lock.acquire()
        control = daemon.cancel_run_operation("prepare-1", principal_id="caller")
        assert control.state == "pending"
        daemon.stop()
    finally:
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()
    recovered = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    recovered.start()
    try:
        replay = recovered.cancel_run_operation("prepare-1", principal_id="caller")
        assert replay.operation_id == control.operation_id
        settled = recovered.wait_operation(control.operation_id, timeout=25).operation
        assert settled.kind == "cancel_run" and settled.state == "applied"
        original = recovered.start_run(request, principal_id="caller")
        assert original.state == ("applied" if admitted else "cancelled")
        assert _result(original)["cancellation_operation_id"] == control.operation_id
        assert bool(_result(settled)["admission"]) is admitted
    finally:
        recovered.stop()


def test_pending_cancellations_do_not_starve_a_settled_control_after_first_page(
    tmp_path,
):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    controls = []
    try:
        for index in range(33):
            request = RunRequest(
                replace(
                    _request(), operation_id=f"run-{index}", run_name=f"target-{index}"
                ),
                f"queue-{index}",
            )
            daemon.start_run(request, principal_id="caller")
            controls.append(
                daemon.cancel_run_operation(
                    request.preparation.operation_id, principal_id="caller"
                )
            )
        # Run the native suppression step for the tail while predecessors still
        # await their own preparation settlement. No retained state is forged.
        daemon._preparations._advance(daemon._preparations._read("run-32"))
        assert daemon.operation("run-32").state == "cancelled"
        daemon._preparations._reconcile_cancellations()
        assert daemon.operation(controls[-1].operation_id).state == "pending"
        daemon._preparations._reconcile_cancellations()
        assert daemon.operation(controls[-1].operation_id).state == "applied"
        assert all(
            daemon.operation(control.operation_id).state == "pending"
            for control in controls[:-1]
        )
    finally:
        daemon.stop()
        daemon._preparations._reconcile_lock.release()
