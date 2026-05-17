"""Backend-neutral per-run authority contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.event_sinks import EventObserverLinkRecord, EventSinkFailureRecord
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData

from .capabilities import BackendCapabilitySet
from .config import AuthorityConfig
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    LeaseRecord,
    LifecycleReason,
    OutputCommitRecord,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageAttempt,
    StageLifecycleSnapshot,
)
from .schema_policy import AuthoritySchemaCheck


class AuthorityStoreError(ValueError):
    """Raised when authoritative per-run store operations are invalid."""


@dataclass(frozen=True, slots=True)
class StatusTransition:
    run_uri: str
    status: RunStatus | StageStatus
    revision: BackendRevision
    previous_status: RunStatus | StageStatus | None = None
    stage_name: str | None = None
    reason: LifecycleReason | None = None

    def __post_init__(self) -> None:
        _non_empty(self.run_uri, "run_uri")
        if not isinstance(self.status, RunStatus | StageStatus):
            raise AuthorityStoreError("status must be a RunStatus or StageStatus")
        if self.previous_status is not None and not isinstance(
            self.previous_status, RunStatus | StageStatus
        ):
            raise AuthorityStoreError(
                "previous_status must be a RunStatus, StageStatus, or None"
            )
        if self.stage_name is not None:
            _non_empty(self.stage_name, "stage_name")
        if self.stage_name is None and isinstance(self.status, StageStatus):
            raise AuthorityStoreError("stage status transitions require stage_name")
        if self.stage_name is not None and isinstance(self.status, RunStatus):
            raise AuthorityStoreError(
                "run status transitions must not include stage_name"
            )
        if not isinstance(self.revision, BackendRevision):
            raise AuthorityStoreError("revision must be a BackendRevision")
        if self.reason is not None and not isinstance(self.reason, LifecycleReason):
            raise AuthorityStoreError("reason must be a LifecycleReason or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "status": self.status.value,
            "previous_status": None
            if self.previous_status is None
            else self.previous_status.value,
            "revision": self.revision.to_dict(),
            "reason": None if self.reason is None else self.reason.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StatusTransition":
        mapping = _mapping(data, "StatusTransition")
        _reject_unknown(
            mapping,
            {
                "run_uri",
                "stage_name",
                "status",
                "previous_status",
                "revision",
                "reason",
            },
            "StatusTransition",
        )
        stage_name = _optional_string(mapping.get("stage_name"), "stage_name")
        return cls(
            run_uri=_non_empty(_required(mapping, "run_uri"), "run_uri"),
            stage_name=stage_name,
            status=_coerce_status(_required(mapping, "status"), stage_name),
            previous_status=_coerce_optional_status(
                mapping.get("previous_status"), stage_name
            ),
            revision=BackendRevision.from_dict(_required(mapping, "revision")),
            reason=_optional_reason(mapping.get("reason")),
        )


@dataclass(frozen=True, slots=True)
class AttemptAllocation:
    attempt: StageAttempt
    lease: LeaseRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, StageAttempt):
            raise AuthorityStoreError("attempt must be a StageAttempt")
        if self.lease is not None and not isinstance(self.lease, LeaseRecord):
            raise AuthorityStoreError("lease must be a LeaseRecord or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "attempt": self.attempt.to_dict(),
            "lease": None if self.lease is None else self.lease.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AttemptAllocation":
        mapping = _mapping(data, "AttemptAllocation")
        _reject_unknown(mapping, {"attempt", "lease"}, "AttemptAllocation")
        lease = mapping.get("lease")
        return cls(
            attempt=StageAttempt.from_dict(_required(mapping, "attempt")),
            lease=None if lease is None else LeaseRecord.from_dict(lease),
        )


@dataclass(frozen=True, slots=True)
class OutputCommit:
    commit: OutputCommitRecord
    artifact_facts: tuple[ArtifactFactRecord, ...] = ()
    cleanup_candidates: tuple[CleanupCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.commit, OutputCommitRecord):
            raise AuthorityStoreError("commit must be an OutputCommitRecord")
        object.__setattr__(
            self,
            "artifact_facts",
            _tuple_of(self.artifact_facts, ArtifactFactRecord, "artifact_facts"),
        )
        object.__setattr__(
            self,
            "cleanup_candidates",
            _tuple_of(
                self.cleanup_candidates,
                CleanupCandidate,
                "cleanup_candidates",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "commit": self.commit.to_dict(),
            "artifact_facts": [fact.to_dict() for fact in self.artifact_facts],
            "cleanup_candidates": [
                candidate.to_dict() for candidate in self.cleanup_candidates
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> "OutputCommit":
        mapping = _mapping(data, "OutputCommit")
        _reject_unknown(
            mapping,
            {"commit", "artifact_facts", "cleanup_candidates"},
            "OutputCommit",
        )
        return cls(
            commit=OutputCommitRecord.from_dict(_required(mapping, "commit")),
            artifact_facts=tuple(
                ArtifactFactRecord.from_dict(fact)
                for fact in _sequence(
                    mapping.get("artifact_facts", ()), "artifact_facts"
                )
            ),
            cleanup_candidates=tuple(
                CleanupCandidate.from_dict(candidate)
                for candidate in _sequence(
                    mapping.get("cleanup_candidates", ()), "cleanup_candidates"
                )
            ),
        )


@runtime_checkable
class PerRunAuthorityStore(Protocol):
    """Authoritative active-state contract for one run scope."""

    def capabilities(self) -> BackendCapabilitySet: ...

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck: ...

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision: ...

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation: ...

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord: ...

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord: ...

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord: ...

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision: ...

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None: ...

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]: ...

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision: ...

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]: ...

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision: ...

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]: ...

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision: ...

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision: ...

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]: ...

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision: ...

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]: ...

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit: ...

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord: ...

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> BackendRevision: ...

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]: ...

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> BackendRevision: ...

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]: ...

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]: ...

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]: ...


@runtime_checkable
class StageStore(Protocol):
    """Scoped authority surface for one stage inside a run."""

    @property
    def run_uri(self) -> str: ...

    @property
    def stage_name(self) -> str: ...

    def capabilities(self) -> BackendCapabilitySet: ...

    def transition(
        self,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def allocate_attempt(
        self,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation: ...

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord: ...

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord: ...

    def write_submitted_operation(
        self, record: SubmittedOperationRecord
    ) -> BackendRevision: ...

    def read_submitted_operation(
        self, submission_id: str
    ) -> SubmittedOperationRecord | None: ...

    def list_submitted_operations(self) -> tuple[SubmittedOperationRecord, ...]: ...

    def write_reliability_policy_fact(
        self, fact: ReliabilityPolicyFact
    ) -> BackendRevision: ...

    def list_reliability_policy_facts(self) -> tuple[ReliabilityPolicyFact, ...]: ...

    def write_reliability_status_detail(
        self, detail: ReliabilityStatusDetail
    ) -> BackendRevision: ...

    def list_reliability_status_details(
        self,
    ) -> tuple[ReliabilityStatusDetail, ...]: ...

    def write_stage_attempt_transaction(
        self, transaction: StageAttemptTransaction
    ) -> BackendRevision: ...

    def read_transaction_chain(
        self, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def list_stage_attempt_transactions(
        self,
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def write_retry_decision(
        self, decision: RetryDecisionRecord
    ) -> BackendRevision: ...

    def list_retry_decisions(self) -> tuple[RetryDecisionRecord, ...]: ...

    def write_timeout_outcome(
        self, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision: ...

    def list_timeout_outcomes(self) -> tuple[TimeoutOutcomeRecord, ...]: ...

    def record_output_commit(
        self,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit: ...

    def snapshot(self) -> StageLifecycleSnapshot: ...

    def scan_recovery(self) -> tuple[RecoveryRecord, ...]: ...

    def list_cleanup_candidates(self) -> tuple[CleanupCandidate, ...]: ...


@runtime_checkable
class RunStore(Protocol):
    """Public authority-backed run lifecycle surface."""

    def authority_config(self) -> AuthorityConfig: ...

    def capabilities(self) -> BackendCapabilitySet: ...

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck: ...

    def admit_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision: ...

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def acquire_run_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord: ...

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord: ...

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord: ...

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision: ...

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None: ...

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]: ...

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision: ...

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]: ...

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision: ...

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]: ...

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision: ...

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision: ...

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]: ...

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision: ...

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]: ...

    def stage_store(self, run_uri: str, stage_name: str) -> StageStore: ...

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]: ...

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]: ...


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityStoreError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityStoreError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityStoreError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityStoreError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise AuthorityStoreError(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _coerce_status(value: object, stage_name: str | None) -> RunStatus | StageStatus:
    if stage_name is None:
        if isinstance(value, RunStatus):
            return value
        if not isinstance(value, str):
            raise AuthorityStoreError("run status must be a string")
        try:
            return RunStatus(value)
        except ValueError as exc:
            raise AuthorityStoreError(f"invalid run status {value!r}") from exc
    if isinstance(value, StageStatus):
        return value
    if not isinstance(value, str):
        raise AuthorityStoreError("stage status must be a string")
    try:
        return StageStatus(value)
    except ValueError as exc:
        raise AuthorityStoreError(f"invalid stage status {value!r}") from exc


def _coerce_optional_status(
    value: object, stage_name: str | None
) -> RunStatus | StageStatus | None:
    if value is None:
        return None
    return _coerce_status(value, stage_name)


def _optional_reason(value: object) -> LifecycleReason | None:
    if value is None:
        return None
    return LifecycleReason.from_dict(value)


def _tuple_of[T](values: object, value_type: type[T], field: str) -> tuple[T, ...]:
    result = tuple(values)  # type: ignore[arg-type]
    if any(not isinstance(value, value_type) for value in result):
        raise AuthorityStoreError(f"{field} must contain {value_type.__name__} values")
    return result


__all__ = [
    "AuthorityStoreError",
    "StatusTransition",
    "AttemptAllocation",
    "OutputCommit",
    "PerRunAuthorityStore",
    "RunStore",
    "StageStore",
]
