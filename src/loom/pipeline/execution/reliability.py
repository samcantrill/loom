"""Execution-owned reliability transaction and classification helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from loom.pipeline.reliability import (
    FailureClassification,
    ReliabilityStatusDetail,
    StageAttemptTransaction,
    StageAttemptTransactionState,
    TimeoutOutcome,
    TimeoutOutcomeRecord,
    TimeoutSupportLevel,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LegacyRunStore, RunReliabilityStore
from loom.serialization import PlainData, ensure_plain_data, stable_json_dumps

from .models import ExecutionFailure


_RETRIABLE_FAILURE_TYPES = frozenset({"stage_exception", "executor_infrastructure"})
_TIMEOUT_METADATA_KEY = "reliability_timeout"
_TRANSACTION_STATE_ORDER = {
    StageAttemptTransactionState.UNSPECIFIED: 0,
    StageAttemptTransactionState.PREPARED: 10,
    StageAttemptTransactionState.RUNNING: 20,
    StageAttemptTransactionState.STAGED: 30,
    StageAttemptTransactionState.COMMITTED: 40,
    StageAttemptTransactionState.COMMIT_FAILED: 50,
    StageAttemptTransactionState.FAILED: 60,
    StageAttemptTransactionState.CANCELLED: 60,
}


def build_reliability_status_detail(
    run_store: LegacyRunStore,
    *,
    run_uri: str,
    stage_name: str,
    stage_status: StageStatus,
    attempt: int,
    created_at: str,
) -> ReliabilityStatusDetail:
    return ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=_current_run_status(run_store, run_uri),
        stage_id=stage_name,
        stage_status=stage_status,
        attempt=attempt,
        created_at=created_at,
    )


def classify_execution_failure(
    failure: ExecutionFailure,
    *,
    status: ReliabilityStatusDetail,
) -> FailureClassification:
    if not isinstance(failure, ExecutionFailure):
        raise TypeError("failure must be an ExecutionFailure")
    details = _classification_details(failure)
    return FailureClassification(
        reason_code=_failure_reason_code(failure),
        retriable=failure.failure_type in _RETRIABLE_FAILURE_TYPES,
        details=details,
        status=status,
    )


def failure_with_reliability_classification(
    failure: ExecutionFailure,
    classification: FailureClassification,
) -> ExecutionFailure:
    details = dict(failure.details)
    details["reliability_classification"] = classification.to_dict()
    return replace(failure, details=details)


def record_stage_reliability_transition(
    run_store: LegacyRunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    state: StageAttemptTransactionState,
    stage_status: StageStatus,
    recorded_at: str,
) -> StageAttemptTransaction | None:
    detail = build_reliability_status_detail(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        stage_status=stage_status,
        attempt=attempt,
        created_at=recorded_at,
    )
    return record_reliability_transaction(
        run_store,
        run_uri=run_uri,
        status=detail,
        state=state,
    )


def record_reliability_transaction(
    run_store: LegacyRunStore,
    *,
    run_uri: str,
    status: ReliabilityStatusDetail,
    state: StageAttemptTransactionState,
) -> StageAttemptTransaction | None:
    if not isinstance(run_store, RunReliabilityStore):
        return None
    parent_id = _latest_transaction_id(
        run_store,
        run_uri=run_uri,
        stage_name=status.stage_id,
        attempt=status.attempt,
    )
    transaction = StageAttemptTransaction(
        transaction_id=_transaction_id(
            run_uri=run_uri,
            stage_name=status.stage_id,
            attempt=status.attempt,
            state=state,
            recorded_at=status.created_at,
        ),
        run_uri=run_uri,
        stage_id=status.stage_id,
        attempt=status.attempt,
        status=status,
        state=state,
        causal_parent_id=parent_id,
    )
    run_store.write_reliability_status_detail(run_uri, status)
    run_store.write_stage_attempt_transaction(run_uri, transaction)
    return transaction


def record_timeout_outcome_from_metadata(
    run_store: LegacyRunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    stage_status: StageStatus,
    recorded_at: str,
    executor_metadata: object,
) -> TimeoutOutcomeRecord | None:
    metadata = _timeout_metadata(executor_metadata)
    if metadata is None or not isinstance(run_store, RunReliabilityStore):
        return None
    transaction_id = _latest_transaction_id(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
    )
    if transaction_id is None:
        return None
    status = build_reliability_status_detail(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        stage_status=stage_status,
        attempt=attempt,
        created_at=recorded_at,
    )
    outcome = TimeoutOutcomeRecord(
        outcome_id=_timeout_outcome_id(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            transaction_id=transaction_id,
            outcome=_timeout_outcome(metadata),
            recorded_at=recorded_at,
        ),
        transaction_id=transaction_id,
        timed_out=_bool_metadata(metadata, "timed_out"),
        duration_seconds=_positive_float_metadata(metadata, "duration_seconds"),
        reason_code=_string_metadata(metadata, "reason_code"),
        outcome=_timeout_outcome(metadata),
        support_level=_timeout_support_level(metadata),
        status=status,
    )
    run_store.write_timeout_outcome(run_uri, outcome)
    return outcome


def _current_run_status(run_store: LegacyRunStore, run_uri: str) -> RunStatus:
    record = run_store.read_run_status(run_uri)
    if record is None:
        return RunStatus.RUNNING
    return record.status


def _latest_transaction_id(
    run_store: RunReliabilityStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> str | None:
    transactions = [
        transaction
        for transaction in run_store.list_stage_attempt_transactions(
            run_uri,
            stage_name=stage_name,
        )
        if transaction.attempt == attempt
    ]
    if not transactions:
        return None
    latest = sorted(
        transactions,
        key=lambda transaction: (
            transaction.status.created_at,
            _TRANSACTION_STATE_ORDER[
                cast(StageAttemptTransactionState, transaction.state)
            ],
            transaction.transaction_id,
        ),
    )[-1]
    return latest.transaction_id


def _transaction_id(
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    state: StageAttemptTransactionState,
    recorded_at: str,
) -> str:
    digest = hashlib.sha256(
        stable_json_dumps(
            {
                "run_uri": run_uri,
                "stage_name": stage_name,
                "attempt": attempt,
                "state": state.value,
                "recorded_at": recorded_at,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"tx-{digest[:32]}"


def _timeout_outcome_id(
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    transaction_id: str,
    outcome: TimeoutOutcome,
    recorded_at: str,
) -> str:
    digest = hashlib.sha256(
        stable_json_dumps(
            {
                "run_uri": run_uri,
                "stage_name": stage_name,
                "attempt": attempt,
                "transaction_id": transaction_id,
                "outcome": outcome.value,
                "recorded_at": recorded_at,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"timeout-{digest[:32]}"


def _failure_reason_code(failure: ExecutionFailure) -> str:
    if _failure_timed_out(failure):
        return "reliability.timeout.timed_out"
    if failure.signal is not None:
        return "executor_signal"
    if failure.exit_code is not None and failure.exit_code != 0:
        return "executor_exit_code"
    return failure.failure_type


def _failure_timed_out(failure: ExecutionFailure) -> bool:
    metadata = _timeout_metadata(failure.executor_metadata)
    if metadata is None:
        metadata = _timeout_metadata(failure.details)
    return metadata is not None and _bool_metadata(metadata, "timed_out")


def _timeout_metadata(value: object) -> dict[str, PlainData] | None:
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[str, object], value).get(_TIMEOUT_METADATA_KEY)
    if raw is None:
        raw = cast(Mapping[str, object], value).get("timeout")
    if not isinstance(raw, dict):
        return None
    normalized = ensure_plain_data(raw, path=_TIMEOUT_METADATA_KEY)
    if not isinstance(normalized, dict):
        return None
    return cast(dict[str, PlainData], normalized)


def _timeout_outcome(metadata: Mapping[str, PlainData]) -> TimeoutOutcome:
    value = _string_metadata(metadata, "outcome")
    try:
        return TimeoutOutcome(value)
    except ValueError as exc:
        valid = ", ".join(outcome.value for outcome in TimeoutOutcome)
        raise ValueError(f"timeout outcome must be one of: {valid}") from exc


def _timeout_support_level(metadata: Mapping[str, PlainData]) -> TimeoutSupportLevel:
    value = _string_metadata(metadata, "support_level")
    try:
        return TimeoutSupportLevel(value)
    except ValueError as exc:
        valid = ", ".join(level.value for level in TimeoutSupportLevel)
        raise ValueError(f"timeout support_level must be one of: {valid}") from exc


def _string_metadata(metadata: Mapping[str, PlainData], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"timeout metadata {key!r} must be a non-empty string")
    return value


def _bool_metadata(metadata: Mapping[str, PlainData], key: str) -> bool:
    value = metadata.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"timeout metadata {key!r} must be a bool")
    return value


def _positive_float_metadata(metadata: Mapping[str, PlainData], key: str) -> float:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"timeout metadata {key!r} must be a positive number")
    number = float(value)
    if number <= 0:
        raise ValueError(f"timeout metadata {key!r} must be a positive number")
    return number


def _classification_details(failure: ExecutionFailure) -> dict[str, PlainData]:
    details: dict[str, object] = {
        "failure_type": failure.failure_type,
        "executor": failure.executor,
        "message": failure.message,
    }
    if failure.exception_type is not None:
        details["exception_type"] = failure.exception_type
    if failure.exit_code is not None:
        details["exit_code"] = failure.exit_code
    if failure.signal is not None:
        details["signal"] = failure.signal
    if failure.executor_metadata:
        details["executor_metadata"] = dict(failure.executor_metadata)
    failure_details = {
        key: value
        for key, value in failure.details.items()
        if key != "reliability_classification"
    }
    if failure_details:
        details["failure_details"] = failure_details
    normalized = ensure_plain_data(details, path="reliability_classification.details")
    if not isinstance(normalized, dict):
        raise TypeError("classification details must be plain mapping data")
    return cast(dict[str, PlainData], normalized)


__all__ = [
    "build_reliability_status_detail",
    "classify_execution_failure",
    "failure_with_reliability_classification",
    "record_timeout_outcome_from_metadata",
    "record_reliability_transaction",
    "record_stage_reliability_transition",
]
