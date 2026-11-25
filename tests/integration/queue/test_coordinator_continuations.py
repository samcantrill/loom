"""Real scheduler continuations across capacity, cancellation and restart."""
from dataclasses import replace
from threading import Event
from typing import cast

import pytest

from loom.pipeline.stores import LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue import _preparation_operations as preparation
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from tests.integration.queue.test_local_daemon_production import (
    _daemon_config, _launch_profile, _persist_sleep_run, _supervisor_launch_count,
)
from tests.integration.queue.test_preparation_operations import _request, _service


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("cancel_oldest", [False, True])
def test_free_bulk_slot_revisits_waiting_owner_outside_discovery(tmp_path, monkeypatch, cancel_oldest):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    occupied = [Event(), Event()]
    queued, off_page, captured = Event(), Event(), Event()
    captures = []
    try:
        bulk = daemon._result_verifications.bulk
        submit, capture, reconcile = bulk.submit, preparation._capture_owned_input, daemon._preparations.reconcile

        def track_submit(operation_id, action, *args):
            future = submit(operation_id, action, *args)
            if action == "preparation_input_capture" and operation_id == "later" and future is None:
                queued.set()
            return future

        def track_capture(guards, config, request, *args):
            captures.append(request.operation_id)
            captured.set()
            return capture(guards, config, request, *args)

        def skip_discovery(priorities=()):
            if off_page.is_set():
                daemon._preparations._cursor = 2**50
            reconcile(priorities)

        monkeypatch.setattr(bulk, "submit", track_submit)
        monkeypatch.setattr(preparation, "_capture_owned_input", track_capture)
        monkeypatch.setattr(daemon._preparations, "reconcile", skip_discovery)
        with daemon._reconcile_guard:
            for index, gate in enumerate(occupied):
                assert bulk.submit(str(index), "occupy", gate.wait, 30) is not None
            for name in ("oldest", "later"):
                daemon.prepare_run(replace(_request(), operation_id=name, run_name=name), principal_id="caller")
        assert queued.wait(10)
        with daemon._reconcile_guard:
            off_page.set()
            if cancel_oldest:
                daemon.cancel_preparation("oldest", principal_id="caller")
        occupied[0].set()
        assert captured.wait(10), daemon._service_error
        assert captures[0] == ("later" if cancel_oldest else "oldest")
        if cancel_oldest:
            assert "oldest" not in captures
    finally:
        off_page.clear()
        for gate in occupied:
            gate.set()
        daemon.stop()


def test_worker_request_precedes_host_eligibility_and_restart_resumes_attempt(tmp_path, monkeypatch):
    from loom.queue import _ready_preparation
    from loom.queue._scheduling_waits import SchedulingWaits

    config = replace(_daemon_config(tmp_path), remote_profiles=(
        ResidentProfileDescriptor.from_dict(_launch_profile().descriptor),
    ))
    run_uri = _persist_sleep_run(config.run_store_root, run_name="remote-ready", stage_name="work", seconds=0.01)
    store = LocalRunStore(config.run_store_root)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    written, host_wait = Event(), Event()
    prepare, record = _ready_preparation.prepare_ready_request, SchedulingWaits.record

    def watch_request(**kwargs):
        worker = prepare(**kwargs)
        written.set()
        return worker

    def watch_wait(self, uri, stage, boundary):
        record(self, uri, stage, boundary)
        if uri == run_uri and boundary == "host_eligibility":
            host_wait.set()

    monkeypatch.setattr(_ready_preparation, "prepare_ready_request", watch_request)
    monkeypatch.setattr(SchedulingWaits, "record", watch_wait)
    daemon.start()
    principal = LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    try:
        monkeypatch.setattr(daemon._execution, "_candidate_for_dispatch", lambda: None)
        admission = daemon.client_view(principal).submit(LocalDaemonAdmissionRequest("test", run_uri))
        assert written.wait(15), daemon._service_error
        assert host_wait.wait(10)
        assert _supervisor_launch_count(config) == 0
        request = store.read_stage_worker_request(run_uri, "work", attempt=None)
        assert request is not None
        waits = cast(list[dict], daemon.admission(admission.admission_id).owners["scheduling_waits"])
        assert any(row["boundary"] == "host_eligibility" and row["elapsed_nanoseconds"] >= 0 for row in waits)
    finally:
        daemon.stop()

    daemon.start()
    try:
        assert daemon.client_view(principal).wait("test", timeout_seconds=20).state.value == "SUCCEEDED"
        assert _supervisor_launch_count(config) == 1
        assert store.read_stage_worker_request(run_uri, "work", attempt=None) == request
    finally:
        daemon.stop()


def test_admission_detail_times_actual_context_request_and_reservation_waits(tmp_path, monkeypatch):
    from loom.queue import _ready_preparation

    config = _daemon_config(tmp_path)
    run_uri = _persist_sleep_run(config.run_store_root, run_name="waits", stage_name="work", seconds=0.01)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    gates = {name: (Event(), Event()) for name in ("preparation", "request_preparation", "reservation")}
    try:
        execution = daemon._execution
        assert execution is not None

        def hold(boundary, fn):
            def observe(*args, **kwargs):
                entered, release = gates[boundary]
                entered.set()
                assert release.wait(20)
                return fn(*args, **kwargs)
            return observe

        monkeypatch.setattr(execution, "prepare_admission_context",
                            hold("preparation", execution.prepare_admission_context))
        monkeypatch.setattr(_ready_preparation, "prepare_ready_request",
                            hold("request_preparation", _ready_preparation.prepare_ready_request))
        monkeypatch.setattr(execution.coordinator, "reserve", hold("reservation", execution.coordinator.reserve))
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        admission = client.submit(LocalDaemonAdmissionRequest("observed", run_uri))
        for boundary, (entered, release) in gates.items():
            assert entered.wait(10), daemon._service_error
            waits = cast(list[dict], daemon.admission(admission.admission_id).owners["scheduling_waits"])
            assert any(row["boundary"] == boundary and row["elapsed_nanoseconds"] >= 0 for row in waits), waits
            release.set()
        assert client.wait("observed", timeout_seconds=15).state.value == "SUCCEEDED"
        assert not daemon.admission(admission.admission_id).owners["scheduling_waits"]
    finally:
        for _, release in gates.values():
            release.set()
        daemon.stop()
