"""Deferred result envelope records and reconciliation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    is_terminal_submitted_operation,
    validate_submission_id,
)
from loom.serialization import PlainData, ensure_plain_data, load_versioned_document
from loom.serialization.errors import PlainDataError, SchemaVersionError
from loom.timestamps import parse_timestamp

from .authority import PerRunAuthorityStore
from .read_models import BackendRevision, LifecycleReason, StageLifecycleSnapshot
from .run_uri import validate_run_uri


DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION = 1

_TERMINAL_ENVELOPE_STATUSES = frozenset(
    {StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.CANCELLED}
)
_OPEN_STAGE_STATUSES = frozenset({StageStatus.RUNNING, StageStatus.SUBMITTED})


class DeferredFinalizationError(ValueError):
    """Raised when deferred finalization records are invalid."""


class DeferredReconciliationCode(StrEnum):
    ACCEPTED = "accepted"
    UNKNOWN_RUN = "unknown_run"
    UNKNOWN_STAGE = "unknown_stage"
    UNKNOWN_ATTEMPT = "unknown_attempt"
    FOREIGN_ATTEMPT_OWNER = "foreign_attempt_owner"
    STALE_ATTEMPT = "stale_attempt"
    CANCELLED_STAGE = "cancelled_stage"
    SUPERSEDED_STAGE = "superseded_stage"
    SUBMISSION_MISMATCH = "submission_mismatch"
    MISSING_RECONCILER_FENCE = "missing_reconciler_fence"
    AUTHORITY_REJECTED = "authority_rejected"


@dataclass(frozen=True, slots=True)
class DeferredResultEnvelope:
    """Worker-produced evidence for later authority reconciliation.

    The envelope is intentionally evidence only. It never carries live lease or
    fencing material; the reconciler must supply any authority credentials it
    needs from controller-side state.
    """

    run_uri: str
    stage_name: str
    attempt_id: str
    submission_id: str
    owner_id: str
    produced_at: str
    producer_id: str
    status: StageStatus
    output_refs: Mapping[str, ArtifactRef] = field(default_factory=dict)
    diagnostics: tuple[LifecycleReason, ...] = ()
    materialized_refs: Mapping[str, PlainData] = field(default_factory=dict)
    plan_fingerprint: str | None = None
    schema_version: int = DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION:
            raise DeferredFinalizationError(
                "unsupported deferred result envelope schema_version"
            )
        object.__setattr__(self, "run_uri", validate_run_uri(self.run_uri))
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
        )
        object.__setattr__(
            self, "submission_id", validate_submission_id(self.submission_id)
        )
        object.__setattr__(
            self, "owner_id", _non_empty_string(self.owner_id, "owner_id")
        )
        object.__setattr__(
            self, "produced_at", _timestamp(self.produced_at, "produced_at")
        )
        object.__setattr__(
            self, "producer_id", _non_empty_string(self.producer_id, "producer_id")
        )
        object.__setattr__(self, "status", _terminal_status(self.status))
        object.__setattr__(
            self,
            "output_refs",
            {
                _non_empty_string(name, "output_refs key"): _artifact_ref(artifact)
                for name, artifact in self.output_refs.items()
            },
        )
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(reason, LifecycleReason) for reason in diagnostics):
            raise DeferredFinalizationError(
                "diagnostics must contain LifecycleReason values"
            )
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self,
            "materialized_refs",
            _plain_mapping(self.materialized_refs, "materialized_refs"),
        )
        if self.plan_fingerprint is not None:
            object.__setattr__(
                self,
                "plan_fingerprint",
                _non_empty_string(self.plan_fingerprint, "plan_fingerprint"),
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt_id": self.attempt_id,
            "submission_id": self.submission_id,
            "owner_id": self.owner_id,
            "produced_at": self.produced_at,
            "producer_id": self.producer_id,
            "status": self.status.value,
            "output_refs": {
                name: artifact.to_dict() for name, artifact in self.output_refs.items()
            },
            "diagnostics": [reason.to_dict() for reason in self.diagnostics],
            "materialized_refs": dict(self.materialized_refs),
            "plan_fingerprint": self.plan_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: object) -> "DeferredResultEnvelope":
        try:
            payload = load_versioned_document(
                data,
                current_version=DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "stage_name",
                    "attempt_id",
                    "submission_id",
                    "owner_id",
                    "produced_at",
                    "producer_id",
                    "status",
                },
                optional={
                    "output_refs",
                    "diagnostics",
                    "materialized_refs",
                    "plan_fingerprint",
                },
            )
        except SchemaVersionError as exc:
            raise DeferredFinalizationError(
                f"DeferredResultEnvelope.from_dict: {exc}"
            ) from exc
        _reject_unknown(
            payload,
            {
                "schema_version",
                "run_uri",
                "stage_name",
                "attempt_id",
                "submission_id",
                "owner_id",
                "produced_at",
                "producer_id",
                "status",
                "output_refs",
                "diagnostics",
                "materialized_refs",
                "plan_fingerprint",
            },
            "DeferredResultEnvelope",
        )
        output_refs = _mapping(payload.get("output_refs", {}), "output_refs")
        diagnostics = _sequence(payload.get("diagnostics", ()), "diagnostics")
        return cls(
            schema_version=DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION,
            run_uri=cast(str, payload["run_uri"]),
            stage_name=cast(str, payload["stage_name"]),
            attempt_id=cast(str, payload["attempt_id"]),
            submission_id=cast(str, payload["submission_id"]),
            owner_id=cast(str, payload["owner_id"]),
            produced_at=cast(str, payload["produced_at"]),
            producer_id=cast(str, payload["producer_id"]),
            status=_terminal_status(payload["status"]),
            output_refs={
                name: ArtifactRef.from_dict(artifact)
                for name, artifact in output_refs.items()
            },
            diagnostics=tuple(
                LifecycleReason.from_dict(reason) for reason in diagnostics
            ),
            materialized_refs=_plain_mapping(
                payload.get("materialized_refs", {}), "materialized_refs"
            ),
            plan_fingerprint=cast(str | None, payload.get("plan_fingerprint")),
        )


@dataclass(frozen=True, slots=True)
class DeferredReconciliationResult:
    """Result of reconciling one deferred envelope through authority."""

    accepted: bool
    code: DeferredReconciliationCode
    message: str
    run_uri: str
    stage_name: str
    attempt_id: str
    submission_id: str
    revision: BackendRevision | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _enum(self.code, DeferredReconciliationCode, "code")
        )
        object.__setattr__(self, "message", _non_empty_string(self.message, "message"))
        object.__setattr__(self, "run_uri", validate_run_uri(self.run_uri))
        object.__setattr__(
            self, "stage_name", _non_empty_string(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self, "attempt_id", _non_empty_string(self.attempt_id, "attempt_id")
        )
        object.__setattr__(
            self, "submission_id", validate_submission_id(self.submission_id)
        )
        if self.revision is not None and not isinstance(self.revision, BackendRevision):
            raise DeferredFinalizationError(
                "revision must be a BackendRevision or None"
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "accepted": self.accepted,
            "code": self.code.value,
            "message": self.message,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt_id": self.attempt_id,
            "submission_id": self.submission_id,
            "revision": None if self.revision is None else self.revision.to_dict(),
            "detail": dict(self.detail),
        }


def reconcile_deferred_result(
    authority_store: PerRunAuthorityStore,
    envelope: DeferredResultEnvelope,
    *,
    fencing_token: str | None = None,
) -> DeferredReconciliationResult:
    """Accept or reject a deferred envelope through authority state."""

    try:
        snapshot = authority_store.snapshot(envelope.run_uri)
    except Exception as exc:
        return _rejected(
            envelope,
            DeferredReconciliationCode.UNKNOWN_RUN,
            "run is not known to authority",
            error=str(exc),
        )
    stage = _stage(snapshot.stages, envelope.stage_name)
    if stage is None:
        return _rejected(
            envelope,
            DeferredReconciliationCode.UNKNOWN_STAGE,
            "stage is not known to authority",
        )
    attempt = next(
        (
            candidate
            for candidate in stage.attempts
            if candidate.attempt_id == envelope.attempt_id
        ),
        None,
    )
    if attempt is None:
        return _rejected(
            envelope,
            DeferredReconciliationCode.UNKNOWN_ATTEMPT,
            "attempt is not known to authority",
        )
    if attempt.owner != envelope.owner_id:
        return _rejected(
            envelope,
            DeferredReconciliationCode.FOREIGN_ATTEMPT_OWNER,
            "envelope owner does not match recorded attempt owner",
            recorded_owner=attempt.owner,
        )
    latest_attempt = max(stage.attempts, key=lambda value: value.attempt)
    if latest_attempt.attempt_id != envelope.attempt_id:
        return _rejected(
            envelope,
            DeferredReconciliationCode.STALE_ATTEMPT,
            "envelope attempt has been superseded",
            latest_attempt_id=latest_attempt.attempt_id,
        )
    if stage.latest_commit is not None:
        return _rejected(
            envelope,
            DeferredReconciliationCode.SUPERSEDED_STAGE,
            "stage already has an output commit",
            commit_id=stage.latest_commit.commit_id,
        )
    if stage.status is StageStatus.CANCELLED:
        return _rejected(
            envelope,
            DeferredReconciliationCode.CANCELLED_STAGE,
            "stage was cancelled before deferred reconciliation",
        )
    if stage.status not in _OPEN_STAGE_STATUSES:
        return _rejected(
            envelope,
            DeferredReconciliationCode.SUPERSEDED_STAGE,
            "stage is no longer open for deferred reconciliation",
            stage_status=stage.status.value,
        )
    submitted = _submitted(snapshot.submitted_operations, envelope.submission_id)
    if submitted is None:
        return _rejected(
            envelope,
            DeferredReconciliationCode.SUBMISSION_MISMATCH,
            "submission is not known to authority",
        )
    if is_terminal_submitted_operation(submitted):
        return _rejected(
            envelope,
            DeferredReconciliationCode.SUBMISSION_MISMATCH,
            "submission is already terminal",
            submission_state=submitted.state.value,
        )
    if envelope.status is StageStatus.SUCCEEDED:
        return _commit_success(authority_store, envelope, fencing_token=fencing_token)
    return _commit_terminal_status(authority_store, envelope, from_status=stage.status)


def _commit_success(
    authority_store: PerRunAuthorityStore,
    envelope: DeferredResultEnvelope,
    *,
    fencing_token: str | None,
) -> DeferredReconciliationResult:
    if not fencing_token:
        return _rejected(
            envelope,
            DeferredReconciliationCode.MISSING_RECONCILER_FENCE,
            "successful deferred reconciliation requires reconciler-held fencing token",
        )
    try:
        commit = authority_store.record_output_commit(
            envelope.run_uri,
            envelope.stage_name,
            attempt_id=envelope.attempt_id,
            fencing_token=fencing_token,
            outputs=envelope.output_refs,
            reason=LifecycleReason(
                code="deferred_finalization.accepted",
                detail={"submission_id": envelope.submission_id},
            ),
        )
    except Exception as exc:
        return _rejected(
            envelope,
            DeferredReconciliationCode.AUTHORITY_REJECTED,
            "authority rejected deferred output commit",
            error=str(exc),
        )
    return _accepted(envelope, revision=commit.commit.revision)


def _commit_terminal_status(
    authority_store: PerRunAuthorityStore,
    envelope: DeferredResultEnvelope,
    *,
    from_status: StageStatus,
) -> DeferredReconciliationResult:
    try:
        transition = authority_store.transition_stage(
            envelope.run_uri,
            envelope.stage_name,
            from_status=from_status,
            to_status=envelope.status,
            reason=LifecycleReason(
                code="deferred_finalization.accepted",
                detail={"submission_id": envelope.submission_id},
            ),
        )
    except Exception as exc:
        return _rejected(
            envelope,
            DeferredReconciliationCode.AUTHORITY_REJECTED,
            "authority rejected deferred terminal transition",
            error=str(exc),
        )
    return _accepted(envelope, revision=transition.revision)


def _accepted(
    envelope: DeferredResultEnvelope, *, revision: BackendRevision
) -> DeferredReconciliationResult:
    return DeferredReconciliationResult(
        accepted=True,
        code=DeferredReconciliationCode.ACCEPTED,
        message="deferred envelope accepted by authority",
        run_uri=envelope.run_uri,
        stage_name=envelope.stage_name,
        attempt_id=envelope.attempt_id,
        submission_id=envelope.submission_id,
        revision=revision,
    )


def _rejected(
    envelope: DeferredResultEnvelope,
    code: DeferredReconciliationCode,
    message: str,
    **detail: PlainData,
) -> DeferredReconciliationResult:
    return DeferredReconciliationResult(
        accepted=False,
        code=code,
        message=message,
        run_uri=envelope.run_uri,
        stage_name=envelope.stage_name,
        attempt_id=envelope.attempt_id,
        submission_id=envelope.submission_id,
        detail=detail,
    )


def _stage(
    stages: tuple[StageLifecycleSnapshot, ...], stage_name: str
) -> StageLifecycleSnapshot | None:
    return next((stage for stage in stages if stage.stage_name == stage_name), None)


def _submitted(
    records: tuple[SubmittedOperationRecord, ...], submission_id: str
) -> SubmittedOperationRecord | None:
    return next(
        (record for record in records if record.submission_id == submission_id),
        None,
    )


def _terminal_status(value: object) -> StageStatus:
    try:
        status = value if isinstance(value, StageStatus) else StageStatus(value)
    except ValueError as exc:
        raise DeferredFinalizationError(
            f"invalid deferred envelope status {value!r}"
        ) from exc
    if status not in _TERMINAL_ENVELOPE_STATUSES:
        raise DeferredFinalizationError(
            "deferred envelope status must be SUCCEEDED, FAILED, or CANCELLED"
        )
    return status


def _artifact_ref(value: object) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        return value
    return ArtifactRef.from_dict(value)


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise DeferredFinalizationError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise DeferredFinalizationError(f"invalid {field} {value!r}") from exc


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeferredFinalizationError(f"{field} must be a non-empty string")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise DeferredFinalizationError(f"{field} must be a string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise DeferredFinalizationError(f"{field} must be a valid timestamp") from exc
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DeferredFinalizationError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise DeferredFinalizationError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise DeferredFinalizationError(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise DeferredFinalizationError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise DeferredFinalizationError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise DeferredFinalizationError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


__all__ = [
    "DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION",
    "DeferredFinalizationError",
    "DeferredReconciliationCode",
    "DeferredReconciliationResult",
    "DeferredResultEnvelope",
    "reconcile_deferred_result",
]
