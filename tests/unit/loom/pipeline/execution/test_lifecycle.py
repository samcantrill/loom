"""Unit tests for lifecycle status helpers."""

from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.execution.errors import PlanExecutionError
from loom.pipeline.execution.lifecycle import (
    bind_stage_inputs,
    commit_stage_execution_result,
    persist_stage_cancellation,
    persist_stage_failure,
    write_run_submitted,
    write_run_status,
    write_stage_artifact_index_refs,
    write_stage_blocked,
    write_stage_running,
    write_stage_submitted,
)
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionResult,
)
from loom.pipeline.execution.reliability import (
    record_retry_decision_for_stage_result,
    record_stage_reliability_transition,
    record_timeout_outcome_from_metadata,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.reliability import (
    RetryPolicy,
    StageAttemptTransactionState,
    TimeoutOutcome,
    TimeoutSupportLevel,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores import (
    LifecycleReason,
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _ref(stage: str = "build", output: str = "data") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"{stage}/{output}",
        uri=f"file:///tmp/{stage}/{output}.json",
        artifact_type="json",
        codec_key="json.v1",
    )


def _two_stage_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                },
                {
                    "name": "report",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                    },
                    "inputs": {"data": "build.data"},
                    "outputs": {"text": {"artifact_type": "text"}},
                },
            ]
        }
    )


