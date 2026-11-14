"""Native scheduling and cancellation remain live during a result byte audit."""

from dataclasses import replace
from threading import Event

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue._action_result_resolution import ActionResultResolution
from tests.integration.queue.test_installed_node_contracts import _start, _text_service
from tests.integration.queue.test_preparation_operations import _result
from tests.integration.queue.test_reconciled_runs import _reconciled_request


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_independent_fresh_run_finishes_while_result_audit_is_blocked(tmp_path, monkeypatch):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release = Event(), Event()
    verify = ActionResultResolution._verify_artifacts

    def hold_first_audit(owner, outputs):
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=120), "result audit barrier was not released"
        return verify(owner, outputs)

    monkeypatch.setattr(ActionResultResolution, "_verify_artifacts", hold_first_audit)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "held-result")
        assert entered.wait(timeout=40), daemon._service_error
        # Cancellation acceptance detaches demand even though byte IO cannot stop.
        daemon.cancel_run_operation("held-result", principal_id="caller")
        uri = first["prepared_run"]["run_uri"]
        with daemon._connection() as conn:
            demands = conn.execute(
                "SELECT state FROM action_demands WHERE run_uri = ?", (uri,)
            ).fetchall()
        assert demands and all(row[0] == "detached" for row in demands)
        assert not release.is_set()
        daemon.start_run(
            replace(_reconciled_request("independent"), fresh_stages=("author",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        second = _result(operation)
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        # The blocked operation still occupies its real worker slot.
        assert daemon._result_verifications.running()
        release.set()
        settled = daemon._wait(first["queue_item_id"], timeout_seconds=40)
        assert settled.state.value in {"SUCCEEDED", "CANCELLED"}, (
            settled, daemon._service_error,
        )
    finally:
        release.set()
        daemon.stop()


def test_cancelled_report_hydration_cannot_publish_and_other_run_progresses(tmp_path, monkeypatch):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    read_report = CoordinatorPreparation.read_report

    def hold_first_report(owner, *args):
        if not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "report barrier was not released"
                return read_report(owner, *args)
            finally:
                finished.set()
        return read_report(owner, *args)

    monkeypatch.setattr(CoordinatorPreparation, "read_report", hold_first_report)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("held-report"), principal_id="caller")
        assert entered.wait(timeout=40), daemon._service_error
        daemon.cancel_run_operation("held-report", principal_id="caller")
        cancelled = daemon.wait_operation("held-report", timeout=30).operation
        assert cancelled.state == "cancelled", cancelled.to_dict()
        assert _result(cancelled)["prepared_run"] is None
        second = _start(daemon, "independent-report")
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        assert daemon._result_verifications.running()
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        current = daemon.wait_operation("held-report", timeout=10).operation
        assert current.state == "cancelled"
        assert _result(current)["prepared_run"] is None
    finally:
        release.set()
        daemon.stop()


def test_publication_claim_preserves_cancellation_while_independent_work_finishes(tmp_path, monkeypatch):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release = Event(), Event()
    publish = CoordinatorPreparation.publish_target

    def hold_first_publication(owner, *args):
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=120), "publication barrier was not released"
        return publish(owner, *args)

    monkeypatch.setattr(CoordinatorPreparation, "publish_target", hold_first_publication)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("held-publication"), principal_id="caller")
        assert entered.wait(timeout=40), daemon._service_error
        daemon.cancel_run_operation("held-publication", principal_id="caller")
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT state, cancellation_requested FROM preparation_operations WHERE operation_id = ?",
                ("held-publication",),
            ).fetchone()
        assert tuple(row) == ("applying", 1)
        daemon.start_run(
            replace(_reconciled_request("other-publication"), fresh_stages=("author",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("other-publication", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        release.set()
        cancelled = daemon.wait_operation("held-publication", timeout=30).operation
        assert cancelled.state == "cancelled", (cancelled.to_dict(), daemon._service_error)
        prepared = _result(cancelled)["prepared_run"]
        assert prepared is not None  # Cancellation does not undo owned publication.
        with daemon._connection() as conn:
            assert conn.execute(
                "SELECT 1 FROM managed_admissions WHERE run_uri = ?", (prepared["run_uri"],)
            ).fetchone() is None
    finally:
        release.set()
        daemon.stop()


def test_shutdown_retains_deployment_ownership_until_publication_finishes(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from loom.queue.errors import QueueServiceError

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release = Event(), Event()
    publish = CoordinatorPreparation.publish_target

    def hold_publication(owner, *args):
        entered.set()
        assert release.wait(timeout=60)
        return publish(owner, *args)

    monkeypatch.setattr(CoordinatorPreparation, "publish_target", hold_publication)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    contender = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    executor = ThreadPoolExecutor(max_workers=1)
    stopped = None
    try:
        daemon.start_run(_reconciled_request("stop-publication"), principal_id="caller")
        assert entered.wait(timeout=40), daemon._service_error
        stopped = executor.submit(daemon.stop)
        assert daemon._stop.wait(timeout=10)
        assert not stopped.done()
        with pytest.raises(QueueServiceError):
            contender.start()
        release.set()
        stopped.result(timeout=30)
        assert daemon._coordinator_lock is None
        # The new owner reconciles the retained applying claim by exact replay.
        contender.start()
        operation = contender.wait_operation("stop-publication", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), contender._service_error)
        outcome = contender._wait(_result(operation)["queue_item_id"], timeout_seconds=40)
        assert outcome.state.value == "SUCCEEDED", (outcome, contender._service_error)
    finally:
        release.set()
        if stopped is not None:
            stopped.result(timeout=30)
        else:
            daemon.stop()
        contender.stop()
        executor.shutdown(wait=True)


def test_cancelled_child_construction_never_dispatches_and_other_run_progresses(tmp_path, monkeypatch):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    prepare = CoordinatorPreparation.prepare_child
    held_name = []

    def hold_first_child(owner, *args):
        if not entered.is_set():
            held_name.append(args[2])
            entered.set()
            try:
                assert release.wait(timeout=120), "child construction barrier was not released"
                return prepare(owner, *args)
            finally:
                finished.set()
        return prepare(owner, *args)

    monkeypatch.setattr(CoordinatorPreparation, "prepare_child", hold_first_child)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("held-child"), principal_id="caller")
        assert entered.wait(timeout=40), daemon._service_error
        daemon.cancel_run_operation("held-child", principal_id="caller")
        cancelled = daemon.wait_operation("held-child", timeout=30).operation
        assert cancelled.state == "cancelled", cancelled.to_dict()
        second = _start(daemon, "independent-child")
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT dispatch_claimed, child_admission_id FROM preparation_operations WHERE operation_id = ?",
                ("held-child",),
            ).fetchone()
            assert tuple(row) == (0, None)
            assert conn.execute(
                "SELECT 1 FROM managed_admissions WHERE queue_item_id = ?", (held_name[0],)
            ).fetchone() is None
    finally:
        release.set()
        daemon.stop()


def test_slow_capture_keeps_control_live_and_cancellation_waits_for_safe_cleanup(tmp_path, monkeypatch):
    from loom.queue import _preparation_operations as operations

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release = Event(), Event()
    capture = operations.capture_shared_input

    def hold_first_capture(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=120), "capture barrier was not released"
        return capture(*args, **kwargs)

    monkeypatch.setattr(operations, "capture_shared_input", hold_first_capture)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("held-capture"), principal_id="caller")
        assert entered.wait(timeout=30), daemon._service_error
        daemon.cancel_run_operation("held-capture", principal_id="caller")
        second = _start(daemon, "independent-capture")
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT state, cancellation_requested, child_admission_id FROM preparation_operations WHERE operation_id = ?",
                ("held-capture",),
            ).fetchone()
        assert tuple(row) == ("pending", 1, None)
        assert not release.is_set()
        release.set()
        cancelled = daemon.wait_operation("held-capture", timeout=30).operation
        assert cancelled.state == "cancelled", cancelled.to_dict()
        assert _result(cancelled)["input_receipt"] is not None
        assert _result(cancelled)["preparation_admission_id"] is None
        assert _result(cancelled)["prepared_run"] is None
    finally:
        release.set()
        daemon.stop()


