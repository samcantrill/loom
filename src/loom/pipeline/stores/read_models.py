"""Authoritative read-model value records for v9 store contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp


class AuthorityModelError(ValueError):
    """Raised when authoritative store model records are invalid."""


class LeaseKind(StrEnum):
    CONTROLLER = "controller"
    STAGE = "stage"
    TRIAL = "trial"
    RESOURCE = "resource"


class LeaseState(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    FAILED = "failed"
    EXPIRED = "expired"


class MaterializedRefKind(StrEnum):
    ARTIFACT_PAYLOAD = "artifact_payload"
    STAGE_LOG = "stage_log"
    CONFIG = "config"
    PROVENANCE = "provenance"
    WORKER_HANDOFF = "worker_handoff"


class CleanupCandidateKind(StrEnum):
    STAGED_PAYLOAD = "staged_payload"
    WORKER_HANDOFF = "worker_handoff"
    MATERIALIZED_REF = "materialized_ref"


class RecoveryKind(StrEnum):
    ABANDONED_ATTEMPT = "abandoned_attempt"
    EXPIRED_LEASE = "expired_lease"
    PARTIAL_COMMIT = "partial_commit"
    INTERRUPTED_SUBMISSION = "interrupted_submission"


class StaticOutcomeKind(StrEnum):
    SELECTED = "selected"
    NOT_SELECTED = "not_selected"
    BLOCKED = "blocked"


class ReadModelWarningCode(StrEnum):
    MISSING_MATERIALIZED_REF = "missing_materialized_ref"
    STALE_PROJECTION = "stale_projection"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    ACTIVE_RUN_CHANGING = "active_run_changing"
    PARTIAL_COMMIT = "partial_commit"


@dataclass(frozen=True, slots=True)
class BackendRevision:
    sequence: int
    token: str
    created_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _positive_int(self.sequence, "sequence"))
        object.__setattr__(self, "token", _non_empty_string(self.token, "token"))
        if self.created_at is not None:
            _timestamp(self.created_at, "created_at")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sequence": self.sequence,
            "token": self.token,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class LifecycleReason:
    code: str
    message: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _reason_code(self.code))
        if self.message is not None:
            object.__setattr__(
                self, "message", _non_empty_string(self.message, "message")
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class StageAttempt:
    run_uri: str
    stage_name: str
    attempt: int
    attempt_id: str
    status: StageStatus
    revision: BackendRevision
    created_at: str
    owner: str | None = None
    reason: LifecycleReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "attempt"))
        object.__setattr__(
            self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
        )
        object.__setattr__(self, "status", _stage_status(self.status))
        _revision(self.revision)
        _timestamp(self.created_at, "created_at")
        if self.owner is not None:
            object.__setattr__(self, "owner", _non_empty_string(self.owner, "owner"))
        if self.reason is not None and not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "revision": self.revision.to_dict(),
            "created_at": self.created_at,
            "owner": self.owner,
            "reason": None if self.reason is None else self.reason.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LeaseRecord:
    lease_id: str
    kind: LeaseKind
    owner_id: str
    fencing_token: str
    acquired_at: str
    renewed_at: str
    expires_at: str
    revision: BackendRevision
    state: LeaseState = LeaseState.ACTIVE
    run_uri: str | None = None
    stage_name: str | None = None
    attempt_id: str | None = None
    reason: LifecycleReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _non_empty_string(self.lease_id, "lease_id"))
        object.__setattr__(self, "kind", _coerce_enum(self.kind, LeaseKind, "kind"))
        object.__setattr__(self, "owner_id", _non_empty_string(self.owner_id, "owner_id"))
        object.__setattr__(
            self,
            "fencing_token",
            _non_empty_string(self.fencing_token, "fencing_token"),
        )
        _timestamp(self.acquired_at, "acquired_at")
        _timestamp(self.renewed_at, "renewed_at")
        _timestamp(self.expires_at, "expires_at")
        _revision(self.revision)
        object.__setattr__(self, "state", _coerce_enum(self.state, LeaseState, "state"))
        if self.run_uri is not None:
            object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        if self.stage_name is not None:
            object.__setattr__(
                self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
            )
        if self.attempt_id is not None:
            object.__setattr__(
                self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
            )
        if self.kind is LeaseKind.STAGE and (
            self.run_uri is None or self.stage_name is None or self.attempt_id is None
        ):
            raise AuthorityModelError(
                "stage leases require run_uri, stage_name, and attempt_id"
            )
        if self.reason is not None and not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "lease_id": self.lease_id,
            "kind": self.kind.value,
            "owner_id": self.owner_id,
            "fencing_token": self.fencing_token,
            "acquired_at": self.acquired_at,
            "renewed_at": self.renewed_at,
            "expires_at": self.expires_at,
            "revision": self.revision.to_dict(),
            "state": self.state.value,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt_id": self.attempt_id,
            "reason": None if self.reason is None else self.reason.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OutputCommitRecord:
    commit_id: str
    run_uri: str
    stage_name: str
    attempt_id: str
    committed_at: str
    revision: BackendRevision
    output_names: tuple[str, ...] = ()
    materialized_refs: tuple["MaterializedRef", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commit_id", _non_empty_string(self.commit_id, "commit_id")
        )
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
        )
        _timestamp(self.committed_at, "committed_at")
        _revision(self.revision)
        object.__setattr__(
            self, "output_names", tuple(_non_empty_string(name, "output_name") for name in self.output_names)
        )
        refs = tuple(self.materialized_refs)
        if any(not isinstance(ref, MaterializedRef) for ref in refs):
            raise AuthorityModelError(
                "materialized_refs must contain MaterializedRef values"
            )
        object.__setattr__(self, "materialized_refs", refs)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "commit_id": self.commit_id,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt_id": self.attempt_id,
            "committed_at": self.committed_at,
            "revision": self.revision.to_dict(),
            "output_names": list(self.output_names),
            "materialized_refs": [ref.to_dict() for ref in self.materialized_refs],
        }


@dataclass(frozen=True, slots=True)
class ArtifactFactRecord:
    artifact_name: str
    artifact: ArtifactRef
    commit_id: str
    revision: BackendRevision

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_name",
            _non_empty_string(self.artifact_name, "artifact_name"),
        )
        if not isinstance(self.artifact, ArtifactRef):
            raise AuthorityModelError("artifact must be an ArtifactRef")
        object.__setattr__(self, "commit_id", _non_empty_string(self.commit_id, "commit_id"))
        _revision(self.revision)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "artifact_name": self.artifact_name,
            "artifact": self.artifact.to_dict(),
            "commit_id": self.commit_id,
            "revision": self.revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MaterializedRef:
    kind: MaterializedRefKind
    uri: str
    exists: bool | None = None
    checksum: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(self.kind, MaterializedRefKind, "kind"))
        object.__setattr__(self, "uri", _non_empty_string(self.uri, "uri"))
        if self.exists is not None and not isinstance(self.exists, bool):
            raise AuthorityModelError("exists must be a bool or None")
        if self.checksum is not None:
            object.__setattr__(
                self, "checksum", _non_empty_string(self.checksum, "checksum")
            )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "uri": self.uri,
            "exists": self.exists,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    candidate_id: str
    kind: CleanupCandidateKind
    uri: str
    reason: LifecycleReason
    recorded_at: str
    revision: BackendRevision

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _non_empty_string(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(self.kind, CleanupCandidateKind, "kind")
        )
        object.__setattr__(self, "uri", _non_empty_string(self.uri, "uri"))
        if not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason")
        _timestamp(self.recorded_at, "recorded_at")
        _revision(self.revision)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "uri": self.uri,
            "reason": self.reason.to_dict(),
            "recorded_at": self.recorded_at,
            "revision": self.revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    recovery_id: str
    kind: RecoveryKind
    reason: LifecycleReason
    detected_at: str
    revision: BackendRevision
    run_uri: str | None = None
    stage_name: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recovery_id", _non_empty_string(self.recovery_id, "recovery_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(self.kind, RecoveryKind, "kind"))
        if not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason")
        _timestamp(self.detected_at, "detected_at")
        _revision(self.revision)
        if self.run_uri is not None:
            object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        if self.stage_name is not None:
            object.__setattr__(
                self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
            )
        if self.attempt_id is not None:
            object.__setattr__(
                self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "recovery_id": self.recovery_id,
            "kind": self.kind.value,
            "reason": self.reason.to_dict(),
            "detected_at": self.detected_at,
            "revision": self.revision.to_dict(),
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt_id": self.attempt_id,
        }


@dataclass(frozen=True, slots=True)
class StaticOutcomeRecord:
    run_uri: str
    stage_name: str
    outcome: StaticOutcomeKind
    status: StageStatus
    reason: LifecycleReason
    revision: BackendRevision

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self, "outcome", _coerce_enum(self.outcome, StaticOutcomeKind, "outcome")
        )
        object.__setattr__(self, "status", _stage_status(self.status))
        if self.outcome is StaticOutcomeKind.NOT_SELECTED and self.status is not StageStatus.SKIPPED:
            raise AuthorityModelError(
                "not_selected static outcomes must use StageStatus.SKIPPED"
            )
        if not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason")
        _revision(self.revision)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "outcome": self.outcome.value,
            "status": self.status.value,
            "reason": self.reason.to_dict(),
            "revision": self.revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReadModelWarning:
    code: ReadModelWarningCode
    message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)
    revision: BackendRevision | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _coerce_enum(self.code, ReadModelWarningCode, "code"))
        object.__setattr__(
            self, "message", _non_empty_string(self.message, "message")
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))
        if self.revision is not None:
            _revision(self.revision)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code.value,
            "message": self.message,
            "detail": dict(self.detail),
            "revision": None if self.revision is None else self.revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class StageLifecycleSnapshot:
    stage_name: str
    status: StageStatus
    revision: BackendRevision
    attempts: tuple[StageAttempt, ...] = ()
    active_lease: LeaseRecord | None = None
    latest_commit: OutputCommitRecord | None = None
    artifact_facts: tuple[ArtifactFactRecord, ...] = ()
    static_outcome: StaticOutcomeRecord | None = None
    reason: LifecycleReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(self, "status", _stage_status(self.status))
        _revision(self.revision)
        object.__setattr__(self, "attempts", _tuple_of(self.attempts, StageAttempt, "attempts"))
        if self.active_lease is not None and not isinstance(self.active_lease, LeaseRecord):
            raise AuthorityModelError("active_lease must be a LeaseRecord or None")
        if self.latest_commit is not None and not isinstance(
            self.latest_commit, OutputCommitRecord
        ):
            raise AuthorityModelError("latest_commit must be an OutputCommitRecord or None")
        object.__setattr__(
            self,
            "artifact_facts",
            _tuple_of(self.artifact_facts, ArtifactFactRecord, "artifact_facts"),
        )
        if self.static_outcome is not None and not isinstance(
            self.static_outcome, StaticOutcomeRecord
        ):
            raise AuthorityModelError(
                "static_outcome must be a StaticOutcomeRecord or None"
            )
        if self.reason is not None and not isinstance(self.reason, LifecycleReason):
            raise AuthorityModelError("reason must be a LifecycleReason or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": self.status.value,
            "revision": self.revision.to_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "active_lease": None
            if self.active_lease is None
            else self.active_lease.to_dict(),
            "latest_commit": None
            if self.latest_commit is None
            else self.latest_commit.to_dict(),
            "artifact_facts": [fact.to_dict() for fact in self.artifact_facts],
            "static_outcome": None
            if self.static_outcome is None
            else self.static_outcome.to_dict(),
            "reason": None if self.reason is None else self.reason.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeRunSnapshot:
    run_uri: str
    status: RunStatus
    schema_version: int
    revision: BackendRevision
    stages: tuple[StageLifecycleSnapshot, ...] = ()
    submitted_operations: tuple[SubmittedOperationRecord, ...] = ()
    cleanup_candidates: tuple[CleanupCandidate, ...] = ()
    materialized_refs: tuple[MaterializedRef, ...] = ()
    warnings: tuple[ReadModelWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(self, "status", _run_status(self.status))
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, "schema_version"),
        )
        _revision(self.revision)
        object.__setattr__(
            self, "stages", _tuple_of(self.stages, StageLifecycleSnapshot, "stages")
        )
        object.__setattr__(
            self,
            "submitted_operations",
            _tuple_of(
                self.submitted_operations,
                SubmittedOperationRecord,
                "submitted_operations",
            ),
        )
        object.__setattr__(
            self,
            "cleanup_candidates",
            _tuple_of(self.cleanup_candidates, CleanupCandidate, "cleanup_candidates"),
        )
        object.__setattr__(
            self,
            "materialized_refs",
            _tuple_of(self.materialized_refs, MaterializedRef, "materialized_refs"),
        )
        object.__setattr__(
            self, "warnings", _tuple_of(self.warnings, ReadModelWarning, "warnings")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status.value,
            "schema_version": self.schema_version,
            "revision": self.revision.to_dict(),
            "stages": [stage.to_dict() for stage in self.stages],
            "submitted_operations": [
                operation.to_dict() for operation in self.submitted_operations
            ],
            "cleanup_candidates": [
                candidate.to_dict() for candidate in self.cleanup_candidates
            ],
            "materialized_refs": [ref.to_dict() for ref in self.materialized_refs],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def _coerce_enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityModelError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityModelError(f"invalid {field} {value!r}") from exc


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityModelError(f"{field} must be a non-empty string")
    return value


def _reason_code(value: object) -> str:
    text = _non_empty_string(value, "code")
    if not text.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise AuthorityModelError(
            "code must contain letters, digits, '_', '-', or '.'"
        )
    return text


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityModelError(f"{field} must be a positive integer")
    return value


def _timestamp(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise AuthorityModelError(f"{field} must be a valid loom timestamp") from exc
    return text


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthorityModelError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthorityModelError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _revision(value: object) -> BackendRevision:
    if not isinstance(value, BackendRevision):
        raise AuthorityModelError("revision must be a BackendRevision")
    return value


def _stage_status(value: object) -> StageStatus:
    if isinstance(value, StageStatus):
        return value
    if not isinstance(value, str):
        raise AuthorityModelError("stage status must be a string")
    try:
        return StageStatus(value)
    except ValueError as exc:
        raise AuthorityModelError(f"invalid stage status {value!r}") from exc


def _run_status(value: object) -> RunStatus:
    if isinstance(value, RunStatus):
        return value
    if not isinstance(value, str):
        raise AuthorityModelError("run status must be a string")
    try:
        return RunStatus(value)
    except ValueError as exc:
        raise AuthorityModelError(f"invalid run status {value!r}") from exc


def _tuple_of[T](values: object, value_type: type[T], field: str) -> tuple[T, ...]:
    result = tuple(cast(tuple[T, ...], values))
    if any(not isinstance(value, value_type) for value in result):
        raise AuthorityModelError(f"{field} must contain {value_type.__name__} values")
    return result


__all__ = [
    "AuthorityModelError",
    "LeaseKind",
    "LeaseState",
    "MaterializedRefKind",
    "CleanupCandidateKind",
    "RecoveryKind",
    "StaticOutcomeKind",
    "ReadModelWarningCode",
    "BackendRevision",
    "LifecycleReason",
    "StageAttempt",
    "LeaseRecord",
    "OutputCommitRecord",
    "ArtifactFactRecord",
    "MaterializedRef",
    "CleanupCandidate",
    "RecoveryRecord",
    "StaticOutcomeRecord",
    "ReadModelWarning",
    "StageLifecycleSnapshot",
    "AuthoritativeRunSnapshot",
]
