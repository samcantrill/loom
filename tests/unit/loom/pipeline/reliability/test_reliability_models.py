"""Unit tests for reliability policy and record contract models."""

from __future__ import annotations

import pytest

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.reliability import (
    FailureClassification,
    RetryDecisionRecord,
    ReliabilityPolicy,
    ReliabilityStatusDetail,
    ReliabilityTransactionStore,
    ReliabilityRecordStore,
    RetryPolicy,
    RetryEvaluator,
    StageAttemptTransaction,
    StageAttemptTransactionState,
    TimeoutOutcomeRecord,
    TimeoutPolicy,
    merge_reliability_options,
)


pytestmark = pytest.mark.unit


def test_retry_policy_round_trip_and_validation() -> None:
    policy = RetryPolicy(enabled=True, max_attempts=3)

    assert policy.to_dict() == {"enabled": True, "max_attempts": 3}
    assert RetryPolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(RuntimeResourceError):
        RetryPolicy.from_dict({"enabled": True, "max_attempts": 0})
    with pytest.raises(RuntimeResourceError, match="unknown field"):
        RetryPolicy.from_dict({"enabled": True, "max_attempts": 3, "extra": 1})


def test_timeout_policy_requires_duration_for_enabled_true() -> None:
    policy = TimeoutPolicy(enabled=False)

    assert policy.to_dict() == {"enabled": False, "duration_seconds": None}
    assert TimeoutPolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(RuntimeResourceError, match="requires duration_seconds"):
        TimeoutPolicy(enabled=True, duration_seconds=None)
    with pytest.raises(RuntimeResourceError, match="positive"):
        TimeoutPolicy.from_dict({"enabled": True, "duration_seconds": 0})


def test_reliability_policy_uses_defaults_and_merges_stage_override() -> None:
    assert ReliabilityPolicy.defaults().to_dict() == {
        "retry": {"enabled": False, "max_attempts": 1},
    }
    base = ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=3),
        timeout=TimeoutPolicy(enabled=True, duration_seconds=15),
    )
    merged = merge_reliability_options(base, ReliabilityPolicy(timeout=TimeoutPolicy(enabled=False)))
    assert merged == ReliabilityPolicy(
        retry=RetryPolicy(enabled=True, max_attempts=3),
        timeout=TimeoutPolicy(enabled=False),
    )


def test_reliability_policy_rejects_unknown_fields_and_shape() -> None:
    with pytest.raises(RuntimeResourceError, match="unknown field"):
        ReliabilityPolicy.from_dict(
            {"retry": {"enabled": False, "max_attempts": 2}, "extra": True}
        )


def test_reliability_status_detail_round_trip_and_timestamp_validation() -> None:
    status = ReliabilityStatusDetail(
        run_uri="runs/demo",
        run_status="RUNNING",
        stage_id="train",
        stage_status="RUNNING",
        attempt=1,
        created_at="2026-01-01T12:00:00Z",
    )

    payload = status.to_dict()
    assert ReliabilityStatusDetail.from_dict(payload) == status
    with pytest.raises(RuntimeResourceError):
        ReliabilityStatusDetail.from_dict(
            {
                **payload,
                "created_at": "not-a-timestamp",
            }
        )


def test_failure_classification_round_trip_is_plain_data() -> None:
    status = ReliabilityStatusDetail(
        run_uri="runs/demo",
        run_status="FAILED",
        stage_id="train",
        stage_status="FAILED",
        attempt=1,
        created_at="2026-01-01T12:00:00Z",
    )
    payload = FailureClassification(
        reason_code="runtime.error",
        retriable=False,
        details={"trace": "example"},
        status=status,
    )

    assert FailureClassification.from_dict(payload.to_dict()) == payload
    with pytest.raises(RuntimeResourceError, match="bool"):
        FailureClassification(
            reason_code="runtime.error",
            retriable="yes",  # type: ignore[arg-type]
            details={},
            status=status,
        )
    with pytest.raises(RuntimeResourceError):
        FailureClassification.from_dict(
            {
                "reason_code": "runtime.error",
                "details": {"trace": "missing"},
                "status": status.to_dict(),
                "retriable": True,
                "extra": "blocklist",
            }
        )


def test_stage_attempt_transaction_round_trip() -> None:
    status = ReliabilityStatusDetail(
        run_uri="runs/demo",
        run_status="RUNNING",
        stage_id="train",
        stage_status="RUNNING",
        attempt=2,
        created_at="2026-01-01T12:00:01Z",
    )
    transaction = StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri="runs/demo",
        stage_id="train",
        attempt=2,
        status=status,
        state=StageAttemptTransactionState.RUNNING,
    )

    payload = transaction.to_dict()
    assert payload["state"] == "running"
    assert StageAttemptTransaction.from_dict(payload) == transaction
    missing_state_payload = {
        key: value for key, value in payload.items() if key != "state"
    }
    assert StageAttemptTransaction.from_dict(
        missing_state_payload
    ).state is StageAttemptTransactionState.UNSPECIFIED
    with pytest.raises(RuntimeResourceError):
        StageAttemptTransaction.from_dict({**payload, "attempt": 0})
    with pytest.raises(RuntimeResourceError, match="StageAttemptTransaction.state"):
        StageAttemptTransaction.from_dict({**payload, "state": "unknown"})


def test_retry_and_timeout_records_round_trip() -> None:
    status = ReliabilityStatusDetail(
        run_uri="runs/demo",
        run_status="RUNNING",
        stage_id="train",
        stage_status="FAILED",
        attempt=1,
        created_at="2026-01-01T12:00:02Z",
    )
    failure = FailureClassification(
        reason_code="runtime.error",
        retriable=True,
        details={"code": 1},
        status=status,
    )
    decision = RetryDecisionRecord(
        decision_id="retry-1",
        transaction_id="tx-1",
        should_retry=True,
        next_attempt=2,
        decision_reason="retry_allowed",
        policy_max_attempts=2,
        attempt_count=1,
        status=status,
        failure=failure,
    )
    outcome = TimeoutOutcomeRecord(
        outcome_id="timeout-1",
        transaction_id="tx-1",
        timed_out=False,
        duration_seconds=10,
        reason_code="test.timeout",
        status=status,
    )

    assert RetryDecisionRecord.from_dict(decision.to_dict()) == decision
    assert TimeoutOutcomeRecord.from_dict(outcome.to_dict()) == outcome
    with pytest.raises(RuntimeResourceError, match="bool"):
        RetryDecisionRecord(
            decision_id="retry-2",
            transaction_id="tx-1",
            should_retry="yes",  # type: ignore[arg-type]
            next_attempt=None,
            decision_reason="invalid",
            policy_max_attempts=1,
            attempt_count=1,
            status=status,
            failure=failure,
        )
    with pytest.raises(RuntimeResourceError, match="bool"):
        TimeoutOutcomeRecord(
            outcome_id="timeout-2",
            transaction_id="tx-1",
            timed_out="no",  # type: ignore[arg-type]
            duration_seconds=10,
            reason_code="invalid",
            status=status,
        )


def test_protocol_types_are_importable_and_protocol_only() -> None:
    assert isinstance(ReliabilityRecordStore, type)
    assert isinstance(ReliabilityTransactionStore, type)
    assert isinstance(RetryEvaluator, type)
