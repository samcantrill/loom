"""Shared reliability fact validation and identity helpers for stores."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.serialization import PlainData, stable_json_dumps

from .authority import AuthorityStoreError
from .read_models import ReliabilityPolicyFact


def reliability_policy_fact_key(fact: ReliabilityPolicyFact) -> str:
    return _digest(
        {
            "run_uri": fact.run_uri,
            "scope": fact.scope.value,
            "stage_name": fact.stage_name,
            "attempt": fact.attempt,
            "recorded_at": fact.recorded_at,
        }
    )


def reliability_status_detail_key(detail: ReliabilityStatusDetail) -> str:
    return _digest(
        {
            "run_uri": detail.run_uri,
            "stage_name": detail.stage_id,
            "attempt": detail.attempt,
            "run_status": str(detail.run_status),
            "stage_status": str(detail.stage_status),
            "created_at": detail.created_at,
        }
    )


def reliability_payload_matches(
    existing: Mapping[str, PlainData],
    incoming: Mapping[str, PlainData],
) -> bool:
    return stable_json_dumps(existing) == stable_json_dumps(incoming)


def validate_policy_fact_run(fact: ReliabilityPolicyFact, run_uri: str) -> None:
    if fact.run_uri != run_uri:
        raise AuthorityStoreError(
            f"reliability policy fact run_uri {fact.run_uri!r} does not match {run_uri!r}"
        )


def validate_status_detail_run(
    detail: ReliabilityStatusDetail, run_uri: str
) -> None:
    if detail.run_uri != run_uri:
        raise AuthorityStoreError(
            f"reliability status detail run_uri {detail.run_uri!r} does not match {run_uri!r}"
        )


def validate_transaction_run(
    transaction: StageAttemptTransaction, run_uri: str
) -> None:
    if transaction.run_uri != run_uri:
        raise AuthorityStoreError(
            f"reliability transaction run_uri {transaction.run_uri!r} does not match {run_uri!r}"
        )
    validate_status_detail_run(transaction.status, run_uri)
    if transaction.status.stage_id != transaction.stage_id:
        raise AuthorityStoreError("reliability transaction stage_id mismatch")
    if transaction.status.attempt != transaction.attempt:
        raise AuthorityStoreError("reliability transaction attempt mismatch")


def validate_retry_decision_run(decision: RetryDecisionRecord, run_uri: str) -> None:
    validate_status_detail_run(decision.status, run_uri)
    validate_status_detail_run(decision.failure.status, run_uri)
    if decision.failure.status != decision.status:
        raise AuthorityStoreError("retry decision failure status mismatch")


def validate_timeout_outcome_run(outcome: TimeoutOutcomeRecord, run_uri: str) -> None:
    validate_status_detail_run(outcome.status, run_uri)


def reliability_record_stage_name(
    record: ReliabilityStatusDetail
    | StageAttemptTransaction
    | RetryDecisionRecord
    | TimeoutOutcomeRecord,
) -> str:
    if isinstance(record, ReliabilityStatusDetail):
        return record.stage_id
    if isinstance(record, StageAttemptTransaction):
        return record.stage_id
    if isinstance(record, RetryDecisionRecord):
        return record.status.stage_id
    return record.status.stage_id


def _digest(value: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(stable_json_dumps(value).encode("utf-8")).hexdigest()


__all__ = [
    "reliability_policy_fact_key",
    "reliability_status_detail_key",
    "reliability_payload_matches",
    "reliability_record_stage_name",
    "validate_policy_fact_run",
    "validate_status_detail_run",
    "validate_transaction_run",
    "validate_retry_decision_run",
    "validate_timeout_outcome_run",
]
