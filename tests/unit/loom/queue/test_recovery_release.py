"""Contained Slurm release survives a durable unavailable recovery outcome."""

import base64
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from loom.pipeline.executors.slurm.ready_stage import (
    JobPrivateFilePrepared, ReadyStageState, SlurmReadyStageRequest,
    SlurmReadyStageSubmission,
)
from loom.queue import _shared_recovery as recovery
from loom.queue.errors import QueueConflictError
from loom.queue.local_daemon_execution import LocalDaemonExecution
from tests.unit.loom.queue.test_shared_recovery import _workspace, _retention_database
from tests.unit.loom.queue.test_slurm_admission import ReservationFixture


@pytest.mark.parametrize("deferred", [False, True])
def test_slurm_ack_replays_budget_outcome_before_releasing_gpu(tmp_path, monkeypatch, deferred):
    limits = {"max_payload_bytes": 1, "max_members": 100, "max_manifest_bytes": 4096}
    workspace, shared_profile, _ = _workspace(tmp_path, limits=limits)
    fixture = ReservationFixture(tmp_path)
    assignment, arguments = fixture.candidate("cancelled", 1)
    delivery = arguments["delivery"]
    delivery = replace(delivery, fingerprint=workspace.request().fingerprint, worker_metadata={
        **workspace.request().worker_metadata,
        recovery.WIRE: {"schema_version": 1, "root_id": "outputs", "predecessors": [],
                        "tree": recovery.current_relative(delivery, assignment.agent_id)},
    })
    fixture.store.reserve(assignment, **{**arguments, "delivery": delivery})
    fixture.store.advance(assignment.assignment_id, expected="reserved", next_state="bound")
    capability = b"fixture-only-capability"
    verifier = hashlib.sha256(capability).hexdigest()
    fixture.store.mark_submission_eligible(
        assignment.assignment_id, operation_id=assignment.operation_id,
        request_digest=assignment.request_digest, profile_id=assignment.profile_id,
        profile_descriptor=assignment.profile_descriptor, verifier=verifier,
    )
    fixture.store.record_submission(assignment.assignment_id, state="accepted", job_id="123", cluster=None)
    fixture.store.register_bootstrap(
        assignment.operation_id, request_digest=assignment.request_digest, job_id="123",
        cluster=None, incarnation="incarnation", capability=base64.b64encode(capability).decode(),
    )
    fixture.store.mark_input_ready(assignment.assignment_id, "incarnation")
    fixture.store.mark_granted(assignment.assignment_id, "incarnation", "fence-1")
    fixture.store.consume_start(assignment.assignment_id)
    fixture.store.mark_running(assignment.assignment_id, "incarnation", "fence-1", "process-1")
    # The native cancellation path has already fenced authority. Its accepted
    # exact provider proof is replaying after logical release, as on restart.
    fixture.store.mark_contained_cancelled(assignment.assignment_id)
    roots = shared_profile.shared_roots
    current = recovery.current_tree(delivery, roots, owner=recovery._owner(delivery, assignment.agent_id, "fence-1"))
    (current / "checkpoint").write_bytes(b"complete progress")
    database = tmp_path / "control.sqlite"
    with _retention_database(database) as conn:
        conn.execute("CREATE TABLE agent_coordinator_references (reference_kind TEXT, reference_id TEXT, resolved INTEGER)")
        conn.execute("INSERT INTO agent_coordinator_references VALUES ('assignment', ?, 0)", (assignment.assignment_id,))
    conn.close()

    @contextmanager
    def connection(*args):
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    proof = {"assignment_id": assignment.assignment_id, "job_id": "123", "execution_fence": "fence-1"}
    projected = []
    execution = SimpleNamespace(
        slurm_assignments=fixture.store,
        slurm_submissions=SimpleNamespace(acknowledge=projected.append),
        _recovery_retains_assignment=lambda _: False,
        _slurm_task=lambda _: {"containment_request": proof},
        _slurm_profile=lambda *args: fixture.profile,
        _attempt_cancel_requested=lambda *args: True,
        _daemon_owner=lambda: SimpleNamespace(_connection=connection),
        config=SimpleNamespace(coordinator_shared_roots=roots, control_database=database,
                               connect_database=connection),
    )
    submission = SlurmReadyStageSubmission(
        SlurmReadyStageRequest.from_dict(arguments["request_json"]), ReadyStageState.ACCEPTED,
        "2020-01-01T00:00:00Z", job_id="123", cancel_requested=True,
        capability=JobPrivateFilePrepared("receipt", verifier, "2030-01-01T00:00:00Z",
                                          str(tmp_path / "capability"), "fixture"),
    )
    evidence = {
        "schema_version": 1, "sequence": 1, "assignment": assignment.to_dict(),
        "submission": submission.to_dict(), "provider_released": False,
        "release": {"state": "CONTAINED", "echo": proof}, "recovery_evidence": None,
    }

    def acknowledge(value):
        from loom.queue.local_daemon_execution import _SlurmRetentionRequired
        try:
            return LocalDaemonExecution.acknowledge_slurm_agent(
                execution, assignment.agent_id, assignment.agent_root_id, value,
                _defer_retention=deferred,
            )
        except _SlurmRetentionRequired as continuation:
            assert fixture.reopen().reserved_gpu_count() == 1
            with pytest.raises(QueueConflictError, match="retention context changed"):
                LocalDaemonExecution.acknowledge_slurm_agent(
                    execution, assignment.agent_id, assignment.agent_root_id, value,
                    _retained=continuation,
                )
            continuation.retain()
            assert fixture.reopen().reserved_gpu_count() == 1
            with monkeypatch.context() as changed:
                changed.setattr(execution, "_recovery_retains_assignment", lambda _: True)
                with pytest.raises(QueueConflictError, match="frozen by guarded recovery"):
                    LocalDaemonExecution.acknowledge_slurm_agent(
                        execution, assignment.agent_id, assignment.agent_root_id, value,
                        _retained=continuation,
                    )
            assert fixture.reopen().reserved_gpu_count() == 1
            return LocalDaemonExecution.acknowledge_slurm_agent(
                execution, assignment.agent_id, assignment.agent_root_id, value,
                _retained=continuation,
            )

    acknowledge(evidence)
    assert fixture.reopen().reserved_gpu_count() == 1
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 0
    evidence = {**evidence, "sequence": 2, "provider_released": True}
    with pytest.raises(QueueConflictError, match="exact containment"):
        acknowledge({**evidence, "release": {"state": "CONTAINED", "echo": {}}})
    assert fixture.reopen().reserved_gpu_count() == 1

    def crash_before_release(*args):
        raise OSError("crash after retention commit")

    with monkeypatch.context() as patch:
        patch.setattr(fixture.store, "release", crash_before_release)
        with pytest.raises(OSError, match="after retention"):
            acknowledge(evidence)
    assert fixture.reopen().reserved_gpu_count() == 1
    with connection() as conn:
        assert conn.execute("SELECT operation FROM agent_receipts").fetchone()[0] == "seal_unavailable"
        rows = recovery.assignment_rows(conn, assignment.run_uri, slurm_assignments=fixture.reopen())
        assert len(rows) == 1 and rows[0]["recovery_json"] is None
        assert json.loads(rows[0]["recovery_failure_json"])["reason"]["code"] == "budget_exceeded"

    def no_rescan(*args):
        raise AssertionError("replay rescanned unavailable payload")

    monkeypatch.setattr(recovery, "inventory", no_rescan)
    execution.slurm_assignments = fixture.reopen()
    assert acknowledge(evidence) == {"sequence": 2, "cancel_requested": True}
    assert acknowledge(evidence) == {"sequence": 2, "cancel_requested": True}
    assert fixture.reopen().reserved_gpu_count() == 0
    record = fixture.reopen().read(assignment.assignment_id)
    assert record.state == "released" and record.report is None
    assert (current / "checkpoint").read_bytes() == b"complete progress"
    from loom.pipeline.status import StageStatus
    from loom.queue.local_daemon import LocalDaemonAdmissionState

    admission = SimpleNamespace(state=LocalDaemonAdmissionState.CANCELLED)
    execution._daemon_owner = lambda: SimpleNamespace(_connection=connection, admission_for_run_uri=lambda _: admission)
    stage = SimpleNamespace(stage_name=assignment.stage_name, status=StageStatus.CANCELLED)
    execution._authority_store = lambda _: SimpleNamespace(open_run=lambda _: SimpleNamespace(stages=[stage]))
    from loom.queue._continuation import ContinuationConflict
    from loom.queue._slurm_retry import reconcile

    assert reconcile(execution, assignment.run_uri) == ContinuationConflict(
        "slurm_recovery_retention_budget_exceeded"
    )
    with connection() as conn:
        assert conn.execute("SELECT resolved FROM agent_coordinator_references").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 1


