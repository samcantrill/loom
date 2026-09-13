"""Native coordinator event truth and isolated callback failures."""

import json
from dataclasses import replace

import pytest

from loom.coordinator import RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue._lifecycle_observers import LifecycleObservers, parse_event_sinks
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.integration.queue.test_run_operations import _two_stage_service, _request

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
