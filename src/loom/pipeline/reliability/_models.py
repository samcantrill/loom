"""Import-light reliability contracts for policy, classification, records, and protocols."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.status import RunStatus, StageStatus, parse_run_status, parse_stage_status
from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp

RELIABILITY_POLICY_SCHEMA_VERSION = 1
RELIABILITY_RECORD_SCHEMA_VERSION = 1


class ReliabilityField(StrEnum):
    """Known top-level reliability policy field keys."""

    RETRY = "retry"
    TIMEOUT = "timeout"


class RetryPolicy:
    """Retry policy configuration for one runtime stage run attempt."""

    _FIELDS = frozenset({"enabled", "max_attempts"})

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_attempts: int = 1,
    ) -> None:
        self.enabled = _bool_value(enabled, path="RetryPolicy.enabled")
        self.max_attempts = _positive_int(max_attempts, path="RetryPolicy.max_attempts")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "enabled": self.enabled,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RetryPolicy":
        mapping = _object_mapping(data, path="RetryPolicy")
        _reject_unknown(mapping, allowed=cls._FIELDS, path="RetryPolicy")
        return cls(
            enabled=_bool_value(mapping.get("enabled", True), path="RetryPolicy.enabled"),
            max_attempts=_positive_int(
                mapping.get("max_attempts", 1),
                path="RetryPolicy.max_attempts",
            ),
        )

    def __repr__(self) -> str:  # pragma: no cover - deterministic repr path
        return f"RetryPolicy(enabled={self.enabled!r}, max_attempts={self.max_attempts!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RetryPolicy):
            return False
        return (
            self.enabled == other.enabled
            and self.max_attempts == other.max_attempts
        )

    def __hash__(self) -> int:
        return hash((self.enabled, self.max_attempts))


class TimeoutPolicy:
    """Wall-clock timeout policy configuration for one runtime stage attempt."""

    _FIELDS = frozenset({"enabled", "duration_seconds"})

    def __init__(
        self,
        *,
        enabled: bool = True,
        duration_seconds: float | int | None = None,
    ) -> None:
        enabled_value = _bool_value(enabled, path="TimeoutPolicy.enabled")
        if enabled_value and duration_seconds is None:
            raise RuntimeResourceError("TimeoutPolicy.enabled true requires duration_seconds")
        if duration_seconds is not None:
            duration = _positive_number(duration_seconds, path="TimeoutPolicy.duration_seconds")
        else:
            duration = None
        self.enabled = enabled_value
        self.duration_seconds = duration

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "enabled": self.enabled,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: object) -> "TimeoutPolicy":
        mapping = _object_mapping(data, path="TimeoutPolicy")
        _reject_unknown(mapping, allowed=cls._FIELDS, path="TimeoutPolicy")
        duration = mapping.get("duration_seconds")
        if "duration_seconds" not in mapping and mapping.get("enabled", True):
            raise RuntimeResourceError(
                "TimeoutPolicy.enabled true requires duration_seconds"
            )
        return cls(
            enabled=_bool_value(mapping.get("enabled", True), path="TimeoutPolicy.enabled"),
            duration_seconds=None
            if duration is None
            else cast(float | int, duration),
        )

    def __repr__(self) -> str:  # pragma: no cover - deterministic repr path
        return (
            "TimeoutPolicy(enabled={0!r}, duration_seconds={1!r})"
        ).format(self.enabled, self.duration_seconds)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimeoutPolicy):
            return False
        return (
            self.enabled == other.enabled
            and self.duration_seconds == other.duration_seconds
        )

    def __hash__(self) -> int:
        return hash((self.enabled, self.duration_seconds))


@dataclass(frozen=True, slots=True)
class ReliabilityPolicy:
    """Runtime reliability policy with nested retry and timeout policy blocks."""

    retry: RetryPolicy | None = None
    timeout: TimeoutPolicy | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "retry",
            None if self.retry is None else _coerce_retry_policy(self.retry, path="ReliabilityPolicy.retry"),
        )
        object.__setattr__(
            self,
            "timeout",
            None
            if self.timeout is None
            else _coerce_timeout_policy(self.timeout, path="ReliabilityPolicy.timeout"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            key: value.to_dict()
            for key, value in (
                ("retry", self.retry),
                ("timeout", self.timeout),
            )
            if value is not None
        }

    @classmethod
    def from_dict(cls, data: object) -> "ReliabilityPolicy":
        mapping = _object_mapping(data, path="ReliabilityPolicy")
        unknown = set(mapping) - {"retry", "timeout"}
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"ReliabilityPolicy contains unknown field(s): {fields}"
            )
        return cls(
            retry=_coerce_optional_retry(mapping.get("retry"), path="ReliabilityPolicy.retry"),
            timeout=_coerce_optional_timeout(
                mapping.get("timeout"),
                path="ReliabilityPolicy.timeout",
            ),
        )

    def merge_with(self, override: "ReliabilityPolicy | None") -> "ReliabilityPolicy":
        if override is None:
            return self
        return ReliabilityPolicy(
            retry=override.retry if override.retry is not None else self.retry,
            timeout=override.timeout if override.timeout is not None else self.timeout,
        )

    @staticmethod
    def defaults() -> "ReliabilityPolicy":
        return ReliabilityPolicy(
            retry=RetryPolicy(enabled=False, max_attempts=1),
            timeout=None,
        )


@dataclass(frozen=True, slots=True)
class ReliabilityStatusDetail:
    """Stable status snapshot used for reliability records."""

    run_uri: str
    run_status: RunStatus | str
    stage_id: str
    stage_status: StageStatus | str
    attempt: int
    created_at: str
    schema_version: int = RELIABILITY_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "run_status",
            parse_run_status(
                self.run_status.value if isinstance(self.run_status, RunStatus) else self.run_status,
            ),
        )
        object.__setattr__(
            self,
            "stage_status",
            parse_stage_status(
                self.stage_status.value
                if isinstance(self.stage_status, StageStatus)
                else self.stage_status,
            ),
        )
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RuntimeResourceError("ReliabilityStatusDetail.run_uri must be a non-empty string")
        if not isinstance(self.stage_id, str) or not self.stage_id:
            raise RuntimeResourceError("ReliabilityStatusDetail.stage_id must be a non-empty string")
        object.__setattr__(self, "attempt", _positive_int(self.attempt, path="ReliabilityStatusDetail.attempt"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, path="ReliabilityStatusDetail.created_at"))
        if (
            self.schema_version != RELIABILITY_RECORD_SCHEMA_VERSION
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise RuntimeResourceError(
                "ReliabilityStatusDetail.schema_version must be 1"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "run_status": cast(RunStatus, self.run_status).value,
            "stage_id": self.stage_id,
            "stage_status": cast(StageStatus, self.stage_status).value,
            "attempt": self.attempt,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ReliabilityStatusDetail":
        mapping = _object_mapping(data, path="ReliabilityStatusDetail")
        required = {"run_uri", "run_status", "stage_id", "stage_status", "attempt", "created_at"}
        missing = required - set(mapping)
        if missing:
            raise RuntimeResourceError(
                "ReliabilityStatusDetail missing required field(s): "
                + ", ".join(sorted(missing))
            )
        unknown = set(mapping) - required - {"schema_version"}
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"ReliabilityStatusDetail contains unknown field(s): {fields}"
            )
        version = mapping.get("schema_version", RELIABILITY_RECORD_SCHEMA_VERSION)
        if version != RELIABILITY_RECORD_SCHEMA_VERSION:
            raise RuntimeResourceError(
                "ReliabilityStatusDetail unsupported schema_version "
                f"{version!r}, expected {RELIABILITY_RECORD_SCHEMA_VERSION}"
            )
        return cls(
            run_uri=_non_empty_string(mapping["run_uri"], path="ReliabilityStatusDetail.run_uri"),
            run_status=_non_empty_string(mapping["run_status"], path="ReliabilityStatusDetail.run_status"),
            stage_id=_non_empty_string(mapping["stage_id"], path="ReliabilityStatusDetail.stage_id"),
            stage_status=_non_empty_string(
                mapping["stage_status"],
                path="ReliabilityStatusDetail.stage_status",
            ),
            attempt=_positive_int(mapping["attempt"], path="ReliabilityStatusDetail.attempt"),
            created_at=_timestamp(mapping["created_at"], path="ReliabilityStatusDetail.created_at"),
            schema_version=_positive_int(version, path="ReliabilityStatusDetail.schema_version"),
        )


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """Failure classification payload emitted for potential reliability handling."""

    reason_code: str
    status: ReliabilityStatusDetail
    retriable: bool
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_code",
            _non_empty_string(self.reason_code, path="FailureClassification.reason_code"),
        )
        object.__setattr__(
            self,
            "retriable",
            _bool_value(self.retriable, path="FailureClassification.retriable"),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain_mapping(self.details, path="FailureClassification.details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "reason_code": self.reason_code,
            "retriable": self.retriable,
            "details": cast(dict[str, PlainData], thaw_plain_data(self.details)),
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "FailureClassification":
        mapping = _object_mapping(data, path="FailureClassification")
        _require_fields(
            mapping,
            required={"reason_code", "retriable", "details", "status"},
            path="FailureClassification",
        )
        unknown = set(mapping) - {
            "reason_code",
            "retriable",
            "details",
            "status",
        }
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"FailureClassification contains unknown field(s): {fields}"
            )
        return cls(
            reason_code=_non_empty_string(mapping["reason_code"], path="FailureClassification.reason_code"),
            retriable=_bool_value(mapping["retriable"], path="FailureClassification.retriable"),
            details=_plain_mapping(mapping["details"], path="FailureClassification.details"),
            status=ReliabilityStatusDetail.from_dict(mapping["status"]),
        )


class StageAttemptTransactionState(StrEnum):
    """Named stage-attempt transaction transition states."""

    UNSPECIFIED = "unspecified"
    PREPARED = "prepared"
    RUNNING = "running"
    STAGED = "staged"
    COMMITTED = "committed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMMIT_FAILED = "commit_failed"


@dataclass(frozen=True, slots=True)
class StageAttemptTransaction:
    """Reference transaction for one stage attempt evaluation cycle."""

    transaction_id: str
    run_uri: str
    stage_id: str
    attempt: int
    status: ReliabilityStatusDetail
    state: StageAttemptTransactionState | str = StageAttemptTransactionState.UNSPECIFIED
    causal_parent_id: str | None = None
    schema_version: int = RELIABILITY_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transaction_id",
            _non_empty_string(self.transaction_id, path="StageAttemptTransaction.transaction_id"),
        )
        object.__setattr__(
            self,
            "run_uri",
            _non_empty_string(self.run_uri, path="StageAttemptTransaction.run_uri"),
        )
        object.__setattr__(
            self,
            "stage_id",
            _non_empty_string(self.stage_id, path="StageAttemptTransaction.stage_id"),
        )
        object.__setattr__(
            self,
            "attempt",
            _positive_int(self.attempt, path="StageAttemptTransaction.attempt"),
        )
        object.__setattr__(
            self,
            "state",
            _coerce_transaction_state(
                self.state,
                path="StageAttemptTransaction.state",
            ),
        )
        if self.causal_parent_id is not None:
            object.__setattr__(
                self,
                "causal_parent_id",
                _non_empty_string(
                    self.causal_parent_id,
                    path="StageAttemptTransaction.causal_parent_id",
                ),
            )
        if (
            self.schema_version != RELIABILITY_RECORD_SCHEMA_VERSION
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise RuntimeResourceError(
                "StageAttemptTransaction.schema_version must be 1"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "transaction_id": self.transaction_id,
            "run_uri": self.run_uri,
            "stage_id": self.stage_id,
            "attempt": self.attempt,
            "state": cast(StageAttemptTransactionState, self.state).value,
            "causal_parent_id": self.causal_parent_id,
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageAttemptTransaction":
        mapping = _object_mapping(data, path="StageAttemptTransaction")
        required = {"transaction_id", "run_uri", "stage_id", "attempt", "status"}
        _require_fields(mapping, required=required, path="StageAttemptTransaction")
        allowed = required | {"state", "causal_parent_id", "schema_version"}
        unknown = set(mapping) - allowed
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"StageAttemptTransaction contains unknown field(s): {fields}"
            )
        version = mapping.get("schema_version", RELIABILITY_RECORD_SCHEMA_VERSION)
        if version != RELIABILITY_RECORD_SCHEMA_VERSION:
            raise RuntimeResourceError(
                "StageAttemptTransaction unsupported schema_version "
                f"{version!r}, expected {RELIABILITY_RECORD_SCHEMA_VERSION}"
            )
        return cls(
            transaction_id=_non_empty_string(
                mapping["transaction_id"],
                path="StageAttemptTransaction.transaction_id",
            ),
            run_uri=_non_empty_string(mapping["run_uri"], path="StageAttemptTransaction.run_uri"),
            stage_id=_non_empty_string(mapping["stage_id"], path="StageAttemptTransaction.stage_id"),
            attempt=_positive_int(mapping["attempt"], path="StageAttemptTransaction.attempt"),
            state=_coerce_transaction_state(
                mapping.get("state", StageAttemptTransactionState.UNSPECIFIED.value),
                path="StageAttemptTransaction.state",
            ),
            causal_parent_id=(
                None
                if mapping.get("causal_parent_id") is None
                else _non_empty_string(
                    mapping["causal_parent_id"],
                    path="StageAttemptTransaction.causal_parent_id",
                )
            ),
            status=ReliabilityStatusDetail.from_dict(mapping["status"]),
            schema_version=_positive_int(version, path="StageAttemptTransaction.schema_version"),
        )


@dataclass(frozen=True, slots=True)
class RetryDecisionRecord:
    """Retry decision outcome emitted for one stage-attempt candidate."""

    decision_id: str
    transaction_id: str
    should_retry: bool
    next_attempt: int | None
    decision_reason: str
    policy_max_attempts: int
    attempt_count: int
    status: ReliabilityStatusDetail
    failure: FailureClassification
    schema_version: int = RELIABILITY_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _non_empty_string(self.decision_id, path="RetryDecisionRecord.decision_id"),
        )
        object.__setattr__(
            self,
            "transaction_id",
            _non_empty_string(self.transaction_id, path="RetryDecisionRecord.transaction_id"),
        )
        object.__setattr__(
            self,
            "should_retry",
            _bool_value(self.should_retry, path="RetryDecisionRecord.should_retry"),
        )
        object.__setattr__(
            self,
            "decision_reason",
            _non_empty_string(self.decision_reason, path="RetryDecisionRecord.decision_reason"),
        )
        object.__setattr__(
            self,
            "policy_max_attempts",
            _positive_int(self.policy_max_attempts, path="RetryDecisionRecord.policy_max_attempts"),
        )
        object.__setattr__(
            self,
            "attempt_count",
            _positive_int(self.attempt_count, path="RetryDecisionRecord.attempt_count"),
        )
        if self.next_attempt is not None:
            object.__setattr__(
                self,
                "next_attempt",
                _positive_int(self.next_attempt, path="RetryDecisionRecord.next_attempt"),
            )
        if (
            self.schema_version != RELIABILITY_RECORD_SCHEMA_VERSION
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise RuntimeResourceError("RetryDecisionRecord.schema_version must be 1")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "transaction_id": self.transaction_id,
            "should_retry": self.should_retry,
            "next_attempt": self.next_attempt,
            "decision_reason": self.decision_reason,
            "policy_max_attempts": self.policy_max_attempts,
            "attempt_count": self.attempt_count,
            "status": self.status.to_dict(),
            "failure": self.failure.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RetryDecisionRecord":
        mapping = _object_mapping(data, path="RetryDecisionRecord")
        required = {
            "decision_id",
            "transaction_id",
            "should_retry",
            "next_attempt",
            "decision_reason",
            "policy_max_attempts",
            "attempt_count",
            "status",
            "failure",
        }
        _require_fields(mapping, required=required, path="RetryDecisionRecord")
        unknown = set(mapping) - required - {"schema_version"}
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"RetryDecisionRecord contains unknown field(s): {fields}"
            )
        version = mapping.get("schema_version", RELIABILITY_RECORD_SCHEMA_VERSION)
        if version != RELIABILITY_RECORD_SCHEMA_VERSION:
            raise RuntimeResourceError(
                "RetryDecisionRecord unsupported schema_version "
                f"{version!r}, expected {RELIABILITY_RECORD_SCHEMA_VERSION}"
            )
        return cls(
            decision_id=_non_empty_string(
                mapping["decision_id"],
                path="RetryDecisionRecord.decision_id",
            ),
            transaction_id=_non_empty_string(
                mapping["transaction_id"],
                path="RetryDecisionRecord.transaction_id",
            ),
            should_retry=_bool_value(mapping["should_retry"], path="RetryDecisionRecord.should_retry"),
            next_attempt=(
                None
                if mapping.get("next_attempt") is None
                else _positive_int(
                    mapping["next_attempt"], path="RetryDecisionRecord.next_attempt"
                )
            ),
            decision_reason=_non_empty_string(
                mapping["decision_reason"],
                path="RetryDecisionRecord.decision_reason",
            ),
            policy_max_attempts=_positive_int(
                mapping["policy_max_attempts"],
                path="RetryDecisionRecord.policy_max_attempts",
            ),
            attempt_count=_positive_int(
                mapping["attempt_count"], path="RetryDecisionRecord.attempt_count"
            ),
            status=ReliabilityStatusDetail.from_dict(mapping["status"]),
            failure=FailureClassification.from_dict(mapping["failure"]),
            schema_version=_positive_int(version, path="RetryDecisionRecord.schema_version"),
        )


@dataclass(frozen=True, slots=True)
class TimeoutOutcomeRecord:
    """Timeout outcome record linked to a stage attempt transaction."""

    outcome_id: str
    transaction_id: str
    timed_out: bool
    duration_seconds: float
    reason_code: str
    status: ReliabilityStatusDetail
    causal_decision_id: str | None = None
    schema_version: int = RELIABILITY_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome_id",
            _non_empty_string(self.outcome_id, path="TimeoutOutcomeRecord.outcome_id"),
        )
        object.__setattr__(
            self,
            "transaction_id",
            _non_empty_string(self.transaction_id, path="TimeoutOutcomeRecord.transaction_id"),
        )
        object.__setattr__(
            self,
            "timed_out",
            _bool_value(self.timed_out, path="TimeoutOutcomeRecord.timed_out"),
        )
        object.__setattr__(
            self,
            "duration_seconds",
            _positive_number(self.duration_seconds, path="TimeoutOutcomeRecord.duration_seconds"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _non_empty_string(self.reason_code, path="TimeoutOutcomeRecord.reason_code"),
        )
        if self.causal_decision_id is not None:
            object.__setattr__(
                self,
                "causal_decision_id",
                _non_empty_string(
                    self.causal_decision_id,
                    path="TimeoutOutcomeRecord.causal_decision_id",
                ),
            )
        if (
            self.schema_version != RELIABILITY_RECORD_SCHEMA_VERSION
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise RuntimeResourceError("TimeoutOutcomeRecord.schema_version must be 1")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "outcome_id": self.outcome_id,
            "transaction_id": self.transaction_id,
            "timed_out": self.timed_out,
            "duration_seconds": self.duration_seconds,
            "reason_code": self.reason_code,
            "causal_decision_id": self.causal_decision_id,
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TimeoutOutcomeRecord":
        mapping = _object_mapping(data, path="TimeoutOutcomeRecord")
        required = {
            "outcome_id",
            "transaction_id",
            "timed_out",
            "duration_seconds",
            "reason_code",
            "status",
        }
        _require_fields(mapping, required=required, path="TimeoutOutcomeRecord")
        unknown = set(mapping) - required - {"causal_decision_id", "schema_version"}
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(
                f"TimeoutOutcomeRecord contains unknown field(s): {fields}"
            )
        version = mapping.get("schema_version", RELIABILITY_RECORD_SCHEMA_VERSION)
        if version != RELIABILITY_RECORD_SCHEMA_VERSION:
            raise RuntimeResourceError(
                "TimeoutOutcomeRecord unsupported schema_version "
                f"{version!r}, expected {RELIABILITY_RECORD_SCHEMA_VERSION}"
            )
        return cls(
            outcome_id=_non_empty_string(
                mapping["outcome_id"], path="TimeoutOutcomeRecord.outcome_id"
            ),
            transaction_id=_non_empty_string(
                mapping["transaction_id"],
                path="TimeoutOutcomeRecord.transaction_id",
            ),
            timed_out=_bool_value(mapping["timed_out"], path="TimeoutOutcomeRecord.timed_out"),
            duration_seconds=_positive_number(
                mapping["duration_seconds"], path="TimeoutOutcomeRecord.duration_seconds"
            ),
            reason_code=_non_empty_string(
                mapping["reason_code"],
                path="TimeoutOutcomeRecord.reason_code",
            ),
            status=ReliabilityStatusDetail.from_dict(mapping["status"]),
            causal_decision_id=(
                None
                if mapping.get("causal_decision_id") is None
                else _non_empty_string(
                    mapping["causal_decision_id"],
                    path="TimeoutOutcomeRecord.causal_decision_id",
                )
            ),
            schema_version=_positive_int(version, path="TimeoutOutcomeRecord.schema_version"),
        )


class FailureClassifier(Protocol):
    """Classifies raw executor failures into reliability domain decisions."""

    def classify(self, failure: object, *, status: ReliabilityStatusDetail) -> FailureClassification:
        ...


class RetryEvaluator(Protocol):
    """Evaluates retry policy against classified failure facts."""

    def evaluate(
        self,
        *,
        policy: RetryPolicy,
        failure: FailureClassification,
        status: ReliabilityStatusDetail,
    ) -> RetryDecisionRecord:
        ...


class TimeoutAdapter(Protocol):
    """Timeout adapter contract for capability-owned timeout enforcement."""

    def apply_timeout(self, policy: TimeoutPolicy, *, context: Mapping[str, PlainData]) -> None:
        ...


class ReliabilityRecordStore(Protocol):
    """Persistence interface used by reliability record consumers."""

    def write_stage_attempt_transaction(
        self,
        transaction: StageAttemptTransaction,
    ) -> None:
        ...

    def write_retry_decision(
        self,
        decision: RetryDecisionRecord,
    ) -> None:
        ...

    def write_timeout_outcome(
        self,
        outcome: TimeoutOutcomeRecord,
    ) -> None:
        ...


class ReliabilityTransactionStore(Protocol):
    """Low-level read/write contract for reliability transaction topology."""

    def read_transaction_chain(self, transaction_id: str) -> Sequence[StageAttemptTransaction]:
        ...

    def upsert_transaction(
        self,
        transaction: StageAttemptTransaction,
    ) -> None:
        ...


class RunnerReliabilityController(Protocol):
    """Runtime handoff contract for runner-owned reliability controls."""

    def start_transaction(self, status: ReliabilityStatusDetail) -> StageAttemptTransaction:
        ...

    def commit_retry_decision(
        self,
        *,
        policy: RetryPolicy,
        decision: RetryDecisionRecord,
    ) -> RetryDecisionRecord:
        ...

    def commit_timeout(self, *, outcome: TimeoutOutcomeRecord) -> TimeoutOutcomeRecord:
        ...


def merge_reliability_options(
    base: ReliabilityPolicy | None,
    override: ReliabilityPolicy | None,
) -> ReliabilityPolicy:
    """Merge run-level reliability with stage-level override semantics."""

    if base is None:
        base = ReliabilityPolicy.defaults()
    return base.merge_with(override)


def _coerce_retry_policy(
    policy: RetryPolicy | Mapping[str, object],
    *,
    path: str,
) -> RetryPolicy:
    if isinstance(policy, RetryPolicy):
        return policy
    return RetryPolicy.from_dict(policy)


def _coerce_optional_retry(
    value: object,
    *,
    path: str,
) -> RetryPolicy | None:
    if value is None:
        return None
    if isinstance(value, RetryPolicy):
        return value
    return RetryPolicy.from_dict(value)


def _coerce_timeout_policy(
    policy: TimeoutPolicy | Mapping[str, object],
    *,
    path: str,
) -> TimeoutPolicy:
    if isinstance(policy, TimeoutPolicy):
        return policy
    return TimeoutPolicy.from_dict(policy)


def _coerce_optional_timeout(
    value: object,
    *,
    path: str,
) -> TimeoutPolicy | None:
    if value is None:
        return None
    if isinstance(value, TimeoutPolicy):
        return value
    return TimeoutPolicy.from_dict(value)


def _coerce_transaction_state(
    value: object,
    *,
    path: str,
) -> StageAttemptTransactionState:
    if isinstance(value, StageAttemptTransactionState):
        return value
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    try:
        return StageAttemptTransactionState(value)
    except ValueError as exc:
        valid = ", ".join(state.value for state in StageAttemptTransactionState)
        raise RuntimeResourceError(f"{path} must be one of: {valid}") from exc


def _object_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _require_fields(
    mapping: Mapping[str, object],
    *,
    required: set[str],
    path: str,
) -> None:
    missing = required - set(mapping)
    if missing:
        raise RuntimeResourceError(
            f"{path} missing required field(s): {', '.join(sorted(missing))}"
        )


def _timestamp(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"{path} must be a valid timestamp: {exc}") from exc
    return value


def _non_empty_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return value


def _bool_value(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeResourceError(f"{path} must be a bool")
    return value


def _positive_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError(f"{path} must be a positive integer")
    if value <= 0:
        raise RuntimeResourceError(f"{path} must be a positive integer")
    return value


def _positive_number(value: object, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeResourceError(f"{path} must be a finite positive number")
    number = float(value)
    if number <= 0 or number in (float("inf"), float("-inf")) or number != number:
        raise RuntimeResourceError(f"{path} must be a finite positive number")
    return number


def _sort_plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: _sort_plain_value(value[key]) for key in sorted(value)}


def _sort_plain_value(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _sort_plain_mapping(value)
    if isinstance(value, list):
        return [_sort_plain_value(item) for item in value]
    return value


def _reject_unknown(
    mapping: Mapping[str, object],
    *,
    allowed: set[str] | frozenset[str],
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"{path} contains unknown field(s): {fields}")


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(f"{path} must be plain-data-compatible: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _freeze_plain_mapping(value: Mapping[str, PlainData], path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(f"{path} must be plain-data-compatible: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], freeze_plain_data(normalized, path=path))


__all__ = [
    "RELIABILITY_POLICY_SCHEMA_VERSION",
    "RELIABILITY_RECORD_SCHEMA_VERSION",
    "FailureClassification",
    "FailureClassifier",
    "ReliabilityField",
    "ReliabilityPolicy",
    "ReliabilityRecordStore",
    "ReliabilityStatusDetail",
    "RetryDecisionRecord",
    "RetryEvaluator",
    "RetryPolicy",
    "RunnerReliabilityController",
    "StageAttemptTransaction",
    "StageAttemptTransactionState",
    "TimeoutAdapter",
    "TimeoutOutcomeRecord",
    "TimeoutPolicy",
    "ReliabilityTransactionStore",
    "merge_reliability_options",
]
