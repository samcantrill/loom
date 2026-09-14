"""Native coordinator event truth and isolated callback failures."""

import json
import os
from dataclasses import replace

import pytest

from loom.coordinator import CoordinatorClient, RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue._lifecycle_observers import LifecycleObservers, parse_event_sinks
from loom.queue.deployment import load_coordinator_service_config
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.integration.queue.test_run_operations import _two_stage_service, _request
from tests.support.lifecycle_observers import captured_events, selected_capture

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_native_observer_committed_events_failure_and_no_replay(tmp_path):
    service = _two_stage_service(tmp_path)
    observed = tmp_path / "observer.jsonl"
    observers = LifecycleObservers(
        parse_event_sinks(
            [
                {
                    "name": "test.capture",
                    "factory": {
                        "_target_": "tests.support.lifecycle_observers.capture",
                        "path": str(observed),
                        "fail_completed": True,
                    },
                }
            ]
        )
    )
    assert not observed.exists()
    service = replace(service, event_observers=observers)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon,
        preparation=CoordinatorPreparation(service),
        event_observers=observers,
    )
    request = RunRequest(_request(), "target-admission")
    daemon.start()
    try:
        daemon.start_run(request, principal_id="caller")
        operation = daemon.wait_operation("prepare-1", timeout=60).operation
        assert operation.state == "applied", operation
        admission = daemon._wait("target-admission", timeout_seconds=60)
        assert admission.state.value == "SUCCEEDED", admission
        rows = [json.loads(line) for line in observed.read_text().splitlines()]
        assert sum(row.get("constructed", False) for row in rows) == 1
        events = [
            row
            for row in rows
            if "event" in row and row["event"]["run_uri"] == admission.run_uri
        ]
        kinds = [row["event"]["event_type"] for row in events]
        assert {
            "run.created",
            "run.planned",
            "run.started",
            "stage.completed",
            "run.completed",
        } <= set(kinds)
        assert (
            next(row for row in events if row["event"]["event_type"] == "run.started")[
                "status"
            ]
            == "RUNNING"
        )
        authority = SQLitePerRunAuthorityStore(admission.run_uri)
        failures = authority.read_event_sink_failures(admission.run_uri)
        assert len(failures) == 1
        assert failures[0].event_reference.event_type == "run.completed"
        assert failures[0].sink_name == "test.capture"
        commits = authority.list_output_commits(admission.run_uri)
        assert len(commits) == 2
        before = observed.read_bytes()
        daemon.start_run(request, principal_id="caller")
        assert observed.read_bytes() == before
    finally:
        daemon.stop()


def test_coordinator_restart_selects_future_callbacks_without_history_replay(tmp_path):
    _two_stage_service(tmp_path)
    config_path = tmp_path / "coordinator.json"

    def load_selected(path):
        config = json.loads(config_path.read_text())
        config["event_sinks"] = [{"name": "test.capture", "factory": {
            "_target_": "tests.support.lifecycle_observers.capture", "path": str(path),
        }}]
        config_path.write_text(json.dumps(config))
        service = load_coordinator_service_config(config_path)
        assert not path.exists()
        return service

    first_path = tmp_path / "first.jsonl"
    service = load_selected(first_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon, preparation=CoordinatorPreparation(service),
        event_observers=service.event_observers,
    )
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    request = RunRequest(_request(), "target-admission")
    daemon.start()
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.start_run(request)
        # Accepted work and callbacks continue after the submitting client detaches.
        assert daemon.wait_operation("prepare-1", timeout=60).operation.state == "applied"
        admission = daemon._wait("target-admission", timeout_seconds=60)
        assert admission.state.value == "SUCCEEDED"
        authority = SQLitePerRunAuthorityStore(admission.run_uri)
        events = authority.list_audit_events(admission.run_uri)
        assert [event.event_id for event in events] == [
            event["event_id"] for event in captured_events(first_path, admission.run_uri)
        ]
        first_bytes = first_path.read_bytes()
    finally:
        server.stop()
        daemon.stop()

    second_path = tmp_path / "second.jsonl"
    restarted_service = load_selected(second_path)
    restarted = LocalDaemon(
        restarted_service.daemon,
        preparation=CoordinatorPreparation(restarted_service),
        event_observers=restarted_service.event_observers,
    )
    restarted.start()
    try:
        assert second_path.read_text().splitlines() == [json.dumps({"constructed": True})]
        assert restarted.start_run(request, principal_id=f"uid:{os.getuid()}").state == "applied"
        assert restarted.admission_for_queue_item("target-admission").run_uri == admission.run_uri
        assert authority.list_audit_events(admission.run_uri) == events
        assert captured_events(second_path, admission.run_uri) == []
        assert first_path.read_bytes() == first_bytes
        next_request = RunRequest(
            replace(_request(), operation_id="prepare-2", run_name="target-2"),
            "second-admission",
        )
        restarted.start_run(next_request, principal_id=f"uid:{os.getuid()}")
        assert restarted.wait_operation("prepare-2", timeout=60).operation.state == "applied"
        next_admission = restarted._wait("second-admission", timeout_seconds=60)
        assert next_admission.state.value == "SUCCEEDED"
        kinds = [event["event_type"] for event in captured_events(second_path, next_admission.run_uri)]
        assert "run.started" in kinds and "run.completed" in kinds
        assert captured_events(second_path, admission.run_uri) == []
        assert first_path.read_bytes() == first_bytes
    finally:
        restarted.stop()


@pytest.mark.parametrize("outcome", ["FAILED", "CANCELLED"])
def test_native_terminal_observers_preserve_failed_and_cancelled_outcomes(tmp_path, outcome):
    service = _two_stage_service(tmp_path, failing=True)
    if outcome == "CANCELLED":
        path = tmp_path / "projects" / "pipeline.yaml"
        config = json.loads(path.read_text())
        config["pipeline"]["stages"][0]["factory"] = {
            "_target_": "tests.support.pipeline_execution_stages.EarlyStopStage"
        }
        config["pipeline"]["stages"][0]["config"] = {"message": "observer cancellation fixture"}
        path.write_text(json.dumps(config))
    observed = tmp_path / "observed.jsonl"
    service = replace(service, event_observers=selected_capture(observed))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon, preparation=CoordinatorPreparation(service),
        event_observers=service.event_observers,
    )
    daemon.start()
    try:
        daemon.start_run(RunRequest(_request(), "target-admission"), principal_id="caller")
        assert daemon.wait_operation("prepare-1", timeout=60).operation.state == "applied"
        admission = daemon._wait("target-admission", timeout_seconds=60)
        assert admission.state.value == outcome
        authority = SQLitePerRunAuthorityStore(admission.run_uri)
        assert authority.open_run(admission.run_uri).status.value == outcome
        assert authority.list_output_commits(admission.run_uri) == ()
        events = authority.list_audit_events(admission.run_uri)
        kinds = [event.event_type for event in events]
        assert kinds.count(f"run.{outcome.lower()}") == 1
        assert f"stage.{outcome.lower()}" in kinds
        assert "run.completed" not in kinds
        assert [event.event_id for event in events] == [
            event["event_id"] for event in captured_events(observed, admission.run_uri)
        ]
        terminal = next(event for event in events if event.event_type == f"run.{outcome.lower()}")
        assert terminal.payload["status"] == outcome
    finally:
        daemon.stop()
