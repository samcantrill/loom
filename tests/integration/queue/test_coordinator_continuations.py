"""Real scheduler continuations across capacity, cancellation and restart."""
from dataclasses import replace
import sqlite3
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

        def track_submit(operation_id, action, *args, **kwargs):
            future = submit(operation_id, action, *args, **kwargs)
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


def test_early_requests_survive_lost_notifications_and_restart(tmp_path, monkeypatch):
    config = replace(_daemon_config(tmp_path), remote_profiles=(
        ResidentProfileDescriptor.from_dict(_launch_profile().descriptor),
    ))
    store = LocalRunStore(config.run_store_root)
    runs = {name: _persist_sleep_run(config.run_store_root, run_name=name, stage_name="work", seconds=0.01)
            for name in ("first", "second", "third")}
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    completed = Event()
    work_ids = set()

    def drop_notification(work_id):
        work_ids.add(work_id)
        if len(work_ids) == len(runs):
            completed.set()

    daemon.start()
    principal = LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
    try:
        execution = daemon._execution
        assert execution is not None
        monkeypatch.setattr(execution, "_candidate_for_dispatch", lambda: None)
        monkeypatch.setattr(execution._ready_preparations, "_on_ready", drop_notification)
        client = daemon.client_view(principal)
        for name, uri in runs.items():
            client.submit(LocalDaemonAdmissionRequest(name, uri))
        assert completed.wait(20), daemon._service_error
        assert _supervisor_launch_count(config) == 0
        requests = {uri: store.read_stage_worker_request(uri, "work", attempt=None) for uri in runs.values()}
        assert all(requests.values())
    finally:
        daemon.stop()

    daemon.start()
    try:
        client = daemon.client_view(principal)
        for name in runs:
            assert client.wait(name, timeout_seconds=20).state.value == "SUCCEEDED"
        assert _supervisor_launch_count(config) == len(runs)
        with sqlite3.connect(config.execution_database) as conn:
            rows = conn.execute("SELECT stage_work_id FROM coordinator_assignments").fetchall()
        assert sorted(work for work, in rows) == sorted(work_ids)
        for uri, original in requests.items():
            assert store.read_stage_worker_request(uri, "work", attempt=None) == original
    finally:
        daemon.stop()


