"""Read-only recovery previews preserve ineligible attempts and their evidence."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from loom.queue import _shared_recovery as recovery
from loom.queue import _recovery_cleanup as cleanup
from loom.queue._coordinator_control import validate_request, decode_result
from tests.unit.loom.queue.test_shared_recovery import _workspace, _write


@pytest.mark.parametrize("status", ["FAILED", "SUCCEEDED"])
def test_preview_keeps_existing_attempts_without_durable_diagnostics(tmp_path, monkeypatch, status):
    workspace, profile, _ = _workspace(tmp_path)
    current = _write(workspace)
    ref = recovery.seal(
        workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )
    tree, _ = recovery.inspect(ref, profile.shared_roots)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE remote_assignments (
            assignment_id TEXT, run_uri TEXT, stage_name TEXT, attempt INTEGER,
            attempt_id TEXT, state TEXT, provider_release_proof_json TEXT,
            report_json TEXT, fence TEXT);
        CREATE TABLE agent_receipts (
            principal_id TEXT, operation TEXT, idempotency_key TEXT, result_json TEXT);
        CREATE TABLE agent_deliveries (assignment_id TEXT, request_json TEXT);
    """)
    conn.execute("INSERT INTO remote_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        workspace.assignment_id, "run", "fit", 1, "attempt-1", "RELEASED",
        "{}", json.dumps({"status": status}), "fence-1",
    ))
    conn.execute("INSERT INTO agent_receipts VALUES (?, ?, ?, ?)", (
        recovery._PRINCIPAL, "seal", workspace.assignment_id, json.dumps(ref),
    ))
    admitted = []
    daemon = SimpleNamespace(
        admission_for_run_uri=admitted.append,
        _connection=lambda: conn,
        config=SimpleNamespace(coordinator_shared_roots=profile.shared_roots),
    )
    stage = SimpleNamespace(
        stage_name="fit", latest_commit=SimpleNamespace(attempt_id="attempt-1"),
        artifact_facts=[],
    )
    monkeypatch.setattr(cleanup, "_authority", lambda *args: SimpleNamespace(
        open_run=lambda uri: SimpleNamespace(stages=[stage])))

    def no_payload_scan(*args, **kwargs):
        raise AssertionError("preview read scientific payloads")

    monkeypatch.setattr(recovery, "inventory", no_payload_scan)
    result = cleanup.preview_recovery_cleanup(daemon, "run")
    assert admitted == ["run"]
    entry, = result["entries"]
    assert entry["eligible"] is False
    assert entry["retained_payload_bytes"] == len(b"completepartial")
    assert entry["reclaimable_payload_bytes"] == 0
    assert "complete_diagnostics_not_declared" in entry["reasons"]
    assert "logs_not_published" in entry["reasons"]
    assert ("recovery_still_required" in entry["reasons"]) == (status == "FAILED")
    assert (tree / "checkpoints/completed").read_bytes() == b"complete"
    assert not current.exists()
    conn.close()


def test_preview_wire_requires_exact_managed_run_selection():
    assert validate_request("preview_recovery_cleanup", {"run_uri": "run"}) == {"run_uri": "run"}
    with pytest.raises(ValueError):
        validate_request("preview_recovery_cleanup", {"run_uri": "run", "delete": True})
    value = {"run_uri": "run", "entries": []}
    assert decode_result("preview_recovery_cleanup", value) == value


def test_settled_logs_share_publication_and_survive_assignment_removal(tmp_path):
    from dataclasses import replace
    from pathlib import Path
    import shutil
    from loom.queue._shared_publication import publish, RECOVERY_COMPLETE, EXECUTION_LOGS
    from tests.unit.loom.queue.test_remote_stage_execution import _shared_publication_workspace

    workspace, profile, _, original = _shared_publication_workspace(tmp_path)
    output = original.outputs["result"]
    result = replace(original, outputs={"result": replace(output, metadata={
        **output.metadata,
        RECOVERY_COMPLETE: {"schema_version": 1, "required_outputs": ["result"]},
    })})
    log_root = workspace.root / "logs"
    log_root.mkdir(exist_ok=True)
    (log_root / "stdout.log").write_bytes(b"completed output\n")
    (log_root / "stderr.log").write_bytes(b"diagnostic warning\n")
    report = workspace._retain_outputs(result)
    refs = publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1")
    fact = SimpleNamespace(artifact_name="result", artifact=refs["result"])
    assert cleanup._complete_outputs([fact])
    assert cleanup._published_logs([fact], profile.shared_roots)
    # Final publication is the replay authority, even if original logs are gone.
    shutil.rmtree(log_root)
    assert workspace._retain_outputs(result) == report
    root = Path(refs["result"].uri.removeprefix("file://")).parent
    shutil.rmtree(workspace.root)
    assert (root / refs["result"].metadata[EXECUTION_LOGS]["stdout"]).read_bytes() == b"completed output\n"
    assert (root / refs["result"].metadata[EXECUTION_LOGS]["stderr"]).read_bytes() == b"diagnostic warning\n"
    assert cleanup._published_logs([fact], profile.shared_roots)


