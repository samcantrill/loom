"""Read-only sweep status aggregation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from loom.pipeline.early_stopping import EARLY_STOP_REASON_CODE
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .errors import SweepProtocolError

if TYPE_CHECKING:
    from .runner import SweepPlan
    from .trials import SweepTrialRecord


class SweepTrialOutcome(StrEnum):
    """Presented outcome for one sweep trial."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EARLY_STOPPED = "early_stopped"
    UNKNOWN = "unknown"


class SweepAggregateStatus(StrEnum):
    """Aggregate read-only sweep status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SweepTrialStatus:
    """Read model for one planned trial's aggregate status."""

    sweep_id: str
    trial_id: str
    trial_index: int
    outcome: SweepTrialOutcome
    run_uri: str | None = None
    run_status: str | None = None
    queue_item_id: str | None = None
    admission_state: str | None = None
    coordination_state: str | None = None
    early_stopped: bool = False
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _text(self.trial_id, "trial_id"))
        if not isinstance(self.trial_index, int) or isinstance(self.trial_index, bool):
            raise SweepProtocolError("trial_index must be an integer")
        object.__setattr__(self, "outcome", SweepTrialOutcome(self.outcome))
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        object.__setattr__(
            self, "run_status", _optional_text(self.run_status, "run_status")
        )
        object.__setattr__(
            self,
            "queue_item_id",
            _optional_text(self.queue_item_id, "queue_item_id"),
        )
        object.__setattr__(
            self,
            "admission_state",
            _optional_text(self.admission_state, "admission_state"),
        )
        object.__setattr__(
            self,
            "coordination_state",
            _optional_text(self.coordination_state, "coordination_state"),
        )
        if not isinstance(self.early_stopped, bool):
            raise SweepProtocolError("early_stopped must be a bool")
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "outcome": self.outcome.value,
            "run_uri": self.run_uri,
            "run_status": self.run_status,
            "queue_item_id": self.queue_item_id,
            "admission_state": self.admission_state,
            "coordination_state": self.coordination_state,
            "early_stopped": self.early_stopped,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }


@dataclass(frozen=True, slots=True)
class SweepStatusSummary:
    """Aggregate status read model for a finite sweep plan."""

    sweep_id: str
    status: SweepAggregateStatus
    trials: Sequence[SweepTrialStatus]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "status", SweepAggregateStatus(self.status))
        object.__setattr__(self, "trials", _trial_statuses(self.trials))

    @property
    def trial_count(self) -> int:
        return len(self.trials)

    @property
    def counts(self) -> dict[str, int]:
        counts = {outcome.value: 0 for outcome in SweepTrialOutcome}
        for trial in self.trials:
            counts[trial.outcome.value] += 1
        return counts

    @property
    def succeeded_count(self) -> int:
        return self.counts[SweepTrialOutcome.SUCCEEDED.value]

    @property
    def failed_count(self) -> int:
        return self.counts[SweepTrialOutcome.FAILED.value]

    @property
    def early_stopped_count(self) -> int:
        return self.counts[SweepTrialOutcome.EARLY_STOPPED.value]

    def to_dict(self) -> dict[str, PlainData]:
        counts: dict[str, PlainData] = dict(self.counts)
        return {
            "sweep_id": self.sweep_id,
            "status": self.status.value,
            "trial_count": self.trial_count,
            "counts": counts,
            "trials": [trial.to_dict() for trial in self.trials],
        }


def build_sweep_status(
    plan: "SweepPlan",
    *,
    run_statuses: Mapping[str, object] | None = None,
    run_status_reader: Callable[[str], object | None] | None = None,
    coordination_trials: Sequence[object] = (),
) -> SweepStatusSummary:
    """Build a read-only status summary from supplied state snapshots."""

    if run_statuses is not None and run_status_reader is not None:
        raise SweepProtocolError("provide run_statuses or run_status_reader, not both")
    coordination_by_trial_id = {
        trial_id: trial
        for trial in coordination_trials
        if (trial_id := _optional_attr_text(trial, "trial_id")) is not None
    }
    trial_statuses: list[SweepTrialStatus] = []
    for trial in plan.trials:
        run_record = _run_record_for_trial(
            trial,
            run_statuses=run_statuses,
            run_status_reader=run_status_reader,
        )
        native = cast(
            Mapping[str, Any], plan.sweep_manifest.metadata.get("native_runs", {})
        ).get(trial.trial_id)
        coordination = coordination_by_trial_id.get(trial.trial_id)
        trial_statuses.append(
            _trial_status(
                trial,
                run_record=run_record,
                native=native,
                coordination=coordination,
            )
        )
    return SweepStatusSummary(
        sweep_id=plan.sweep_id,
        status=_aggregate_status(trial_statuses),
        trials=tuple(trial_statuses),
    )