def test_candidate_inspection_does_not_repeat_report_loading_or_block_other_runs(tmp_path, monkeypatch):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    capture = CoordinatorPreparation.capture_candidate
    read_report = CoordinatorPreparation.read_report
    reads = []

    def record_report(owner, *args):
        reads.append(args[2].operation_id)
        return read_report(owner, *args)

    def hold_candidate(owner, *args):
        if not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "candidate barrier was not released"
                return capture(owner, *args)
            finally:
                finished.set()
        return capture(owner, *args)

    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        original = _start(daemon, "candidate-original")
        assert daemon._wait(original["queue_item_id"], timeout_seconds=40).state.value == "SUCCEEDED"
        monkeypatch.setattr(CoordinatorPreparation, "read_report", record_report)
        monkeypatch.setattr(CoordinatorPreparation, "capture_candidate", hold_candidate)
        daemon.start_run(_reconciled_request("held-candidate"), principal_id="caller")
        assert entered.wait(timeout=40), daemon._service_error
        before = reads.count("held-candidate")
        assert before == 1
        daemon.start_run(
            replace(_reconciled_request("candidate-independent"), fresh_stages=("author",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("candidate-independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert reads.count("held-candidate") == before
        daemon.cancel_run_operation("held-candidate", principal_id="caller")
        cancelled = daemon.wait_operation("held-candidate", timeout=30).operation
        assert cancelled.state == "cancelled", cancelled.to_dict()
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        assert daemon.wait_operation("held-candidate", timeout=10).operation.state == "cancelled"
    finally:
        release.set()
        daemon.stop()


def test_action_contract_loading_is_async_and_cancelled_completion_cannot_launch(tmp_path, monkeypatch):
    from loom.queue import _action_result_resolution as resolution

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    load = resolution.load_contract_report

    def hold_target_contract(store, run_uri, **kwargs):
        if "/loom-preparation-" not in run_uri and not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "action contract barrier was not released"
                return load(store, run_uri, **kwargs)
            finally:
                finished.set()
        return load(store, run_uri, **kwargs)

    monkeypatch.setattr(resolution, "load_contract_report", hold_target_contract)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "held-contract")
        assert entered.wait(timeout=30), daemon._service_error
        daemon.cancel_run_operation("held-contract", principal_id="caller")
        cancelled = daemon._wait(first["queue_item_id"], timeout_seconds=30)
        assert cancelled.state.value == "CANCELLED", (cancelled, daemon._service_error)
        daemon.start_run(
            replace(_reconciled_request("contract-independent"), fresh_stages=("author",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("contract-independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        factory = service.daemon.coordinator_authority_factory
        snapshot = factory(first["prepared_run"]["run_uri"]).open_run(first["prepared_run"]["run_uri"])
        assert all(not stage.attempts for stage in snapshot.stages)
        with daemon._connection() as conn:
            assert conn.execute(
                "SELECT 1 FROM action_claims WHERE owner_run_uri = ?",
                (first["prepared_run"]["run_uri"],),
            ).fetchone() is None
    finally:
        release.set()
        daemon.stop()


def test_reuse_result_audit_is_async_and_cancellation_cannot_bind_late_proof(tmp_path, monkeypatch):
    from tests.integration.queue.test_action_result_resolution import _rename_graph

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    verify = ActionResultResolution._verify_artifacts

    def hold_reuse_audit(owner, outputs):
        if not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "reuse result barrier was not released"
                return verify(owner, outputs)
            finally:
                finished.set()
        return verify(owner, outputs)

    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        original = _start(daemon, "reuse-proof-original")
        assert daemon._wait(original["queue_item_id"], timeout_seconds=40).state.value == "SUCCEEDED"
        monkeypatch.setattr(ActionResultResolution, "_verify_artifacts", hold_reuse_audit)
        _rename_graph(tmp_path)
        consumer = _start(daemon, "held-reuse-proof")
        assert entered.wait(timeout=40), daemon._service_error
        daemon.cancel_run_operation("held-reuse-proof", principal_id="caller")
        cancelled = daemon._wait(consumer["queue_item_id"], timeout_seconds=30)
        assert cancelled.state.value == "CANCELLED", (cancelled, daemon._service_error)
        daemon.start_run(
            replace(_reconciled_request("proof-independent"), fresh_stages=("write-renamed",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("proof-independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        uri = consumer["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        snapshot = factory(uri).open_run(uri)
        assert all(stage.result_binding is None and not stage.attempts for stage in snapshot.stages)
        with daemon._connection() as conn:
            demands = conn.execute(
                "SELECT state, binding_json FROM action_demands WHERE run_uri = ?", (uri,),
            ).fetchall()
        assert demands and all(tuple(row) == ("detached", None) for row in demands)
    finally:
        release.set()
        daemon.stop()


@pytest.mark.parametrize("cancel", [False, True])
def test_verifier_report_load_is_async_and_late_completion_respects_demand(tmp_path, monkeypatch, cancel):
    from loom.queue import _preparation_operations as preparation
    from tests.integration.queue.test_action_result_resolution import _rename_graph

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    load = preparation._load_verification_report
    reads = []

    def hold_report(root, reference, requested, operation_id):
        reads.append(operation_id)
        if not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "verifier report barrier was not released"
                return load(root, reference, requested, operation_id)
            finally:
                finished.set()
        return load(root, reference, requested, operation_id)

    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        original = _start(daemon, "report-proof-original")
        assert daemon._wait(original["queue_item_id"], timeout_seconds=40).state.value == "SUCCEEDED"
        monkeypatch.setattr(preparation, "_load_verification_report", hold_report)
        _rename_graph(tmp_path)
        consumer = _start(daemon, "held-verifier-report")
        assert entered.wait(timeout=40), daemon._service_error
        held_operation = reads[0]
        if cancel:
            daemon.cancel_run_operation("held-verifier-report", principal_id="caller")
            cancelled = daemon._wait(consumer["queue_item_id"], timeout_seconds=30)
            assert cancelled.state.value == "CANCELLED", (cancelled, daemon._service_error)
            assert held_operation not in daemon._preparations._verification_reports
        daemon.start_run(
            replace(_reconciled_request("report-independent"), fresh_stages=("write-renamed",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("report-independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert reads.count(held_operation) == 1
        assert not release.is_set()
        release.set()
        assert finished.wait(timeout=20)
        outcome = daemon._wait(consumer["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == ("CANCELLED" if cancel else "SUCCEEDED"), (outcome, daemon._service_error)
        daemon.reconcile_once()
        uri = consumer["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        snapshot = factory(uri).open_run(uri)
        assert all(not stage.attempts for stage in snapshot.stages)
        if cancel:
            assert all(stage.result_binding is None for stage in snapshot.stages)
        else:
            assert all(stage.result_binding is not None for stage in snapshot.stages)
        assert held_operation not in daemon._preparations._verification_reports
    finally:
        release.set()
        daemon.stop()


def test_worker_request_preparation_is_async_and_cancellation_prevents_dispatch(tmp_path, monkeypatch):
    from loom.queue import local_daemon_execution as execution

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, release, finished = Event(), Event(), Event()
    prepare = execution.prepare_stage_attempt

    def hold_request(**kwargs):
        if "/loom-preparation-" not in kwargs["run_uri"] and not entered.is_set():
            entered.set()
            try:
                assert release.wait(timeout=120), "worker request barrier was not released"
                return prepare(**kwargs)
            finally:
                finished.set()
        return prepare(**kwargs)

    monkeypatch.setattr(execution, "prepare_stage_attempt", hold_request)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "held-worker-request")
        assert entered.wait(timeout=40), daemon._service_error
        daemon.cancel_run_operation("held-worker-request", principal_id="caller")
        cancelled = daemon._wait(first["queue_item_id"], timeout_seconds=30)
        assert cancelled.state.value == "CANCELLED", (cancelled, daemon._service_error)
        daemon.start_run(
            replace(_reconciled_request("worker-independent"), fresh_stages=("author",)),
            principal_id="caller",
        )
        operation = daemon.wait_operation("worker-independent", timeout=50).operation
        assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
        outcome = daemon._wait(_result(operation)["queue_item_id"], timeout_seconds=50)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        assert not release.is_set()
        uri = first["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        before = factory(uri).open_run(uri)
        release.set()
        assert finished.wait(timeout=20)
        daemon.reconcile_once()
        after = factory(uri).open_run(uri)
        assert after.status == before.status
        assert after.stages == before.stages
        import sqlite3

        with sqlite3.connect(service.daemon.execution_database) as conn:
            assert conn.execute(
                "SELECT 1 FROM coordinator_assignments WHERE run_uri = ?", (uri,),
            ).fetchone() is None
    finally:
        release.set()
        daemon.stop()


def test_context_failure_withdraws_waiters_without_releasing_running_bulk_io(tmp_path, monkeypatch):
    from threading import Barrier
    from loom.queue.local_daemon_execution import LocalDaemonExecution

    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    entered, fail_context, unavailable, release = Event(), Event(), Event(), Event()
    occupied = Barrier(3)
    load = LocalDaemonExecution.load_context

    def unavailable_target(owner, admission):
        if "/loom-preparation-" not in admission.run_uri:
            entered.set()
            assert fail_context.wait(timeout=30)
            raise OSError("temporarily unavailable retained context")
        return load(owner, admission)

    monkeypatch.setattr(LocalDaemonExecution, "load_context", unavailable_target)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    health = daemon._record_admission_health

    def observe_health(admission_id, state):
        health(admission_id, state)
        if state == "unavailable":
            unavailable.set()

    monkeypatch.setattr(daemon, "_record_admission_health", observe_health)
    daemon.start()
    try:
        run = _start(daemon, "unavailable-context")
        assert entered.wait(timeout=10)
        uri = run["prepared_run"]["run_uri"]
        bulk = daemon._result_verifications.bulk

        def occupy():
            occupied.wait(timeout=10)
            assert release.wait(timeout=30)

        with daemon._reconcile_guard:
            running = [bulk.submit(str(index), "occupied", occupy) for index in range(2)]
            assert all(future is not None for future in running)
            occupied.wait(timeout=10)
            for scope in (("run", uri), ("dispatch", uri, "work", "execution")):
                with bulk.offering(scope):
                    assert bulk.submit("waiting", "request", lambda: None) is None
        fail_context.set()
        assert unavailable.wait(timeout=10), daemon._service_error
        with daemon._reconcile_guard:
            assert bulk.scopes(("run", uri)) == set()
            assert bulk.scopes(("dispatch", uri)) == set()
            assert bulk.running()
        release.set()
        for future in running:
            future.result(timeout=10)
    finally:
        fail_context.set()
        release.set()
        daemon.stop()
