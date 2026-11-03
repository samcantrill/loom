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


def test_slurm_ack_replays_budget_outcome_before_releasing_gpu(tmp_path, monkeypatch):
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
        return LocalDaemonExecution.acknowledge_slurm_agent(
            execution, assignment.agent_id, assignment.agent_root_id, value,
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
    with connection() as conn:
        assert conn.execute("SELECT resolved FROM agent_coordinator_references").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 1