def _trial_status(
    trial: "SweepTrialRecord",
    *,
    run_record: object | None,
    native: Mapping[str, Any] | None,
    coordination: object | None,
) -> SweepTrialStatus:
    run_status = _status_attr_value(run_record)
    observation = {} if native is None else native.get("observation", {})
    admission = observation.get("admission") or {}
    operation = observation.get("operation") or {}
    admission_state = admission.get("state")
    if native is not None:
        # Native references outrank stale local projections during an explicit retry.
        run_status = (
            admission_state
            if admission_state in {"SUCCEEDED", "FAILED", "CANCELLED"}
            else None
        )

    coordination_state = _status_attr_value(getattr(coordination, "state", None))
    inspection = observation.get("inspection") or {}
    early_stopped = run_status == "CANCELLED" and (
        _early_stop_reason(run_record)
        or any(
            stage.get("code") == EARLY_STOP_REASON_CODE
            for stage in inspection.get("stages", ())
        )
    )
    outcome = _outcome(
        run_status=run_status,
        admission_state=admission_state,
        coordination_state=coordination_state,
        early_stopped=early_stopped,
    )
    if native is not None and not admission:
        state = operation.get("state")
        outcome = (
            SweepTrialOutcome.FAILED
            if state in {"failed", "conflict"} or native.get("dispatch_failed")
            else SweepTrialOutcome.CANCELLED
            if state == "cancelled"
            else SweepTrialOutcome.UNKNOWN
            if native.get("error")
            else SweepTrialOutcome.QUEUED
        )
    return SweepTrialStatus(
        sweep_id=trial.sweep_id,
        trial_id=trial.trial_id,
        trial_index=trial.trial_index,
        run_uri=trial.run_uri,
        outcome=outcome,
        run_status=run_status,
        queue_item_id=admission.get("queue_item_id"),
        admission_state=admission_state,
        coordination_state=coordination_state,
        early_stopped=early_stopped,
        metadata={
            "operation_id": None
            if native is None
            else native["request"]["preparation"]["operation_id"],
            "admission_id": admission.get("admission_id"),
            "dispatch_error": None if native is None else native.get("error"),
            "provider_trial_id": trial.provider_trial_id,
            "proposal_overrides": dict(trial.proposal_overrides),
        },
    )


def _outcome(
    *,
    run_status: str | None,
    admission_state: str | None,
    coordination_state: str | None,
    early_stopped: bool,
) -> SweepTrialOutcome:
    if early_stopped:
        return SweepTrialOutcome.EARLY_STOPPED
    if run_status is not None:
        return _outcome_from_run_status(run_status)
    if admission_state is not None:
        return _outcome_from_admission_state(admission_state)
    if coordination_state is not None:
        return _outcome_from_coordination_state(coordination_state)
    return SweepTrialOutcome.PENDING


def _outcome_from_run_status(status: str) -> SweepTrialOutcome:
    mapping = {
        "CREATED": SweepTrialOutcome.PENDING,
        "PLANNED": SweepTrialOutcome.PENDING,
        "SUBMITTED": SweepTrialOutcome.RUNNING,
        "RUNNING": SweepTrialOutcome.RUNNING,
        "SUCCEEDED": SweepTrialOutcome.SUCCEEDED,
        "FAILED": SweepTrialOutcome.FAILED,
        "CANCELLED": SweepTrialOutcome.CANCELLED,
        "INTERRUPTED": SweepTrialOutcome.CANCELLED,
    }
    return mapping.get(status, SweepTrialOutcome.UNKNOWN)


