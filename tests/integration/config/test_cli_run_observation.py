"""CLI identity survives uncertainty; observation and cancellation retain native scope."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping
import io
import json
import os
import socket
import sqlite3
import time

import pytest

from loom.cli.main import main
from loom.coordinator import CoordinatorClient
from loom.deployment import _bind, load_deployment
from loom.diagnostics.run_inspection import RunInspectionProjection
from loom.pipeline.stores import LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
from tests.integration.queue.test_preparation_operations import _request
from tests.integration.queue.test_reconciled_runs import _reconciled_service
from tests.integration.queue.test_service_lifetime import _selection

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@contextmanager
def _owner(tmp_path, *, reconcile=False):
    if reconcile:
        _reconciled_service(tmp_path)
        path = tmp_path / "selection.json"
        path.write_text(json.dumps({
            "schema_version": 1, "kind": "loom.deployment",
            "coordinator": {"service_config": "coordinator.json", "lifetime": "persistent"},
            "binding_path": "binding.json",
            "preparation": {"source": _request().source.to_dict(), "profile": "existing-project"},
            "startup_seconds": 20,
        }))
        path.chmod(0o600)
    else:
        path = _selection(tmp_path, lifetime="persistent")
    config = tmp_path / "coordinator.json"
    value = json.loads(config.read_text())
    value["agent_policy"]["local_owner"]["actions"].append("maintenance")
    config.write_text(json.dumps(value))
    selection = load_deployment(path)
    _bind(selection, "fixture", time.monotonic() + 20)
    service = load_coordinator_service_config(config)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    projection = RunInspectionProjection(run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon)
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint, inspect_run=lambda uri: projection.inspect(uri).to_dict())
    server.start()
    try:
        yield path, daemon
    finally:
        server.stop()
        daemon.stop()


@pytest.fixture
def native(tmp_path):
    with _owner(tmp_path) as selected:
        yield selected


class _CapturedErrors(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        super().flush()


def _run(path, *, identity=None, extra=(), output_format="json", errors=None):
    output = io.StringIO()
    errors = errors if errors is not None else _CapturedErrors()
    args = ["run", "pipeline.yaml", "--deployment", str(path), "--detach", "--format", output_format]
    if identity is not None:
        args.extend(["--operation-id", identity])
    code = main([*args, *extra], stdout=output, stderr=errors)
    return code, output.getvalue(), errors


def _reference(errors):
    line = next(line for line in errors.getvalue().splitlines() if line.startswith("operation reference: "))
    return json.loads(line.removeprefix("operation reference: "))


def _counts(daemon):
    with sqlite3.connect(daemon.config.control_database) as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("managed_admissions", "preparation_operations", "preparation_cancellations"))


@pytest.mark.parametrize("identity", [None, "chosen-operation"])
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_identity_flushed_before_dispatch_and_lost_reply_can_be_observed(native, monkeypatch, identity, output_format):
    import loom.queue.local_daemon_transport as transport

    path, daemon = native
    errors = _CapturedErrors()
    dispatch = CoordinatorClient._native_call
    chosen = []
    def verify_early(client, operation, payload, *args, **kwargs):
        if operation == "start_run":
            reference = _reference(errors)
            assert errors.flush_count > 0
            assert reference["deployment"] == str(path)
            chosen.append(reference["operation_id"])
            assert payload["request"]["preparation"]["operation_id"] == chosen[-1]
        return dispatch(client, operation, payload, *args, **kwargs)
    monkeypatch.setattr(CoordinatorClient, "_native_call", verify_early)
    reply = transport._write_message
    dropped = []
    def lost_reply(connection, value):
        result = value.get("result")
        if isinstance(result, dict) and result.get("kind") == "run" and not dropped:
            dropped.append(True)
            connection.shutdown(socket.SHUT_RDWR)
            return
        reply(connection, value)
    monkeypatch.setattr(transport, "_write_message", lost_reply)
    code, output, errors = _run(path, identity=identity, output_format=output_format, errors=errors)
    assert code == 6
    assert dropped and len(chosen) == 1
    retained = chosen[0]
    assert retained == identity if identity is not None else retained.startswith("run-")
    assert daemon._preparations.contains(retained)
    if output_format == "json":
        error = json.loads(output)["error"]
        assert error["context"]["operation_id"] == retained
        assert error["details"]["coordinator"]["mutation_outcome"] == "unknown"
        assert "loom runs follow" in error["hint"]
    else:
        assert "outcome unknown" in errors.getvalue()
    before = _counts(daemon)[1]
    follow = io.StringIO()
    assert main(["runs", "follow", "--operation-id", retained, "--deployment", str(path), "--timeout-seconds", "30", "--format", "json"], stdout=follow, stderr=io.StringIO()) == 0
    observed = json.loads(follow.getvalue())["result"]
    assert observed["observation"]["admission"]["state"] == "SUCCEEDED"
    assert _counts(daemon)[1] == before
    assert _run(path, identity=retained)[0] == 0
    assert _counts(daemon)[1] == before
    changed, changed_output, _ = _run(path, identity=retained, extra=("--set", "runtime.max_parallel_stages=2"))
    assert changed == 6
    assert json.loads(changed_output)["error"]["details"]["coordinator"]["code"] == "conflict"
    assert _counts(daemon)[1] == before


@pytest.mark.parametrize("arguments", [["not-included.yaml"], ["pipeline.yaml", "--timeout-seconds", "nan"]])
def test_invalid_local_arguments_have_no_receipt_or_service_effect(tmp_path, arguments):
    path = _selection(tmp_path)
    output, errors = io.StringIO(), io.StringIO()
    assert main(["run", *arguments, "--deployment", str(path), "--format", "json"], stdout=output, stderr=errors) != 0
    assert "operation reference:" not in errors.getvalue()
    assert not (tmp_path / "binding.json").exists()
    assert not (tmp_path / "deployment").exists()
    assert json.loads(output.getvalue())["error"]["context"]["operation_id"].startswith("run-")


def test_missing_follow_never_submits_initializes_or_cancels(native, monkeypatch):
    import loom.deployment as deployment

    path, daemon = native
    before = _counts(daemon)
    def forbidden(*args, **kwargs):
        raise AssertionError("observation attempted service creation")
    monkeypatch.setattr(deployment, "ensure_available", forbidden)
    monkeypatch.setattr(LocalDaemon, "initialize_deployment", forbidden)
    output = io.StringIO()
    assert main(["runs", "follow", "--operation-id", "absent", "--deployment", str(path), "--format", "json"], stdout=output, stderr=io.StringIO()) == 6
    error = json.loads(output.getvalue())["error"]
    assert error["details"]["coordinator"]["code"] == "not_found"
    assert _counts(daemon) == before


@pytest.mark.parametrize("interruption", ["ctrl-c", "read-ctrl-c", "timeout"])
def test_follow_detaches_pending_native_work_without_mutation(native, monkeypatch, interruption):
    path, daemon = native
    monkeypatch.setattr(daemon._preparations, "reconcile", lambda: None)
    assert _run(path, identity="pending")[0] == 0
    before = _counts(daemon)
    if interruption == "ctrl-c":
        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(CoordinatorClient, "_wait_native", interrupted)
    elif interruption == "read-ctrl-c":
        read = CoordinatorClient._native_call
        def interrupted_read(client, operation, *args, **kwargs):
            if operation == "operation":
                raise KeyboardInterrupt()
            return read(client, operation, *args, **kwargs)
        monkeypatch.setattr(CoordinatorClient, "_native_call", interrupted_read)
    output = io.StringIO()
    started = time.monotonic()
    assert main(["runs", "follow", "--operation-id", "pending", "--deployment", str(path), "--timeout-seconds", "0.15", "--format", "json"], stdout=output, stderr=io.StringIO()) == 0
    assert time.monotonic() - started < 1.0
    result = json.loads(output.getvalue())["result"]
    assert result["detached"] == ("timeout" if interruption == "timeout" else "interrupted")
    if interruption == "read-ctrl-c":
        assert result["observation"] is None
    else:
        assert result["observation"]["operation"]["state"] == "pending"
    assert _counts(daemon) == before
    assert daemon.operation("pending").result["cancellation_operation_id"] is None


def test_native_maintenance_refusal_retains_early_id_and_outcome(native):
    path, daemon = native
    operator = daemon.operator_view(LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR))
    operator.maintenance({
        "operation_id": "window-close", "maintenance_id": "window",
        "maintenance_intent_digest": "selected-window", "action": "close",
        "expected_revision": 0, "check": None,
    }, expected_coordinator_id=daemon.status().coordinator_id)
    before = _counts(daemon)
    code, output, errors = _run(path, identity="refused")
    assert code == 6
    assert _reference(errors)["operation_id"] == "refused"
    error = json.loads(output)["error"]
    assert error["context"]["operation_id"] == "refused"
    assert error["details"]["coordinator"]["code"] == "maintenance_in_progress"
    assert error["details"]["coordinator"]["mutation_outcome"] == "not_applied"
    assert error["details"]["coordinator"]["ids"]["maintenance_id"] == "window"
    assert _counts(daemon) == before


def test_shared_target_cancel_displays_scope_before_dispatch_and_keeps_native_id(tmp_path, monkeypatch):
    with _owner(tmp_path, reconcile=True) as (path, daemon):
        for identity in ("first", "observer"):
            assert _run(path, identity=identity, extra=("--reconcile",))[0] == 0
            assert daemon.wait_operation(identity, timeout=30).operation.state == "applied"
        first, observer = daemon.operation("first"), daemon.operation("observer")
        assert isinstance(first.result, Mapping) and isinstance(observer.result, Mapping)
        first_binding, observer_binding = first.result["binding"], observer.result["binding"]
        assert isinstance(first_binding, Mapping) and isinstance(observer_binding, Mapping)
        resolved_target = observer_binding["run_uri"]
        assert first_binding["run_uri"] == resolved_target
        output, errors = io.StringIO(), _CapturedErrors()
        cancel = CoordinatorClient.cancel_run_operation
        previews = []
        def verify_scope(client, identity, **kwargs):
            line = errors.getvalue().splitlines()[-1]
            preview = json.loads(line.removeprefix("cancellation scope: "))
            assert preview["resolved_target"] == resolved_target
            assert preview["scope"] == "resolved_target_and_all_observers_if_bound"
            assert errors.flush_count > 0
            previews.append(preview)
            return cancel(client, identity, **kwargs)
        monkeypatch.setattr(CoordinatorClient, "cancel_run_operation", verify_scope)
        arguments = ["runs", "cancel", "--operation-id", "observer", "--deployment", str(path), "--format", "json"]
        assert main(arguments, stdout=output, stderr=errors) == 0
        result = json.loads(output.getvalue())["result"]
        assert result["cancellation_operation_id"].startswith("cancel-run-")
        assert result["containment"] == "not_established_by_acknowledgement"
        assert result["scope"] == previews[0]["scope"]
        assert result["resolved_target"] == previews[0]["resolved_target"]
        before = _counts(daemon)
        output = io.StringIO()
        assert main(arguments, stdout=output, stderr=errors) == 0
        assert json.loads(output.getvalue())["result"]["cancellation_operation_id"] == result["cancellation_operation_id"]
        assert _counts(daemon) == before
        with daemon._connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM preparation_operations WHERE cancellation_requested = 1 AND operation_id IN ('first','observer')").fetchone()[0] == 2


def test_follow_success_does_not_turn_borrowed_cleanup_into_failure(native):
    path, daemon = native
    assert _run(path, identity="success")[0] == 0
    output, errors = io.StringIO(), io.StringIO()
    assert main(["runs", "follow", "--operation-id", "success", "--deployment", str(path), "--format", "json"], stdout=output, stderr=errors) == 0
    result = json.loads(output.getvalue())["result"]
    assert result["observation"]["admission"]["state"] == "SUCCEEDED"
    assert result["observation"]["cleanup"] == {"coordinator": "borrowed"}
    assert result["observation"]["inspection"]["axes"]
    assert "observer cleanup: coordinator borrowed" in errors.getvalue()
    assert daemon.status().service_health == "healthy"


def test_follow_reports_native_failed_preparation(native):
    path, daemon = native
    project = path.parent / "projects" / "pipeline.yaml"
    value = json.loads(project.read_text())
    stage = value["pipeline"]["stages"][0]
    stage["factory"]["_target_"] = "tests.support.pipeline_execution_stages.FailOnceThenProduceStage"
    stage["config"] = {"marker_path": str(path.parent / "failed-once")}
    project.write_text(json.dumps(value))
    assert _run(path, identity="failing")[0] == 0
    output = io.StringIO()
    assert main(["runs", "follow", "--operation-id", "failing", "--deployment", str(path), "--format", "json"], stdout=output, stderr=io.StringIO()) == 5
    result = json.loads(output.getvalue())["result"]["observation"]
    assert result["operation"]["state"] == "failed"
    assert result["admission"] is None
    assert result["cleanup"] == {"coordinator": "borrowed"}
    assert daemon.operation("failing").result["cancellation_operation_id"] is None


@pytest.mark.parametrize("action", ["follow", "cancel"])
def test_observation_selection_does_not_create_uninitialized_services(tmp_path, action):
    path = _selection(tmp_path)
    output = io.StringIO()
    assert main(["runs", action, "--operation-id", "absent", "--deployment", str(path), "--format", "json"], stdout=output, stderr=io.StringIO()) == 6
    assert json.loads(output.getvalue())["error"]["details"]["coordinator"]["code"] == "unavailable"
    assert not (tmp_path / "binding.json").exists()
    assert not (tmp_path / "deployment").exists()


def test_raw_connection_is_not_parsed_as_a_deployment(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"schema_version": 1, "kind": "loom.coordinator-client", "transport": {"kind": "https"}}))
    path.chmod(0o600)
    output = io.StringIO()
    assert main(["runs", "follow", "--operation-id", "absent", "--deployment", str(path), "--format", "json"], stdout=output, stderr=io.StringIO()) == 6
    assert "deployment selection version/kind" in json.loads(output.getvalue())["error"]["message"]


@pytest.mark.parametrize("consumer", ["python", "cli"])
def test_interrupt_during_target_read_retains_completed_operation(native, monkeypatch, consumer):
    from loom.deployment import connect_deployment

    path, daemon = native
    assert _run(path, identity="read-target")[0] == 0
    assert daemon.wait_operation("read-target", timeout=30).operation.state == "applied"
    before = _counts(daemon)
    read = CoordinatorClient._native_call
    def interrupted(client, operation, *args, **kwargs):
        if operation == "admission":
            raise KeyboardInterrupt()
        return read(client, operation, *args, **kwargs)
    monkeypatch.setattr(CoordinatorClient, "_native_call", interrupted)
    if consumer == "python":
        with connect_deployment(load_deployment(path)) as client:
            observation = client.observe_run("read-target", wait=False)
            assert observation.operation is not None
            assert observation.operation.operation_id == "read-target"
            assert observation.operation.state == "applied"
            assert observation.admission is None
    else:
        output = io.StringIO()
        assert main(["runs", "follow", "--operation-id", "read-target", "--deployment", str(path), "--format", "json"], stdout=output, stderr=io.StringIO()) == 0
        result = json.loads(output.getvalue())["result"]
        assert result["detached"] == "interrupted"
        assert result["observation"]["operation"]["operation_id"] == "read-target"
        assert result["observation"]["operation"]["state"] == "applied"
        assert result["observation"]["admission"] is None
    assert _counts(daemon) == before