@pytest.fixture
def releasable_attempt(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from dataclasses import replace
    from loom.queue._shared_publication import RECOVERY_COMPLETE, publish

    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    reference = recovery.seal(workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1")
    tree, _ = recovery.inspect(reference, profile.shared_roots)
    from loom.artifacts import ArtifactRef
    from loom.pipeline.execution.models import StageWorkerResult
    from loom.pipeline.status import StageStatus
    from loom.queue._shared_publication import worker_artifact_root

    output = worker_artifact_root(workspace) / workspace.request().stage_name / "primary.json"
    output.write_bytes(b"scientific output")
    result = StageWorkerResult(
        schema_version=1, run_uri=f"loom-agent:{workspace.assignment_id}",
        stage_name=workspace.request().stage_name, attempt=1, status=StageStatus.SUCCEEDED,
        started_at="2020-01-01T00:00:00Z", finished_at="2020-01-01T00:00:01Z",
        executor_name="local", outputs={"result": ArtifactRef("result", output.as_uri(), "bytes")},
        executor_metadata={},
    )
    result = replace(result, outputs={name: replace(ref, metadata={
        **ref.metadata, RECOVERY_COMPLETE: {"schema_version": 1, "required_outputs": list(result.outputs)}
    }) for name, ref in result.outputs.items()})
    (workspace.root / "logs").mkdir(exist_ok=True)
    for stream in ("stdout", "stderr"):
        (workspace.root / "logs" / f"{stream}.log").write_bytes(b"retained log\n")
    report = workspace._retain_outputs(result)
    refs = publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1")
    database = tmp_path / "control.sqlite"

    @contextmanager
    def connection():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    with connection() as conn:
        conn.executescript("""
            CREATE TABLE remote_assignments (
                assignment_id TEXT, run_uri TEXT, stage_name TEXT, attempt INTEGER,
                attempt_id TEXT, state TEXT, provider_release_proof_json TEXT,
                report_json TEXT, fence TEXT, session_id TEXT, start_permitted INTEGER);
            CREATE TABLE agent_receipts (
                principal_id TEXT, operation TEXT, idempotency_key TEXT, result_json TEXT,
                digest TEXT, PRIMARY KEY(principal_id, operation, idempotency_key));
            CREATE TABLE agent_deliveries (assignment_id TEXT, request_json TEXT);
            CREATE TABLE agent_sessions (session_id TEXT, agent_root_id TEXT);
        """)
        conn.execute("INSERT INTO remote_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            workspace.assignment_id, "run", workspace.request().stage_name, 1, "attempt-1", "RELEASED",
            "{}", json.dumps({"status": "SUCCEEDED"}), "fence-1", "session", 1,
        ))
        conn.execute("INSERT INTO agent_sessions VALUES ('session', 'agent-1')")
        conn.execute("INSERT INTO agent_deliveries VALUES (?, ?)",
                     (workspace.assignment_id, json.dumps(workspace.request().to_dict())))
        conn.execute("INSERT INTO agent_receipts VALUES (?, ?, ?, ?, ?)", (
            recovery._PRINCIPAL, "seal", workspace.assignment_id, json.dumps(reference), reference["receipt_digest"],
        ))
        conn.commit()
    checks, results = [], []
    stage = SimpleNamespace(stage_name=workspace.request().stage_name,
                            latest_commit=SimpleNamespace(attempt_id="attempt-1"),
                            artifact_facts=[SimpleNamespace(artifact_name=k, artifact=v) for k, v in refs.items()])

    def append_result(uri, result):
        results.append(result)
        return SimpleNamespace(result=result)

    authority = SimpleNamespace(open_run=lambda uri: SimpleNamespace(stages=[stage]),
                                append_cleanup_result=append_result)
    monkeypatch.setattr(cleanup, "_authority", lambda *args: authority)
    daemon = SimpleNamespace(
        admission_for_run_uri=lambda uri: None, _connection=connection,
        config=SimpleNamespace(coordinator_shared_roots=profile.shared_roots, control_database=database),
        _authorizer=lambda: SimpleNamespace(require_operator=lambda *args, **kwargs: checks.append((args, kwargs))),
    )
    return SimpleNamespace(daemon=daemon, tree=tree, refs=refs, results=results, checks=checks,
                           workspace=workspace, profile=profile, stage=stage,
                           principal=SimpleNamespace(subject="operator"),
                           arguments=dict(run_uri="run", assignment_id=workspace.assignment_id,
                                          operation_id="cleanup-1", reason="durable outputs verified"))


def test_release_preserves_outputs_and_records_cleanup_idempotently(releasable_attempt):
    from loom.pipeline.stores.local_artifacts import LocalArtifactStore

    case = releasable_attempt
    preview = cleanup.preview_recovery_cleanup(case.daemon, "run")
    assert preview["entries"][0]["eligible"]
    result = cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert result["state"] == "deleted"
    assert result["reclaimed_payload_bytes"] == len(b"completepartial")
    assert not case.tree.exists()
    assert len(case.results) == 1
    assert case.results[0].entries[0].outcome.value == "deleted"
    assert case.checks[0][0][1] == "cleanup_recovery"
    assert case.checks[0][1] == {"agent_id": "agent-1"}
    assert cleanup.release_recovery(case.daemon, case.principal, **case.arguments) == result
    assert len(case.results) == 1
    for ref in case.refs.values():
        assert LocalArtifactStore(case.tree.parent).inspect(ref).receipt is not None
    assert cleanup.preview_recovery_cleanup(case.daemon, "run")["entries"][0]["reasons"] == ["recovery_deleted"]
    with case.daemon._connection() as conn:
        assert conn.execute("SELECT result_json FROM agent_receipts WHERE operation = 'seal'").fetchone()
        assert json.loads(conn.execute("SELECT report_json FROM remote_assignments").fetchone()[0])["status"] == "SUCCEEDED"


def test_failed_cleanup_resumes_same_reservation(releasable_attempt, monkeypatch):
    from loom.pipeline.cleanup import execution

    case = releasable_attempt
    original = execution.shutil.rmtree

    def interrupted(path):
        (path / "partial").unlink()
        raise OSError("interrupted cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(execution.shutil, "rmtree", interrupted)
        result = cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert result["state"] == "failed"
    assert result["reclaimed_payload_bytes"] == 0
    assert case.tree.exists()
    assert not (case.tree / recovery.RECEIPT).exists()
    assert not (case.tree / "partial").exists()
    assert execution.shutil.rmtree is original
    result = cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert result["state"] == "deleted"
    assert not case.tree.exists()
    assert [r.entries[0].outcome.value for r in case.results] == ["failed", "deleted"]


def test_ineligible_release_does_not_unpin_or_reserve(releasable_attempt):
    case = releasable_attempt
    with case.daemon._connection() as conn:
        conn.execute("UPDATE remote_assignments SET provider_release_proof_json = NULL")
        conn.commit()
    from loom.queue.errors import QueueConflictError
    with pytest.raises(QueueConflictError, match="provider_not_settled"):
        cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert (case.tree / recovery.RECEIPT).is_file()
    with case.daemon._connection() as conn:
        assert cleanup._release_record(conn, case.workspace.assignment_id) is None


def test_concurrent_release_requests_delete_once(releasable_attempt):
    from concurrent.futures import ThreadPoolExecutor

    case = releasable_attempt
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cleanup.release_recovery, case.daemon, case.principal,
                               **case.arguments) for _ in range(2)]
        first, second = [future.result(timeout=10) for future in futures]
    assert first == second
    assert first["state"] == "deleted"
    assert len(case.results) == 1