@pytest.mark.parametrize("operation", ["retention", "publication"])
def test_slow_slurm_retention_yields_global_lock_then_revalidates_session(operation):
    from threading import Event, RLock, Thread
    from loom.queue.agent_sessions import AgentSessionService
    from loom.queue.local_daemon_execution import _SlurmRetentionRequired, _SlurmPublicationRequired
    from loom.queue._publication_guards import PublicationGuards

    entered, proceed = Event(), Event()
    lock = RLock()
    calls, results, failures = [], [], []
    daemon = SimpleNamespace(_cycle_lock=lock, _publication_guards=PublicationGuards())
    execution = SimpleNamespace(config=SimpleNamespace(coordinator_shared_roots={}))
    evidence = {"provider_released": True, "assignment": {"assignment_id": "assignment-1"}}
    if operation == "publication":
        evidence = {"result_operation": "commit", "assignment_id": "assignment-1"}
        continuation = _SlurmPublicationRequired(execution, SimpleNamespace(), "fence")
    else:
        continuation = _SlurmRetentionRequired(execution, SimpleNamespace(), evidence)

    def retain():
        entered.set()
        assert proceed.wait(5)
        continuation.completed = True

    continuation.retain = continuation.prepare = retain
    current_session = ["original"]

    def locked(session_id, epoch, value, cursor, **options):
        if options.get("_pending_only"):
            return None
        calls.append(options)
        if session_id != current_session[0]:
            raise QueueConflictError("session replaced while sealing")
        if options.get("_defer_retention") or options.get("_defer_publication"):
            raise continuation
        assert options.get("_retained", options.get("_publication")) is continuation and continuation.completed
        return {"sequence": 1}

    service = SimpleNamespace(_daemon=daemon, _slurm_work_locked=locked)

    def release():
        try:
            results.append(AgentSessionService.slurm_work(service, "original", "epoch", evidence))
        except Exception as error:
            failures.append(error)

    worker = Thread(target=release)
    worker.start()
    try:
        assert entered.wait(5)
        assert lock.acquire(timeout=1), "slow sealing retained the global coordinator lock"
        try:
            # Session replacement/control can progress while filesystem IO waits.
            current_session[0] = "replacement"
        finally:
            lock.release()
    finally:
        proceed.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not results
    assert len(calls) == 2
    assert len(failures) == 1 and isinstance(failures[0], QueueConflictError)


