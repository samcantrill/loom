"""Unit tests for diagnostics status and log inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.diagnostics.inspection import (
    DiagnosticsInspectionError,
    inspect_run_artifact,
    inspect_run_artifacts,
    inspect_run_status,
    inspect_stage_logs,
)
from loom.pipeline.reliability import (
    FailureClassification,
    ReliabilityPolicy,
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    RetryPolicy,
    StageAttemptTransaction,
    StageAttemptTransactionState,
    TimeoutOutcome,
    TimeoutOutcomeRecord,
    TimeoutSupportLevel,
)
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import (
    LocalRunStore,
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
    path_to_run_uri,
    run_uri_to_path,
)
from loom.pipeline.stores.sqlite_authority import (
    SQLitePerRunAuthorityStore,
    _authority_database_path,
)
from loom.pipeline import PipelineRunner, RunRequest
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


pytestmark = pytest.mark.unit


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _store_with_stage(tmp_path: Path) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.RUNNING,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.RUNNING,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    return store, run_uri


def _authority_store_with_stage(tmp_path: Path) -> tuple[Any, str]:
    store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
    )
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.RUNNING,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.RUNNING,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    return store, run_uri


def _artifact_ref(
    *,
    artifact_id: str = "build/data",
    artifact_type: str = "json",
    producer_stage: str = "build",
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        uri=f"file:///tmp/{artifact_id}",
        artifact_type=artifact_type,
        codec_key="json.v1" if artifact_type == "json" else "text.v1",
        producer_stage=producer_stage,
        metadata={"label": artifact_id},
    )


def _write_reliability_records(store: Any, run_uri: str) -> None:
    status = ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=RunStatus.RUNNING,
        stage_id="build",
        stage_status=StageStatus.FAILED,
        attempt=1,
        created_at="2020-01-01T00:00:03Z",
    )
    store.write_reliability_policy_fact(
        run_uri,
        ReliabilityPolicyFact(
            run_uri=run_uri,
            scope=ReliabilityPolicyScope.STAGE,
            stage_name="build",
            recorded_at="2020-01-01T00:00:01Z",
            policy=ReliabilityPolicy(
                retry=RetryPolicy(enabled=True, max_attempts=2),
            ),
        ),
    )
    store.write_reliability_status_detail(run_uri, status)
    transaction = StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri=run_uri,
        stage_id="build",
        attempt=1,
        status=status,
        state=StageAttemptTransactionState.FAILED,
    )
    store.write_stage_attempt_transaction(run_uri, transaction)
    failure = FailureClassification(
        reason_code="stage_exception",
        status=status,
        retriable=True,
        details={"failure_type": "stage_exception"},
    )
    store.write_retry_decision(
        run_uri,
        RetryDecisionRecord(
            decision_id="retry-1",
            transaction_id=transaction.transaction_id,
            should_retry=False,
            next_attempt=None,
            decision_reason="retry.disabled",
            policy_max_attempts=2,
            attempt_count=1,
            status=status,
            failure=failure,
        ),
    )
    store.write_timeout_outcome(
        run_uri,
        TimeoutOutcomeRecord(
            outcome_id="timeout-1",
            transaction_id=transaction.transaction_id,
            timed_out=False,
            duration_seconds=2.0,
            reason_code="timeout.unsupported",
            outcome=TimeoutOutcome.UNSUPPORTED,
            support_level=TimeoutSupportLevel.UNSUPPORTED,
            status=status,
        ),
    )


def test_inspect_run_status_uses_store_scan(tmp_path: Path) -> None:
    store, run_uri = _authority_store_with_stage(tmp_path)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.run_uri == run_uri
    assert summary.status == "SUCCEEDED"
    assert summary.state_source["label"] == "authoritative_service_truth"
    assert summary.stages[0].stage_name == "build"
    assert summary.stages[0].status == "SUCCEEDED"
    assert summary.stages[0].state_source["label"] == "authoritative_service_truth"
    assert summary.stages[0].log_source["label"] == "materialized_local_state"
    assert summary.stages[0].log_available == {"stdout": False, "stderr": False}


def test_inspect_run_status_includes_submitted_operation_summaries(
    tmp_path: Path,
) -> None:
    store, run_uri = _authority_store_with_stage(tmp_path)
    record = SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="test-backend",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1/manifest.json",
        summary_counts={"submitted": 1},
    )
    store.write_submitted_operation(run_uri, record)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.submitted_operations[0].submission_id == "sub-1"
    assert summary.submitted_operations[0].active is True
    assert (
        summary.submitted_operations[0].state_source["label"]
        == "authoritative_service_truth"
    )
    operations = cast(
        list[dict[str, object]], summary.to_dict()["submitted_operations"]
    )
    assert operations[0]["backend"] == "test-backend"


def test_inspect_run_status_includes_reliability_summaries(
    tmp_path: Path,
) -> None:
    store, run_uri = _authority_store_with_stage(tmp_path)
    _write_reliability_records(store, run_uri)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.reliability is not None
    assert summary.reliability.to_dict()["counts"] == {
        "run_policy_facts": 0,
        "stage_policy_facts": 1,
        "status_details": 1,
        "transactions": 1,
        "retry_decisions": 1,
        "timeout_outcomes": 1,
        "unsupported_timeouts": 1,
    }
    reliability = summary.stages[0].reliability
    assert reliability is not None
    assert reliability.latest_policy is not None
    assert reliability.latest_policy["policy"] == {
        "retry": {"enabled": True, "max_attempts": 2}
    }
    assert reliability.latest_transaction is not None
    assert reliability.latest_transaction["state"] == "failed"
    assert reliability.latest_retry_decision is not None
    assert reliability.latest_retry_decision["decision_reason"] == "retry.disabled"
    assert reliability.latest_timeout_outcome is not None
    assert reliability.latest_timeout_outcome["outcome"] == "unsupported"
    assert reliability.diagnostics[0]["code"] == "reliability.timeout.unsupported"
    payload = summary.to_dict()
    stages_payload = cast(list[object], payload["stages"])
    stage_payload = cast(dict[str, object], stages_payload[0])
    reliability_payload = cast(dict[str, object], stage_payload["reliability"])
    counts = cast(dict[str, object], reliability_payload["counts"])
    assert counts["retry_decisions"] == 1


def test_inspect_run_status_rejects_local_only_lifecycle_state(
    tmp_path: Path,
) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="local-only lifecycle"):
        inspect_run_status(run_uri, run_store=store)


def test_inspect_run_status_uses_authoritative_facts_over_corrupt_legacy_files(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    run_path = run_uri_to_path(run_uri)
    (run_path / "status.json").write_text("not json", encoding="utf-8")
    (run_path / "artifacts.json").write_text("not json", encoding="utf-8")
    (run_path / "stages" / "build" / "status.json").write_text(
        "not json", encoding="utf-8"
    )

    summary = inspect_run_status(run_uri, run_store=store)
    artifacts = inspect_run_artifacts(run_uri, run_store=store)

    assert summary.status == "SUCCEEDED"
    assert {stage.stage_name: stage.status for stage in summary.stages} == {
        "build": "SUCCEEDED",
        "report": "SUCCEEDED",
    }
    assert {artifact.key for artifact in artifacts.artifacts} == {
        "build.data",
        "report.text",
    }


def test_default_status_read_rejects_missing_authority_backend(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    _authority_database_path(run_uri).unlink()

    with pytest.raises(DiagnosticsInspectionError, match="authoritative backend"):
        inspect_run_status(run_uri)
    with pytest.raises(DiagnosticsInspectionError, match="authoritative backend"):
        inspect_run_artifacts(run_uri)


def test_inspect_stage_logs_tails_each_stream(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    store.write_stage_log(run_uri, "build", "stderr", "err\n")

    summary = inspect_stage_logs(
        run_uri, "build", streams=("stdout", "stderr"), tail=2, run_store=store
    )

    assert summary.streams[0].stream == "stdout"
    assert summary.streams[0].content == "b\nc\n"
    assert summary.streams[0].line_count == 3
    assert summary.streams[0].displayed_line_count == 2
    assert summary.streams[0].truncated is True
    assert summary.streams[0].state_source["label"] == "materialized_local_state"
    assert summary.state_source["label"] == "materialized_local_state"
    assert summary.streams[1].content == "err\n"


def test_inspect_stage_logs_paths_only_allows_missing_logs(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    summary = inspect_stage_logs(run_uri, "build", paths_only=True, run_store=store)

    assert [stream.available for stream in summary.streams] == [False, False]
    assert all(stream.content is None for stream in summary.streams)


def test_inspect_stage_logs_rejects_missing_stage(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="unknown stage"):
        inspect_stage_logs(run_uri, "missing", run_store=store)


def test_inspect_stage_logs_requires_content_without_paths_only(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="no log content"):
        inspect_stage_logs(run_uri, "build", run_store=store)


def test_inspect_run_artifacts_sorts_and_summarizes_metadata(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_provenance(run_uri, "build", {"tool": "loom"}, attempt=1)
    store.write_artifact_index(
        run_uri,
        {
            "report.text": _artifact_ref(
                artifact_id="report/text",
                artifact_type="text",
                producer_stage="report",
            ),
            "build.data": _artifact_ref(),
        },
    )

    summary = inspect_run_artifacts(run_uri, run_store=store)

    assert summary.artifact_count == 2
    assert summary.state_source["label"] == "materialized_local_state"
    assert [artifact.key for artifact in summary.artifacts] == [
        "build.data",
        "report.text",
    ]
    build = summary.artifacts[0]
    assert build.artifact_id == "build/data"
    assert build.stage_name == "build"
    assert build.output_name == "data"
    assert build.metadata == {"label": "build/data"}
    assert build.provenance_available is True
    assert build.state_source["label"] == "materialized_local_state"
    assert build.to_dict()["artifact_type"] == "json"


def test_inspect_run_artifact_includes_stage_provenance(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_provenance(run_uri, "build", {"tool": "loom"}, attempt=1)
    store.write_artifact_index(run_uri, {"build.data": _artifact_ref()})

    detail = inspect_run_artifact(run_uri, "build/data", run_store=store)

    assert detail.artifact.key == "build.data"
    assert detail.state_source["label"] == "materialized_local_state"
    assert detail.stage_provenance == {"tool": "loom"}
    assert detail.to_dict()["stage_provenance"] == {"tool": "loom"}


def test_inspect_run_artifact_rejects_missing_artifact(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="unknown artifact"):
        inspect_run_artifact(run_uri, "missing/out", run_store=store)


def test_inspect_run_artifact_rejects_ambiguous_artifact_id(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_artifact_index(
        run_uri,
        {
            "build.data": _artifact_ref(artifact_id="duplicate/id"),
            "report.text": _artifact_ref(
                artifact_id="duplicate/id",
                artifact_type="text",
                producer_stage="report",
            ),
        },
    )

    with pytest.raises(DiagnosticsInspectionError, match="ambiguous artifact"):
        inspect_run_artifact(run_uri, "duplicate/id", run_store=store)