def test_cancel_while_request_build_finishes_cannot_reserve(tmp_path, monkeypatch):
    from loom.queue import _ready_preparation

    config = replace(_daemon_config(tmp_path), remote_profiles=(
        ResidentProfileDescriptor.from_dict(_launch_profile().descriptor),
    ))
    held = _persist_sleep_run(config.run_store_root, run_name="held", stage_name="work", seconds=0.01)
    peer = _persist_sleep_run(config.run_store_root, run_name="peer", stage_name="work", seconds=0.01)
    entered, release, completed = Event(), Event(), Event()
    held_work_ids = set()
    prepare = _ready_preparation.prepare_ready_request

    def hold_request(**kwargs):
        worker = prepare(**kwargs)
        if kwargs["record"].run_uri == held:
            held_work_ids.add(kwargs["record"].stage_work_id)
            entered.set()
            assert release.wait(30)
        return worker

    monkeypatch.setattr(_ready_preparation, "prepare_ready_request", hold_request)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        execution = daemon._execution
        assert execution is not None

        def notify(work_id):
            execution._ready_continuations.post(work_id)
            if work_id in held_work_ids:
                completed.set()

        monkeypatch.setattr(execution._ready_preparations, "_on_ready", notify)
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        client.submit(LocalDaemonAdmissionRequest("held", held))
        assert entered.wait(10), daemon._service_error
        client.submit(LocalDaemonAdmissionRequest("peer", peer))
        assert client.wait("peer", timeout_seconds=15).state.value == "SUCCEEDED"
        client.cancel("held")
        assert client.wait("held", timeout_seconds=10).state.value == "CANCELLED"
        release.set()
        assert completed.wait(10)
        daemon.reconcile_once()
        assert _supervisor_launch_count(config) == 1
        with sqlite3.connect(config.execution_database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri=?", (held,)).fetchone() == (0,)
    finally:
        release.set()
        daemon.stop()


def test_admission_detail_times_actual_context_request_and_reservation_waits(tmp_path, monkeypatch):
    from loom.queue import _context_timing, _ready_preparation

    monkeypatch.setenv("LOOM_QUALIFICATION_TIMINGS", "all")
    events = []
    def capture(action, *, details, **attrs):
        events.append((action, {**attrs, **details}))

    monkeypatch.setattr(_context_timing, "milestone", capture)
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
        owners = daemon.admission(admission.admission_id).owners
        assert not owners["scheduling_waits"]
        summary, = cast(list[dict], owners["scheduling_summaries"])
        assert summary["result"] == "reserved" and summary["assignment_id"]
        assert summary["admission_id"] == admission.admission_id
        assert summary["wait_ns"]["reservation"] > 0
        assert not daemon._activate_admission(admission.admission_id)
    finally:
        for _, release in gates.values():
            release.set()
        daemon.stop()
    activation = next(attrs for name, attrs in events if name == "context_consumer_advanced"
                      and attrs["consumer"] == "admission_activation")
    observed = [(name, attrs) for name, attrs in events if attrs["context_request_id"] == activation["context_request_id"]]
    assert all(attrs["admission_id"] == admission.admission_id and attrs["admission_revision"] == admission.revision
               for _, attrs in observed)
    assert [name for name, _ in observed if name != "context_cache_evicted"] == [
        "context_requested", "context_loader_started", "context_validation",
        "context_available", "context_consumer_advanced", "context_discarded",
    ]
    assert any(name == "context_validation" and attrs["result"] == "cache_hit" for name, attrs in events)
    assert any(name == "context_discarded" and attrs["owner"] == "retained" and attrs["reason"]
               for name, attrs in observed)


def test_requested_authority_read_completes_five_seconds_before_single_reservation(tmp_path, monkeypatch):
    import time
    from loom.queue import _run_observations

    config = _daemon_config(tmp_path)
    uri = _persist_sleep_run(config.run_store_root, run_name="slow-turn", stage_name="work", seconds=0.01)
    LocalDaemon.initialize(config)
    owner = _run_observations.DispatchObservations
    original = owner.begin_cycle
    held = Event()
    consumed = []
    milestone = _run_observations.milestone

    def slow_turn(self, *args):
        invalidated, epochs, _, revisions, _, _ = args
        if not held.is_set() and any(
            read.work_ids and read.future.done() and read.epochs == epochs
            and read.admission.run_uri not in invalidated and read.admission.revision == revisions.get(identity)
            for identity, read in self._reads.items()
        ):
            held.set()
            time.sleep(5.1)
        return original(self, *args)

    def capture(name, **attrs):
        if name == "dispatch_observation_consumed":
            consumed.append(attrs)
        milestone(name, **attrs)

    monkeypatch.setattr(owner, "begin_cycle", slow_turn)
    monkeypatch.setattr(_run_observations, "milestone", capture)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        client.submit(LocalDaemonAdmissionRequest("delayed", uri))
        assert client.wait("delayed", timeout_seconds=30).state.value == "SUCCEEDED"
        assert held.is_set() and _supervisor_launch_count(config) == 1
        with sqlite3.connect(config.execution_database) as conn:
            (work_id,), = conn.execute("SELECT stage_work_id FROM coordinator_assignments")
        assert any(event["stage_work_id"] == work_id and event["completion_wait_ns"] >= 5_000_000_000
                   for event in consumed)
        assert LocalRunStore(config.run_store_root).read_stage_worker_request(uri, "work", attempt=None)
    finally:
        daemon.stop()


def test_retained_input_mismatch_keeps_peer_runnable_on_only_remote_host(tmp_path, monkeypatch):
    import time
    from loom.queue import _ready_preparation as prep
    from loom.queue._remote_stage_execution import REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY
    from loom.queue.agent_sessions import AgentRegistration
    from loom.queue.errors import QueueServiceError
    from tests.unit.loom.queue.test_agent_sessions import _offer, _policy, _view

    caps = ("python", REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY)
    policy = _policy()
    profile = ResidentProfileDescriptor.from_dict(_launch_profile().descriptor)
    cfg = replace(_daemon_config(tmp_path), agent_root=None, resident_worker_launch_profile=None,
                  cpu_capacity=0, memory_capacity_bytes=0, agent_resource_providers=(), remote_profiles=(profile,),
                  agent_policy=replace(policy, agents=(replace(policy.agents[0], capabilities=caps),)))
    bad, peer = (_persist_sleep_run(cfg.run_store_root, run_name=name, stage_name="work") for name in ("a", "b"))
    store = LocalRunStore(cfg.run_store_root)
    prepare = prep.prepare_ready_request
    invalidated, observed = Event(), Event()

    def build(**kwargs):
        if kwargs["record"].run_uri == bad and not invalidated.is_set():
            request = prepare(**kwargs)
            damaged = request.to_dict()
            damaged["metadata"]["attempt_input_evidence"] = None
            store.write_stage_worker_request(bad, "work", damaged, attempt=request.attempt)
            invalidated.set()
        try:
            return prepare(**kwargs)
        except QueueServiceError as error:
            if kwargs["record"].run_uri == bad and "retained input bindings" in str(error):
                observed.set()
            raise

    monkeypatch.setattr(prep, "prepare_ready_request", build)
    LocalDaemon.initialize(cfg)
    daemon = LocalDaemon(cfg)
    daemon.start()
    try:
        view = _view(daemon)
        hello = view.handshake()
        session = view.register(AgentRegistration("reg", hello["coordinator_id"], hello["coordinator_epoch"],
                                "agent-root-a", "config-1", "inventory-1", "availability-1",
                                ("default",), caps, retirement_verifier="01"*32))
        offer = replace(_offer(session.session_id, session.coordinator_epoch), resident_profiles=(profile,))
        view.publish_offer(offer, idempotency_key="offer")
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        with daemon._reconcile_guard:
            client.submit(LocalDaemonAdmissionRequest("bad", bad))
            client.submit(LocalDaemonAdmissionRequest("peer", peer))
        assert observed.wait(20), daemon._service_error
        until = time.monotonic() + 20
        while time.monotonic() < until:
            with sqlite3.connect(cfg.execution_database) as conn:
                rows = conn.execute("SELECT run_uri FROM coordinator_assignments WHERE state != 'released'").fetchall()
            if rows:
                break
            time.sleep(.05)
        assert rows == [(peer,)], (rows, daemon._service_error)
    finally:
        daemon.stop()