def _outcome_from_admission_state(status: str) -> SweepTrialOutcome:
    mapping = {
        "QUEUED": SweepTrialOutcome.QUEUED,
        "PENDING_AUTHORITY": SweepTrialOutcome.QUEUED,
        "ACTIVE": SweepTrialOutcome.RUNNING,
        "WAITING": SweepTrialOutcome.QUEUED,
        "BLOCKED": SweepTrialOutcome.UNKNOWN,
        "RUNNING": SweepTrialOutcome.RUNNING,
        "CANCELLING": SweepTrialOutcome.RUNNING,
        "CANCELLATION_REQUESTED": SweepTrialOutcome.RUNNING,
        "DISPATCHED": SweepTrialOutcome.RUNNING,
        "SUCCEEDED": SweepTrialOutcome.SUCCEEDED,
        "FAILED": SweepTrialOutcome.FAILED,
        "CANCELLED": SweepTrialOutcome.CANCELLED,
        "UNKNOWN": SweepTrialOutcome.UNKNOWN,
    }
    return mapping.get(status, SweepTrialOutcome.UNKNOWN)


def _outcome_from_coordination_state(state: str) -> SweepTrialOutcome:
    mapping = {
        "pending": SweepTrialOutcome.PENDING,
        "claimed": SweepTrialOutcome.QUEUED,
        "running": SweepTrialOutcome.RUNNING,
        "completed": SweepTrialOutcome.SUCCEEDED,
        "failed": SweepTrialOutcome.FAILED,
        "cancelled": SweepTrialOutcome.CANCELLED,
    }
    return mapping.get(state, SweepTrialOutcome.UNKNOWN)


def _aggregate_status(trials: Sequence[SweepTrialStatus]) -> SweepAggregateStatus:
    if not trials:
        return SweepAggregateStatus.PENDING
    outcomes = {trial.outcome for trial in trials}
    if SweepTrialOutcome.FAILED in outcomes:
        return SweepAggregateStatus.FAILED
    terminal_success = {SweepTrialOutcome.SUCCEEDED, SweepTrialOutcome.EARLY_STOPPED}
    if outcomes <= terminal_success:
        return SweepAggregateStatus.SUCCEEDED
    if outcomes <= terminal_success | {SweepTrialOutcome.CANCELLED}:
        return SweepAggregateStatus.CANCELLED
    if outcomes == {SweepTrialOutcome.PENDING}:
        return SweepAggregateStatus.PENDING
    return SweepAggregateStatus.RUNNING


def _run_record_for_trial(
    trial: "SweepTrialRecord",
    *,
    run_statuses: Mapping[str, object] | None,
    run_status_reader: Callable[[str], object | None] | None,
) -> object | None:
    if trial.run_uri is None:
        return None
    if run_status_reader is not None:
        return run_status_reader(trial.run_uri)
    if run_statuses is None:
        return None
    return run_statuses.get(trial.run_uri) or run_statuses.get(trial.trial_id)


def _early_stop_reason(run_record: object | None) -> bool:
    metadata = getattr(run_record, "metadata", None)
    if not isinstance(metadata, Mapping):
        return False
    reason = metadata.get("reason")
    if isinstance(reason, Mapping) and reason.get("code") == EARLY_STOP_REASON_CODE:
        return True
    return metadata.get("reason_code") == EARLY_STOP_REASON_CODE


def _trial_statuses(values: Sequence[SweepTrialStatus]) -> tuple[SweepTrialStatus, ...]:
    normalized: list[SweepTrialStatus] = []
    for value in values:
        if not isinstance(value, SweepTrialStatus):
            raise SweepProtocolError("trials must contain SweepTrialStatus values")
        normalized.append(value)
    return tuple(normalized)


def _status_attr_value(value: object | None) -> str | None:
    if value is None:
        return None
    raw: Any = getattr(value, "status", value)
    enum_value = getattr(raw, "value", raw)
    return enum_value if isinstance(enum_value, str) else None


def _optional_attr_text(value: object | None, attribute: str) -> str | None:
    if value is None:
        return None
    raw = getattr(value, attribute, None)
    return raw if isinstance(raw, str) and raw else None


def _metadata_text(value: object, key: str) -> str | None:
    metadata = getattr(value, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(key)
    return raw if isinstance(raw, str) and raw else None


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _plain_mapping(
    value: Mapping[str, PlainData], field: str
) -> Mapping[str, PlainData]:
    normalized = freeze_plain_data(value, path=field)
    if not isinstance(normalized, Mapping):
        raise SweepProtocolError(f"{field} must be a plain-data mapping")
    return normalized


__all__ = [
    "SweepAggregateStatus",
    "SweepStatusSummary",
    "SweepTrialOutcome",
    "SweepTrialStatus",
    "build_sweep_status",
]
