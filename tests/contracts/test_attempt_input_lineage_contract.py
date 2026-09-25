"""Durable assignment and start evidence across both authority boundaries."""

from dataclasses import replace
import sqlite3

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.authority import PreparedAttemptRequest
from loom.pipeline.stores.input_lineage import AttemptInputBinding, capture_bindings
from loom.pipeline.stores.read_models import LifecycleReason, StageAttempt
from loom.runs import OutputLocator
from tests.integration.authority.test_action_result_binding import _consumer, _producer

pytestmark = pytest.mark.contract


def prepare(authority, uri, *, bindings=(), stage="consume", upstream=None):
    return authority.ensure_prepared_attempt(
        uri,
        PreparedAttemptRequest(
            operation_id="prepare-" + stage,
            request_digest="digest-" + stage,
            admission_id="admission",
            stage_name=stage,
            readiness_generation="ready-" + stage,
            expected_revision=authority.open_run(uri).revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan",
            bound_inputs={},
            upstream_commits=upstream or {},
            input_bindings=bindings,
        ),
    )


def test_prepared_binding_round_trip_with_nested_artifact_metadata(tmp_path):
    uri, authority, _, _ = _consumer(tmp_path, "embedded")
    binding = AttemptInputBinding(
        "data", None, None,
        ArtifactRef(artifact_id="external", uri="s3://external/input", artifact_type="json",
                    metadata={"dimensions": [2, 3], "nested": {"names": ["a", "b"]}}),
        None, "external",
    )
    receipt = prepare(authority, uri, bindings=(binding,))
    request = replace(receipt.request, bound_inputs={
        "data": {"artifact_ref": binding.artifact.to_dict(),
                 "source_stage": None, "source_output": None},
    })
    assert PreparedAttemptRequest.from_dict(request.to_dict()) == request


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("terminal", [StageStatus.FAILED, StageStatus.CANCELLED])
def test_start_witness_survives_terminal_restart_without_audit(
    tmp_path, backend, started, terminal
):
    uri, authority, database, tables = _consumer(tmp_path, backend)
    external = AttemptInputBinding(
        "data",
        None,
        None,
        ArtifactRef(
            artifact_id="external", uri="file:///external", artifact_type="bytes"
        ),
        None,
        "external",
    )
    receipt = prepare(authority, uri, bindings=(external,))
    assert receipt.attempt.start_confirmed is False
    assert authority.ensure_prepared_attempt(uri, receipt.request) == receipt
    authority.bind_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=receipt.attempt.attempt_id
    )
    fence = authority.grant_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=receipt.attempt.attempt_id
    )
    if started:
        authority.confirm_execution_started(uri, fence=fence)
        first = authority.open_run(uri).stages[0].attempts[0].start_confirmed_at
        authority.confirm_execution_started(uri, fence=fence)
        assert authority.open_run(uri).stages[0].attempts[0].start_confirmed_at == first
    else:
        first = None
    authority.record_managed_attempt_terminal(
        uri, fence=fence, status=terminal, reason=LifecycleReason(code="test.terminal")
    )
    authority.confirm_execution_started(uri, fence=fence)
    # Reads reopen the owning SQLite database; no audit observer supplies evidence.
    with sqlite3.connect(database) as conn:
        audit = "audit_events" if backend == "embedded" else "authority_audit_events"
        actual = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        }
        if audit in actual:
            conn.execute(f"DELETE FROM {audit}")
    attempt = authority.open_run(uri).stages[0].attempts[0]
    if backend == "embedded":
        from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
        restarted = SQLitePerRunAuthorityStore(uri).open_run(uri)
    else:
        from loom.authority._repository import AuthorityRepository
        restarted = AuthorityRepository(database.parent, database_name=database.name).open_run(uri)
    assert restarted.stages[0].attempts[0] == attempt
    assert attempt.status is terminal
    assert attempt.start_confirmed is started
    assert attempt.start_confirmed_at == first
    assert attempt.input_bindings == (external,)
    assert StageAttempt.from_dict(attempt.to_dict()) == attempt
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            f"SELECT start_confirmed, start_confirmed_at FROM {tables[0]}"
        ).fetchone()
        assert row == (int(started), first)


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_reused_pending_input_retains_original_commit_and_rejects_forged_source(
    tmp_path, backend
):
    from loom.pipeline.planning.models import PendingInput, PlanReason, PlanReasonCode
    from types import SimpleNamespace

    _, binding = _producer(tmp_path)
    uri, authority, _, _ = _consumer(tmp_path, backend)
    authority.bind_action_result(uri, "reused", binding)
    source = authority.open_run(uri).stages[0]
    plan = SimpleNamespace(
        bound_inputs={},
        pending_inputs=(
            PendingInput(
                "data",
                "reused",
                "out",
                PlanReason(PlanReasonCode.PENDING_UPSTREAM_INPUT, "pending"),
            ),
        ),
    )
    captured = capture_bindings(plan, {"reused": source})
    assert captured[0].producer == OutputLocator(
        binding.commit.run_uri, "original", binding.commit.commit_id, "out"
    )
    receipt = prepare(
        authority, uri, bindings=captured, upstream={"reused": binding.commit.commit_id}
    )
    assert receipt.attempt.input_bindings == captured
    assert source.attempts == ()
    original = captured[0].producer
    assert original is not None
    bad = replace(captured[0], producer=replace(original, commit_id="different"))
    with pytest.raises(ValueError, match="authoritative source"):
        prepare(
            authority,
            uri,
            bindings=(bad,),
            stage="bad",
            upstream={"reused": binding.commit.commit_id},
        )


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_absent_empty_and_legacy_evidence_remain_distinct(tmp_path, backend):
    uri, authority, _, _ = _consumer(tmp_path, backend)
    known = prepare(authority, uri)
    unknown = prepare(authority, uri, stage="legacy", bindings=None)
    assert known.attempt.input_bindings == ()
    assert unknown.attempt.input_bindings is None
    assert "input_bindings" not in unknown.request.to_dict()
    legacy = known.attempt.to_dict()
    for key in ("input_bindings", "start_confirmed", "start_confirmed_at"):
        legacy.pop(key)
    decoded = StageAttempt.from_dict(legacy)
    assert decoded.input_bindings is None and decoded.start_confirmed is None
    assert decoded.start_confirmed_at is None


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_direct_running_allocation_retains_acknowledgement(tmp_path, backend):
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    uri, store, database, _ = _consumer(tmp_path, backend)
    if backend == "authenticated":
        from loom.authority._repository import AuthorityRepository

        store = AuthorityRepository(database.parent, database_name=database.name)
    else:
        assert isinstance(store, SQLitePerRunAuthorityStore)
    allocation = store.allocate_stage_attempt(
        uri, "direct", owner_id="worker", lease_ttl_seconds=60
    )
    attempt = store.open_run(uri).stages[0].attempts[0]
    assert allocation.attempt.start_confirmed is True
    assert attempt.start_confirmed is True and attempt.start_confirmed_at


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_database_migration_preserves_absent_legacy_evidence(tmp_path, backend):
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.authority._repository import AuthorityRepository

    uri, authority, database, tables = _consumer(tmp_path, backend)
    prepare(authority, uri)
    with sqlite3.connect(database) as conn:
        for column in ("input_bindings_json", "start_confirmed", "start_confirmed_at"):
            conn.execute(f"ALTER TABLE {tables[0]} DROP COLUMN {column}")
        metadata = "metadata" if backend == "embedded" else "repository_metadata"
        version = "9" if backend == "embedded" else "10"
        conn.execute(
            f"UPDATE {metadata} SET value=? WHERE key='schema_version'", (version,)
        )
    if backend == "embedded":
        reopened = SQLitePerRunAuthorityStore(uri)
        snapshot = reopened.open_run(uri)
    else:
        reopened = AuthorityRepository(database.parent, database_name=database.name)
        reopened.initialize()
        snapshot = reopened.open_run(uri)
    attempt = snapshot.stages[0].attempts[0]
    assert attempt.start_confirmed is None and attempt.start_confirmed_at is None
    assert attempt.input_bindings is None


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_retry_has_its_own_retained_inputs_and_start_witness(tmp_path, backend):
    from loom.pipeline.transition_policy import TransitionIntent

    uri, authority, _, _ = _consumer(tmp_path, backend)
    first = prepare(authority, uri)
    authority.bind_prepared_attempt(
        uri, assignment_id="first", attempt_id=first.attempt.attempt_id
    )
    fence = authority.grant_prepared_attempt(
        uri, assignment_id="first", attempt_id=first.attempt.attempt_id
    )
    authority.confirm_execution_started(uri, fence=fence)
    authority.record_managed_attempt_terminal(
        uri,
        fence=fence,
        status=StageStatus.FAILED,
        reason=LifecycleReason(code="test.failed"),
    )
    authority.transition_stage(
        uri,
        "consume",
        from_status=StageStatus.FAILED,
        to_status=StageStatus.STALE,
        intent=TransitionIntent.RESUME,
    )
    second = authority.ensure_prepared_attempt(
        uri,
        replace(
            first.request,
            operation_id="second",
            request_digest="second",
            readiness_generation="second",
            expected_revision=authority.open_run(uri).revision,
            expected_stage_status=StageStatus.STALE,
            expected_attempt_id=first.attempt.attempt_id,
            next_attempt=2,
        ),
    )
    attempts = authority.open_run(uri).stages[0].attempts
    assert (
        len(attempts) == 2
        and attempts[0].input_bindings == attempts[1].input_bindings == ()
    )
    assert attempts[0].start_confirmed is True and attempts[1].start_confirmed is False
    assert second.attempt.attempt_id != first.attempt.attempt_id