@pytest.mark.parametrize("operation", ["retention", "publication"])
def test_embedded_slurm_seals_on_worker_without_acknowledging_early(operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from loom.queue._publication_guards import PublicationGuards
    from loom.queue.local_daemon_execution import _SlurmRetentionRequired, _SlurmPublicationRequired

    entered, proceed, wake = Event(), Event(), Event()
    record = SimpleNamespace(assignment=SimpleNamespace(
        assignment_id="assignment-1", agent_id="embedded", agent_root_id="root",
    ))
    calls = []
    daemon = SimpleNamespace(_wake=wake, _publication_guards=PublicationGuards())
    with ThreadPoolExecutor(max_workers=1) as workers:
        execution = SimpleNamespace(
            agent_id="embedded", config=SimpleNamespace(coordinator_shared_roots={}),
            _slurm_storage_futures={}, _slurm_storage_workers=workers,
            _slurm_task=lambda record: {}, _daemon_owner=lambda: daemon,
        )
        pending = (_SlurmPublicationRequired(execution, record, "fence") if operation == "publication"
                   else _SlurmRetentionRequired(execution, record, {}))
        pending.completed = False
        key = "_publication" if operation == "publication" else "_retained"

        def retain():
            entered.set()
            assert proceed.wait(5)
            pending.completed = True

        pending.retain = pending.prepare = retain

        def acknowledge(*args, **kwargs):
            calls.append(kwargs)
            if kwargs[key] is None:
                raise pending
            assert kwargs[key] is pending and pending.completed
            return {"sequence": 1}

        execution.acknowledge_slurm_agent = acknowledge
        execution._slurm_agent = SimpleNamespace(step=lambda task, ack: ack({}))
        try:
            LocalDaemonExecution._drive_local_slurm(execution, record)
            assert entered.wait(5)
            LocalDaemonExecution._drive_local_slurm(execution, record)
            assert len(calls) == 1
            assert not pending.completed
        finally:
            proceed.set()
        assert wake.wait(5)
        LocalDaemonExecution._drive_local_slurm(execution, record)
        assert len(calls) == 2
        assert execution._slurm_storage_futures == {}


def test_slurm_publication_continuation_binds_verified_tree_and_replays_rename(tmp_path):
    from loom.queue.local_daemon_execution import _SlurmPublicationRequired
    from loom.queue._shared_publication import accept_publication
    from tests.unit.loom.queue.test_slurm_ready_stage import _shared_slurm_workspace

    workspace, profile, result = _shared_slurm_workspace(tmp_path)
    report = workspace.retain_result(result)
    execution = SimpleNamespace(config=SimpleNamespace(coordinator_shared_roots=profile.shared_roots))
    record = SimpleNamespace(
        assignment=SimpleNamespace(agent_id="agent-1", assignment_id=workspace.root.name),
        delivery=workspace.delivery(), report=report, bootstrap_incarnation="bootstrap", fence="fence-1",
    )
    pending = _SlurmPublicationRequired(execution, record, "fence-1")
    assert not pending.validates(execution, record, "fence-1")
    pending.prepare()
    assert pending.validates(execution, record, "fence-1")
    changed = SimpleNamespace(**{**vars(record), "bootstrap_incarnation": "replacement"})
    assert not pending.validates(execution, changed, "fence-1")
    changed = SimpleNamespace(**{**vars(record), "report": replace(report, executor_metadata={"test": "changed"})})
    assert not pending.validates(execution, changed, "fence-1")
    assert not pending.validates(execution, record, "different-fence")
    roots = execution.config.coordinator_shared_roots
    execution.config.coordinator_shared_roots = {}
    assert not pending.validates(execution, record, "fence-1")
    execution.config.coordinator_shared_roots = roots
    outputs = accept_publication(pending.prepared)
    # A crash/lost reply after rename must permit fresh verification and replay.
    replay = _SlurmPublicationRequired(execution, record, "fence-1")
    replay.prepare()
    assert replay.validates(execution, record, "fence-1")
    assert accept_publication(replay.prepared) == outputs


def test_concurrent_slurm_commit_retries_share_one_publication_guard(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, RLock
    from loom.queue.agent_sessions import AgentSessionService
    from loom.queue.local_daemon_execution import _SlurmPublicationRequired
    from loom.queue._publication_guards import PublicationGuards
    from loom.queue import _shared_publication as publication
    from tests.unit.loom.queue.test_slurm_ready_stage import _shared_slurm_workspace

    workspace, profile, result = _shared_slurm_workspace(tmp_path)
    record = SimpleNamespace(
        assignment=SimpleNamespace(agent_id="agent-1", assignment_id=workspace.root.name),
        delivery=workspace.delivery(), report=workspace.retain_result(result),
        bootstrap_incarnation="bootstrap", fence="fence-1",
    )
    execution = SimpleNamespace(config=SimpleNamespace(coordinator_shared_roots=profile.shared_roots))
    lock = RLock()
    daemon = SimpleNamespace(_cycle_lock=lock, _publication_guards=PublicationGuards())
    entered, proceed, retry_started = Event(), Event(), Event()
    preparations = []
    original_prepare = publication.prepare_publication

    def prepare(*args, **kwargs):
        preparations.append(True)
        if len(preparations) == 1:
            entered.set()
            assert proceed.wait(5)
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(publication, "prepare_publication", prepare)

    def locked(session, epoch, evidence, cursor, **options):
        if options.get("_pending_only"):
            return None
        if options.get("_defer_publication"):
            raise _SlurmPublicationRequired(execution, record, "fence-1")
        token = options["_publication"]
        assert token.validates(execution, record, "fence-1")
        return publication.accept_publication(token.prepared)

    service = SimpleNamespace(_daemon=daemon, _slurm_work_locked=locked)
    evidence = {"result_operation": "commit", "assignment_id": workspace.root.name}

    def commit(retry=False):
        if retry:
            retry_started.set()
        return AgentSessionService.slurm_work(service, "session", "epoch", evidence)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(commit)
        try:
            assert entered.wait(5)
            second = workers.submit(commit, True)
            assert retry_started.wait(5)
            assert lock.acquire(timeout=1)
            lock.release()
            assert preparations == [True]
        finally:
            proceed.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert len(preparations) == 2


def test_embedded_publication_can_transition_to_retention_in_one_replay():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from loom.queue._publication_guards import PublicationGuards
    from loom.queue.local_daemon_execution import _SlurmRetentionRequired, _SlurmPublicationRequired

    record = SimpleNamespace(assignment=SimpleNamespace(
        assignment_id="assignment-1", agent_id="embedded", agent_root_id="root",
    ))
    daemon = SimpleNamespace(_wake=Event(), _publication_guards=PublicationGuards())
    accepted = set()
    with ThreadPoolExecutor(max_workers=1) as workers:
        execution = SimpleNamespace(
            agent_id="embedded", config=SimpleNamespace(coordinator_shared_roots={}),
            _slurm_storage_futures={}, _slurm_storage_workers=workers,
            _slurm_task=lambda record: {}, _daemon_owner=lambda: daemon,
        )
        publication = _SlurmPublicationRequired(execution, record, "fence")
        retention = _SlurmRetentionRequired(execution, record, {})
        publication.prepare = lambda: setattr(publication, "prepared", object())
        retention.retain = lambda: setattr(retention, "completed", True)

        def acknowledge(agent, root, evidence, **options):
            phase = evidence["phase"]
            if phase in accepted:
                return {}
            token = publication if phase == "publication" else retention
            if options["_publication" if phase == "publication" else "_retained"] is not token:
                raise token
            assert publication.prepared is not None if phase == "publication" else retention.completed
            accepted.add(phase)
            return {}

        def step(task, ack):
            ack({"phase": "publication"})
            ack({"phase": "retention"})

        execution.acknowledge_slurm_agent = acknowledge
        execution._slurm_agent = SimpleNamespace(step=step)
        LocalDaemonExecution._drive_local_slurm(execution, record)
        execution._slurm_storage_futures["assignment-1"][0].result(timeout=5)
        LocalDaemonExecution._drive_local_slurm(execution, record)
        future, pending = execution._slurm_storage_futures["assignment-1"]
        assert pending is retention and accepted == {"publication"}
        future.result(timeout=5)
        LocalDaemonExecution._drive_local_slurm(execution, record)
        assert accepted == {"publication", "retention"}
        assert execution._slurm_storage_futures == {}
