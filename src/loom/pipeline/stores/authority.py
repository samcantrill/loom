"""Backend-neutral per-run authority contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData

from .capabilities import BackendCapabilitySet
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    LeaseRecord,
    LifecycleReason,
    OutputCommitRecord,
    RecoveryRecord,
    StageAttempt,
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
            raise AuthorityStoreError("run status transitions must not include stage_name")
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

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]: ...

    def list_cleanup_candidates(
        self, run_uri: str
    ) -> tuple[CleanupCandidate, ...]: ...


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


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
]
