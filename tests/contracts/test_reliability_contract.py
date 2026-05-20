"""Contracts for reliability policy and record plain-data models."""

from __future__ import annotations

from textwrap import dedent
import subprocess
import sys

import pytest

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
    TimeoutPolicy,
    TimeoutSupportLevel,
)
from loom.serialization import stable_json_dumps


pytestmark = pytest.mark.contract


def test_reliability_policies_are_stable_plain_data() -> None:
    policy = ReliabilityPolicy(
        retry=RetryPolicy(enabled=False, max_attempts=1),
        timeout=TimeoutPolicy(enabled=True, duration_seconds=42),
    )
    assert stable_json_dumps(policy.to_dict())
    assert ReliabilityPolicy.from_dict(policy.to_dict()) == policy
    timeout = policy.to_dict()["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["duration_seconds"] == 42


def test_reliability_records_are_round_tripped_with_plain_data_contract() -> None:
    status = ReliabilityStatusDetail(
        run_uri="runs/demo",
        run_status="RUNNING",
        stage_id="train",
        stage_status="RUNNING",
        attempt=1,
        created_at="2026-01-01T12:00:00Z",
    )
    failure = FailureClassification(
        reason_code="stage.retry",
        retriable=True,
        details={"detail": "sample"},
        status=status,
    )
    decision = RetryDecisionRecord(
        decision_id="decision-1",
        transaction_id="tx-1",
        should_retry=True,
        next_attempt=2,
        decision_reason="policy.allows",
        policy_max_attempts=3,
        attempt_count=1,
        status=status,
        failure=failure,
    )
    timeout_outcome = TimeoutOutcomeRecord(
        outcome_id="timeout-1",
        transaction_id="tx-1",
        timed_out=True,
        duration_seconds=1.5,
        reason_code="runtime.timeout",
        outcome=TimeoutOutcome.TIMED_OUT,
        support_level=TimeoutSupportLevel.ENFORCED,
        status=status,
    )
    transaction = StageAttemptTransaction(
        transaction_id="tx-1",
        run_uri="runs/demo",
        stage_id="train",
        attempt=1,
        status=status,
        state=StageAttemptTransactionState.RUNNING,
    )

    assert stable_json_dumps(status.to_dict())
    assert stable_json_dumps(decision.to_dict())
    assert stable_json_dumps(timeout_outcome.to_dict())
    assert stable_json_dumps(transaction.to_dict())

    assert ReliabilityStatusDetail.from_dict(status.to_dict()) == status
    assert RetryDecisionRecord.from_dict(decision.to_dict()) == decision
    assert TimeoutOutcomeRecord.from_dict(timeout_outcome.to_dict()) == timeout_outcome
    assert timeout_outcome.to_dict()["outcome"] == "timed_out"
    assert timeout_outcome.to_dict()["support_level"] == "enforced"
    legacy_timeout = {
        key: value
        for key, value in timeout_outcome.to_dict().items()
        if key not in {"outcome", "support_level"}
    }
    assert TimeoutOutcomeRecord.from_dict(
        legacy_timeout
    ).outcome is TimeoutOutcome.TIMED_OUT
    assert StageAttemptTransaction.from_dict(transaction.to_dict()) == transaction
    assert transaction.to_dict()["state"] == "running"
    legacy_payload = {
        key: value for key, value in transaction.to_dict().items() if key != "state"
    }
    assert StageAttemptTransaction.from_dict(
        legacy_payload
    ).state is StageAttemptTransactionState.UNSPECIFIED


def test_importing_reliability_contracts_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline import reliability

        for forbidden in (
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.cli",
            "weave",
            "loom.authority",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through loom.pipeline.reliability")

        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