def test_write_stage_blocked_writes_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = write_stage_blocked(
        store,
        run_uri=run_uri,
        stage_name="downstream",
        attempt=1,
        blocked_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        blocked_by=["upstream"],
        reason_code="upstream_failed",
        metadata={"reason_details": {"exit_code": 2}},
    )

    assert record.status is StageStatus.BLOCKED
    assert record.started_at is None
    assert record.finished_at is None
    assert record.owner == {}
    assert record.metadata == {
        "blocked_by": ("upstream",),
        "reason_code": "upstream_failed",
        "reason_details": {"exit_code": 2},
    }
    assert store.read_stage_status(run_uri, "downstream") == record

    stage_dir = store.local_stage_dir(run_uri, "downstream")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]
    assert store.read_stage_inputs(run_uri, "downstream") is None
    assert store.read_stage_outputs(run_uri, "downstream") is None
    assert store.read_stage_fingerprint(run_uri, "downstream") is None
    assert store.read_stage_failure(run_uri, "downstream") is None
    assert store.read_stage_provenance(run_uri, "downstream") is None
    assert not (stage_dir / "logs").exists()
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_submitted_lifecycle_writers_do_not_set_execution_timestamps(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    run_record = write_run_submitted(
        store,
        run_uri=run_uri,
        created_at="2020-01-01T00:00:00Z",
        submitted_at="2020-01-01T00:00:01Z",
        metadata={"backend": "test-backend"},
    )
    stage_record = write_stage_submitted(
        store,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        submitted_at="2020-01-01T00:00:02Z",
        owner={"component": "submitter"},
        metadata={"submission_id": "sub-1"},
    )

    assert run_record.status is RunStatus.SUBMITTED
    assert run_record.started_at is None
    assert run_record.finished_at is None
    assert stage_record.status is StageStatus.SUBMITTED
    assert stage_record.started_at is None
    assert stage_record.finished_at is None
    assert store.read_run_status(run_uri) == run_record
    assert store.read_stage_status(run_uri, "build") == stage_record


def test_write_stage_running_records_reliability_transaction(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )

    record = write_stage_running(
        store,
        reliability=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
    )

    assert record.status is StageStatus.RUNNING
    details = store.list_reliability_status_details(run_uri, stage_name="build")
    transactions = store.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert [detail.stage_status for detail in details] == [StageStatus.RUNNING]
    assert [transaction.state for transaction in transactions] == [
        StageAttemptTransactionState.RUNNING
    ]


def test_retry_decision_denies_unsafe_transaction_chain(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    write_stage_running(
        store,
        reliability=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
    )
    record_stage_reliability_transition(
        store,
        run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        state=StageAttemptTransactionState.STAGED,
        stage_status=StageStatus.RUNNING,
        recorded_at="2020-01-01T00:00:03Z",
    )
    failure = persist_stage_failure(
        store,
        reliability=store, events=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
        failure=ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri=run_uri,
            stage_name="build",
            attempt=1,
            failed_at="2020-01-01T00:00:04Z",
            executor="local",
            failure_type="stage_exception",
            message="failed after staged outputs",
        ),
    )

    decision = record_retry_decision_for_stage_result(
        store,
        run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        stage_status=StageStatus.FAILED,
        recorded_at="2020-01-01T00:00:05Z",
        policy=RetryPolicy(enabled=True, max_attempts=2),
        failure=failure,
    )

    assert decision is not None
    assert decision.decision_reason == "retry.unsafe_transaction_state"
    assert decision.should_retry is False
    assert decision.next_attempt is None


def test_persist_stage_failure_classifies_and_records_failed_transaction(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:03Z",
        executor="local",
        failure_type="stage_exception",
        message="boom",
        exception_type="builtins.RuntimeError",
        executor_metadata={"executor": "local"},
        details={"source": "unit"},
    )

    observed = persist_stage_failure(
        store,
        reliability=store, events=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
        failure=failure,
        clock=lambda: "2020-01-01T00:00:04Z",
    )

    persisted = store.read_stage_failure(run_uri, "build")
    assert persisted is not None
    details = persisted["details"]
    assert isinstance(details, dict)
    classification = details["reliability_classification"]
    assert isinstance(classification, dict)
    assert classification["reason_code"] == "stage_exception"
    assert classification["retriable"] is True
    assert observed.details["reliability_classification"] == classification
    transactions = store.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert [transaction.state for transaction in transactions] == [
        StageAttemptTransactionState.FAILED
    ]
    assert transactions[0].status.stage_status is StageStatus.FAILED
    assert store.read_stage_status(run_uri, "build") is not None


def test_reliability_timeout_outcome_records_against_latest_transaction(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    write_stage_running(
        store,
        reliability=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
    )

    outcome = record_timeout_outcome_from_metadata(
        store,
        run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        stage_status=StageStatus.FAILED,
        recorded_at="2020-01-01T00:00:03Z",
        executor_metadata={
            "reliability_timeout": {
                "enabled": True,
                "timeout_domain": "reliability",
                "duration_seconds": 1.5,
                "support_level": "enforced",
                "outcome": "timed_out",
                "timed_out": True,
                "reason_code": "reliability.timeout.timed_out",
            }
        },
    )

    assert outcome is not None
    assert outcome.outcome is TimeoutOutcome.TIMED_OUT
    assert outcome.support_level is TimeoutSupportLevel.ENFORCED
    assert outcome.timed_out is True
    assert (
        outcome.transaction_id
        == store.list_stage_attempt_transactions(run_uri, stage_name="build")[
            0
        ].transaction_id
    )
    persisted = store.list_timeout_outcomes(run_uri, stage_name="build")
    assert persisted == (outcome,)


def test_persist_stage_cancellation_records_cancelled_transaction(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )

    persist_stage_cancellation(
        store,
        reliability=store, events=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage_name="build",
        attempt=1,
        started_at="2020-01-01T00:00:02Z",
        cancelled_at="2020-01-01T00:00:03Z",
        reason=LifecycleReason(code="cancelled", message="stopped"),
        clock=lambda: "2020-01-01T00:00:04Z",
    )

    transactions = store.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert [transaction.state for transaction in transactions] == [
        StageAttemptTransactionState.CANCELLED
    ]
    assert transactions[0].status.stage_status is StageStatus.CANCELLED
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status is StageStatus.CANCELLED


def test_write_stage_blocked_requires_message_and_reason_code_when_present(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    with pytest.raises(ValueError, match="message"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="",
        )

    with pytest.raises(ValueError, match="reason_code"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="blocked",
            reason_code="",
        )


def test_bind_stage_inputs_uses_pending_outputs_without_status_side_effects(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    spec = _two_stage_spec()
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    report_plan = plan.ordered_stage_plans[1]

    inputs = bind_stage_inputs(
        stage=spec.get_stage("report"),
        stage_plan=report_plan,
        produced_outputs={"build": {"data": _ref()}},
    )

    assert inputs == {"data": _ref()}
    assert store.read_stage_status(run_uri, "report") is None
    with pytest.raises(PlanExecutionError, match="Cannot bind input"):
        bind_stage_inputs(
            stage=spec.get_stage("report"),
            stage_plan=report_plan,
            produced_outputs={},
        )


def test_write_stage_artifact_index_refs_preserves_merge_semantics(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    existing = _ref("old", "data")
    store.write_artifact_index(run_uri, {"build.data": existing})

    write_stage_artifact_index_refs(
        store,
        run_uri=run_uri,
        stage_name="report",
        outputs={"text": _ref("report", "text")},
        replace=False,
    )

    assert store.read_artifact_index(run_uri) == {
        "build.data": existing,
        "report.text": _ref("report", "text"),
    }


@pytest.mark.parametrize("intent", [TransitionIntent.RESUME, TransitionIntent.RECOVERY])
def test_local_status_projection_refuses_authority_intent_without_mutation(
    tmp_path: Path, intent: TransitionIntent,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="authority transition intent"):
        write_run_status(
            store,
            run_uri=run_uri,
            status=RunStatus.RUNNING,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            intent=intent,
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("finalize", [False, True])
def test_failed_commit_records_timeout_after_run_finalization(
    tmp_path: Path, finalize: bool,
) -> None:
    from loom.pipeline.reliability import TimeoutPolicy
    from loom.pipeline.executors._reliability import metadata_with_timeout, timeout_metadata

    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    started = "2020-01-01T00:00:01Z"
    finished = "2020-01-01T00:00:02Z"
    write_run_status(
        store, run_uri=run_uri, status=RunStatus.RUNNING,
        created_at=started, updated_at=started, started_at=started,
    )
    spec = _two_stage_spec()
    artifacts = LocalArtifactStore(store.local_artifact_root(run_uri))
    plan = plan_pipeline(
        spec, run_uri=run_uri, stage_state=store,
        artifact_index=store, artifact_store=artifacts,
    )
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION, run_uri=run_uri,
        stage_name="build", attempt=1, failed_at=finished, executor="local",
        failure_type="executor_infrastructure", message="deadline exceeded",
    )
    metadata = metadata_with_timeout({}, timeout_metadata(
        policy=TimeoutPolicy(enabled=True, duration_seconds=1),
        support_level=TimeoutSupportLevel.ENFORCED, outcome=TimeoutOutcome.TIMED_OUT,
        timed_out=True, message="deadline exceeded",
    ))
    result = StageExecutionResult(
        stage_name="build", status=StageStatus.FAILED, outputs={}, failure=failure,
        started_at=started, finished_at=finished, executor_name="local", attempt=1,
        executor_metadata=metadata,
    )
    committed = commit_stage_execution_result(
        store, run_status_store=store, artifact_index=store, reliability=store,
        events=store, run_status=RunStatus.RUNNING, run_uri=run_uri,
        stage=spec.get_stage("build"), stage_plan=plan.ordered_stage_plans[0],
        attempt=1, inputs={}, fingerprint={}, artifact_store=artifacts,
        created_at=started, run_started_at=started, execution_result=result,
        executor_name="local", finalize_run_on_failure=finalize,
        clock=lambda: finished,
    )
    assert committed.status is StageStatus.FAILED
    expected = RunStatus.FAILED if finalize else RunStatus.RUNNING
    status = store.read_run_status(run_uri)
    assert status is not None and status.status is expected
    outcomes = store.list_timeout_outcomes(run_uri, stage_name="build")
    assert len(outcomes) == 1
    assert outcomes[0].status.run_status is expected
    transactions = store.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert [item.state for item in transactions] == [StageAttemptTransactionState.FAILED]
    assert transactions[0].status.run_status is RunStatus.RUNNING
    assert outcomes[0].transaction_id == transactions[0].transaction_id
    assert [event.event_type for event in store.read_events(run_uri)] == ["stage.failed"]


@pytest.mark.parametrize("index_failure", [False, True])
def test_output_commit_uses_distinct_owners_and_preserves_commit_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_failure: bool,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    index_owner = LocalRunStore(tmp_path / "runs")
    events = LocalRunStore(tmp_path / "runs")
    reliability = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    artifacts = LocalArtifactStore(store.local_artifact_root(run_uri))
    spec = _two_stage_spec()
    plan = plan_pipeline(
        spec, run_uri=run_uri, stage_state=store,
        artifact_index=index_owner, artifact_store=artifacts,
    )
    ref = artifacts.save(
        {"answer": 42}, stage_name="build", name="data",
        artifact_type="json", codec_key="json.v1",
    )
    started, finished = "2020-01-01T00:00:01Z", "2020-01-01T00:00:02Z"
    result = StageExecutionResult(
        stage_name="build", status=StageStatus.SUCCEEDED, outputs={"data": ref},
        failure=None, started_at=started, finished_at=finished,
        executor_name="local", attempt=1,
    )

    def wrong_owner(*args, **kwargs):
        raise AssertionError("stage-state owner used for an unrelated service")

    monkeypatch.setattr(store, "read_artifact_index", wrong_owner)
    monkeypatch.setattr(store, "append_event", wrong_owner)
    monkeypatch.setattr(store, "list_stage_attempt_transactions", wrong_owner)
    if index_failure:
        def fail_index(*args, **kwargs):
            assert store.read_stage_outputs(run_uri, "build") == {"data": ref}
            assert store.read_stage_status(run_uri, "build") is None
            assert events.read_events(run_uri) == ()
            raise OSError("index publication failed")
        monkeypatch.setattr(index_owner, "write_artifact_index", fail_index)

    def commit():
        return commit_stage_execution_result(
            store, run_status_store=store, artifact_index=index_owner,
            reliability=reliability, events=events, run_status=RunStatus.RUNNING,
            run_uri=run_uri, stage=spec.get_stage("build"),
            stage_plan=plan.ordered_stage_plans[0], attempt=1, inputs={},
            fingerprint={}, artifact_store=artifacts, created_at=started,
            run_started_at=started, execution_result=result, executor_name="local",
            clock=lambda: finished,
        )

    if index_failure:
        with pytest.raises(OSError, match="index publication failed"):
            commit()
        assert store.read_stage_status(run_uri, "build") is None
        assert events.read_events(run_uri) == ()
        assert index_owner.read_artifact_index(run_uri) == {}
    else:
        assert commit().outputs == {"data": ref}
        assert index_owner.read_artifact_index(run_uri) == {"build.data": ref}
        status = store.read_stage_status(run_uri, "build")
        assert status is not None and status.status is StageStatus.SUCCEEDED
        assert store.read_stage_provenance(run_uri, "build") is not None
        assert [event.event_type for event in events.read_events(run_uri)] == ["stage.completed"]
        assert artifacts.load(ref) == {"answer": 42}
    transactions = reliability.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert len(transactions) == 2
    by_state = {item.state: item for item in transactions}
    terminal_state = (
        StageAttemptTransactionState.COMMIT_FAILED if index_failure
        else StageAttemptTransactionState.COMMITTED
    )
    assert set(by_state) == {StageAttemptTransactionState.STAGED, terminal_state}
    staged, terminal = by_state[StageAttemptTransactionState.STAGED], by_state[terminal_state]
    assert staged.causal_parent_id is None
    assert terminal.causal_parent_id == staged.transaction_id
    assert reliability.read_transaction_chain(run_uri, terminal.transaction_id) == (staged, terminal)
