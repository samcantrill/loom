"""Protected selection and visible failure-evidence diagnostics."""

import json
import logging

import pytest

from loom.queue._lifecycle_observers import LifecycleObservers, parse_event_sinks
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueConfigError
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.unit.loom.queue.test_deployment import _coordinator_config

pytestmark = pytest.mark.unit


def test_protected_observer_selection_is_inert_and_constructed_once(tmp_path):
    path = _coordinator_config(tmp_path)
    observed = tmp_path / "observed.jsonl"
    data = json.loads(path.read_text())
    data["event_sinks"] = [
        {
            "name": "test.capture",
            "factory": {
                "_target_": "tests.support.lifecycle_observers.capture",
                "path": str(observed),
            },
        }
    ]
    path.write_text(json.dumps(data))
    service = load_coordinator_service_config(path)
    assert not observed.exists()
    assert str(observed) not in repr(service)
    service.event_observers.start()
    service.event_observers.start()
    assert observed.read_text().splitlines() == [json.dumps({"constructed": True})]


@pytest.mark.parametrize(
    "selection",
    [
        {},
        [{"name": "bad name", "factory": {"_target_": "test.factory"}}],
        [{"name": "sink", "factory": {"_target_": "test.factory"}}] * 2,
        [{"name": "sink", "factory": {"_target_": "missing"}}],
    ],
)
def test_invalid_selection_refuses_configuration(selection):
    with pytest.raises(QueueConfigError):
        parse_event_sinks(selection)


def test_missing_selected_factory_refuses_startup():
    observers = LifecycleObservers(
        parse_event_sinks(
            [
                {
                    "name": "missing",
                    "factory": {"_target_": "not_installed.factory"},
                }
            ]
        )
    )
    with pytest.raises(QueueConfigError):
        observers.start()


def test_swallowed_failure_record_write_is_diagnostic_and_not_scientific(
    tmp_path,
    monkeypatch,
    caplog,
):
    import loom.queue._lifecycle_observers as module

    uri = (tmp_path / "run").as_uri()
    store = SQLitePerRunAuthorityStore(uri)
    store.create_run(uri)
    snapshot = store.open_run(uri)
    observers = LifecycleObservers()

    def fail_callback(event, context):
        raise RuntimeError("synthetic callback failed")

    def fail_persistence(*args):
        raise OSError("synthetic observer record write failed")

    observers._registry.register("failing", fail_callback)
    monkeypatch.setattr(store, "append_event_sink_failure", fail_persistence)
    monkeypatch.setattr(module, "_project_event", lambda record: None)
    with caplog.at_level(logging.ERROR):
        observers.emit(store, uri, event_type="run.created", revision=snapshot.revision)
    assert "native observer fact persistence failed" in caplog.text
    assert "synthetic observer record write failed" in caplog.text
    assert store.open_run(uri).status == snapshot.status
    assert len(store.list_audit_events(uri)) == 1
    assert store.read_event_sink_failures(uri) == ()