def test_retry_after_successful_cleanup_does_not_acquire_retired_tree(releasable_attempt, tmp_path):
    case = releasable_attempt
    cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    (tmp_path / "retry").mkdir()
    retry, _, _ = _workspace(tmp_path / "retry", attempt=2)
    with case.daemon._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        request = recovery.bind_delivery(retry.request(), conn, "run", case.profile.shared_roots,
                                         session_id="session")
    assert request.worker_metadata[recovery.WIRE]["predecessors"] == ()
    assert not case.tree.exists()


def test_release_operator_permission_is_required_before_reservation(releasable_attempt):
    from loom.queue.errors import QueueServiceError

    case = releasable_attempt
    def deny(*args, **kwargs):
        raise QueueServiceError("operator is not authorized")
    case.daemon._authorizer = lambda: SimpleNamespace(require_operator=deny)
    with pytest.raises(QueueServiceError, match="authorized"):
        cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert (case.tree / recovery.RECEIPT).is_file()
    with case.daemon._connection() as conn:
        assert cleanup._release_record(conn, case.workspace.assignment_id) is None


def test_live_recovery_dependency_blocks_release(releasable_attempt):
    from loom.queue.errors import QueueConflictError

    case = releasable_attempt
    request = case.workspace.request().to_dict()
    with case.daemon._connection() as conn:
        reference = json.loads(conn.execute("SELECT result_json FROM agent_receipts WHERE operation = 'seal'").fetchone()[0])
        # A failed predecessor may already have supplied a still-running retry.
        conn.execute("UPDATE remote_assignments SET report_json = ?", (json.dumps({"status": "FAILED"}),))
        request["worker_metadata"][recovery.WIRE]["predecessors"] = [reference]
        conn.execute("INSERT INTO remote_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            "retry", "run", case.workspace.request().stage_name, 2, "attempt-2", "RUNNING",
            None, None, "fence-2", "session", 1,
        ))
        conn.execute("INSERT INTO agent_deliveries VALUES (?, ?)", ("retry", json.dumps(request)))
        conn.commit()
    with pytest.raises(QueueConflictError, match="live_recovery_dependent"):
        cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert (case.tree / recovery.RECEIPT).is_file()
    assert not case.results


