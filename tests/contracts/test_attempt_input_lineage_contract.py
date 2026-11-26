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


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_reprepared_upstream_commit_prevents_binding_an_older_input(tmp_path, backend):
    from loom.pipeline.transition_policy import TransitionIntent
    from loom.pipeline.stores.authority import PreparedAttemptBindRejected

    uri, authority, _, _ = _consumer(tmp_path, backend)
    upstream = prepare(authority, uri, stage="upstream")

    def commit(receipt, previous=None):
        pair = {"assignment_id": "worker-" + receipt.attempt.attempt_id, "attempt_id": receipt.attempt.attempt_id}
        authority.bind_prepared_attempt(uri, **pair, expected_revision=authority.open_run(uri).revision)
        fence = authority.grant_prepared_attempt(uri, **pair)
        return authority.record_output_commit(
            uri, "upstream", **pair, fencing_token=fence.fencing_token, supersedes_commit_id=previous,
            outputs={"out": ArtifactRef(artifact_id="data", uri=uri + "/out", artifact_type="text")},
        ).commit.commit_id

    original = commit(upstream)
    consumer = prepare(authority, uri, upstream={"upstream": original})
    stale = authority.transition_stage(
        uri, "upstream", from_status=StageStatus.SUCCEEDED, to_status=StageStatus.STALE,
        intent=TransitionIntent.RESUME,
    )
    replacement = authority.ensure_prepared_attempt(uri, replace(
        upstream.request, readiness_generation="next-readiness", operation_id="prepare-next", next_attempt=2,
        expected_stage_status=StageStatus.STALE, expected_attempt_id=upstream.attempt.attempt_id,
        expected_revision=stale.revision,
    ))
    assert commit(replacement, original) != original
    pair = {"assignment_id": "consumer", "attempt_id": consumer.attempt.attempt_id}
    with pytest.raises(PreparedAttemptBindRejected, match="upstream commit evidence is stale"):
        authority.bind_prepared_attempt(uri, **pair, expected_revision=authority.open_run(uri).revision)
    with pytest.raises(ValueError, match="not bound"):
        authority.grant_prepared_attempt(uri, **pair)


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
def test_explicit_unknown_inspection_and_empty_input_evidence_remain_distinct(
    tmp_path, backend
):
    from loom.pipeline.stores import AuthorityStoreError
    from loom.pipeline.stores.read_models import AuthorityModelError

    uri, authority, database, _ = _consumer(tmp_path, backend)
    known = prepare(authority, uri)
    allocation_owner = authority
    if backend == "authenticated":
        from loom.authority._repository import AuthorityRepository

        allocation_owner = AuthorityRepository(
            database.parent, database_name=database.name
        )
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.authority._repository import AuthorityRepository
    assert isinstance(allocation_owner, (SQLitePerRunAuthorityStore, AuthorityRepository))
    allocation_owner.allocate_stage_attempt(
        uri,
        "unrecorded",
        owner_id="direct-reader",
        lease_ttl_seconds=30,
    )
    unknown = next(
        stage.attempts[0]
        for stage in authority.open_run(uri).stages
        if stage.stage_name == "unrecorded"
    )
    assert known.attempt.input_bindings == ()
    assert unknown.input_bindings is None
    assert StageAttempt.from_dict(unknown.to_dict()) == unknown
    assert known.request.to_dict()["input_bindings"] == []

    for retired in (None, "absent"):
        payload = known.request.to_dict()
        if retired == "absent":
            del payload["input_bindings"]
        else:
            payload["input_bindings"] = None
        with pytest.raises(AuthorityStoreError, match="input.bindings"):
            PreparedAttemptRequest.from_dict(payload)
    for key in ("input_bindings", "start_confirmed", "start_confirmed_at"):
        payload = known.attempt.to_dict()
        del payload[key]
        with pytest.raises(AuthorityModelError, match=key):
            StageAttempt.from_dict(payload)


def test_retired_input_kind_is_refused():
    binding = AttemptInputBinding(
        "data",
        None,
        None,
        ArtifactRef(
            artifact_id="external", uri="file:///external", artifact_type="bytes"
        ),
        None,
        "external",
    )
    payload = binding.to_dict()
    payload["source_kind"] = "legacy_unresolved"
    with pytest.raises(ValueError, match="source kind"):
        AttemptInputBinding.from_dict(payload)


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
def test_retired_lineage_database_is_refused_without_repair(tmp_path, backend):
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.authority._repository import AuthorityRepository, AuthorityRepositoryCompatibilityError
    from loom.pipeline.stores import AuthoritySchemaError

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
    conn.close()
    before = {path.name: path.read_bytes() for path in database.parent.iterdir() if path.is_file()}
    if backend == "embedded":
        with pytest.raises(AuthoritySchemaError, match="older"):
            SQLitePerRunAuthorityStore(uri).open_run(uri)
    else:
        reopened = AuthorityRepository(database.parent, database_name=database.name)
        with pytest.raises(AuthorityRepositoryCompatibilityError, match="older"):
            reopened.initialize()
    assert {path.name: path.read_bytes() for path in database.parent.iterdir() if path.is_file()} == before


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