def test_release_replays_after_deletion_before_result_ack(releasable_attempt, monkeypatch):
    from loom.pipeline.cleanup import execution

    case = releasable_attempt
    original = execution.execute_cleanup

    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("lost acknowledgement after deletion")

    with monkeypatch.context() as patch:
        patch.setattr(execution, "execute_cleanup", lose_ack)
        first = cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert first["state"] == "failed"
    assert not case.tree.exists()
    replay = cleanup.release_recovery(case.daemon, case.principal, **case.arguments)
    assert replay["state"] == "deleted"
    assert replay["error"] is None
    assert replay["cleanup_result"]["entries"][0]["reason_code"] == "target_missing"


@pytest.mark.parametrize("actions, machines, allowed", [
    (("cleanup_recovery",), ("agent-1",), True),
    (("drain",), ("agent-1",), False),
    (("cleanup_recovery",), ("another-agent",), False),
])
def test_release_uses_native_action_and_machine_scope(releasable_attempt, actions, machines, allowed):
    from loom.queue import LocalDaemonPrincipal, LocalDaemonRole
    from loom.queue.agent_sessions import AgentPolicyConfig, LocalOwnerOperatorPolicy, ScopedAuthorizer
    from loom.queue.errors import QueueServiceError

    case = releasable_attempt
    principal = LocalDaemonPrincipal("uid:owner", LocalDaemonRole.OPERATOR)
    policy = AgentPolicyConfig(local_owner=LocalOwnerOperatorPolicy(actions=actions, agent_ids=machines))
    case.daemon._authorizer = lambda: ScopedAuthorizer(policy, verified_local_owner_subject="uid:owner")
    if allowed:
        assert cleanup.release_recovery(case.daemon, principal, **case.arguments)["state"] == "deleted"
    else:
        with pytest.raises(QueueServiceError, match="not authorized"):
            cleanup.release_recovery(case.daemon, principal, **case.arguments)
        assert (case.tree / recovery.RECEIPT).is_file()
