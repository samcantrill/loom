"""Private SQLite repository foundation for the authority service."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.offline_evidence import OfflineEvidenceManifest, OfflineStageEvidence
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import (
    InvalidRunTransition,
    InvalidStageTransition,
    TransitionIntent,
    ensure_run_transition,
    ensure_stage_transition,
)
from loom.pipeline.stores.authority import (
    AttemptAllocation,
    CancellationEpochReceipt,
    CancellationEpochRequest,
    CoordinatorAdmissionReceipt,
    CoordinatorAdmissionRequest,
    ExecutionFence,
    OutputCommit,
    PreparedAttemptReceipt,
    PreparedAttemptRequest,
    StatusTransition,
)
from loom.pipeline.stores.coordination import (
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    ResourceLeaseRecord,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    WorkspaceIdentity,
)
from loom.pipeline.stores.read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
    CleanupReportFact,
    CleanupResultFact,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    OutputCommitRecord,
    RecoveryKind,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageAttempt,
    StageLifecycleSnapshot,
)
from loom.pipeline.stores.reliability_facts import (
    reliability_payload_matches,
    reliability_policy_fact_key,
    reliability_status_detail_key,
    validate_policy_fact_run,
    validate_retry_decision_run,
    validate_status_detail_run,
    validate_timeout_outcome_run,
    validate_transaction_run,
)
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp


AUTHORITY_REPOSITORY_SCHEMA_VERSION = 6
AUTHORITY_REPOSITORY_DB_NAME = "authority.sqlite3"
AUTHORITY_REPOSITORY_COORDINATION_DB_NAME = "coordination.sqlite3"
_SQLITE_TIMEOUT_SECONDS = 30.0
_ADMISSION_IDEMPOTENCY_METADATA_KEY = "_loom_admission_idempotency_key"
_METADATA_TABLE = "repository_metadata"
_REQUIRED_SCHEMA_COLUMNS = {
    _METADATA_TABLE: frozenset({"key", "value"}),
    "repository_revisions": frozenset({"sequence", "token", "created_at"}),
    "authority_runs": frozenset(
        {
            "run_uri",
            "status",
            "metadata_json",
            "created_revision_sequence",
            "updated_revision_sequence",
            "reason_json",
        }
    ),
    "controller_leases": frozenset(
        {
            "lease_id",
            "run_uri",
            "owner_id",
            "fencing_token",
            "acquired_at",
            "renewed_at",
            "expires_at",
            "state",
            "revision_sequence",
            "reason_json",
        }
    ),
    "submitted_operations": frozenset(
        {"run_uri", "submission_id", "record_json", "revision_sequence"}
    ),
    "cleanup_candidates": frozenset(
        {
            "candidate_id",
            "run_uri",
            "kind",
            "uri",
            "reason_json",
            "recorded_at",
            "revision_sequence",
        }
    ),
    "cleanup_reports": frozenset(
        {"report_id", "run_uri", "record_json", "recorded_at", "revision_sequence"}
    ),
    "cleanup_results": frozenset(
        {"result_id", "run_uri", "record_json", "recorded_at", "revision_sequence"}
    ),
    "recovery_records": frozenset(
        {
            "recovery_id",
            "run_uri",
            "kind",
            "reason_json",
            "detected_at",
            "revision_sequence",
            "stage_name",
            "attempt_id",
        }
    ),
    "audit_events": frozenset(
        {
            "sequence",
            "run_uri",
            "timestamp",
            "scope_json",
            "event_type",
            "payload_json",
            "revision_sequence",
        }
    ),
    "authority_stages": frozenset(
        {"run_uri", "stage_name", "status", "revision_sequence", "reason_json"}
    ),
    "stage_attempts": frozenset(
        {
            "run_uri",
            "attempt_id",
            "stage_name",
            "attempt_number",
            "status",
            "owner_id",
            "created_at",
            "revision_sequence",
            "reason_json",
        }
    ),
    "stage_leases": frozenset(
        {
            "lease_id",
            "run_uri",
            "stage_name",
            "attempt_id",
            "owner_id",
            "fencing_token",
            "acquired_at",
            "renewed_at",
            "expires_at",
            "state",
            "revision_sequence",
            "reason_json",
        }
    ),
    "output_commits": frozenset(
        {
            "commit_id",
            "run_uri",
            "stage_name",
            "attempt_id",
            "committed_at",
            "revision_sequence",
            "output_names_json",
            "materialized_refs_json",
            "supersedes_commit_id",
        }
    ),
    "artifact_facts": frozenset(
        {
            "id",
            "run_uri",
            "stage_name",
            "artifact_name",
            "artifact_json",
            "commit_id",
            "revision_sequence",
        }
    ),
    "prepared_attempt_receipts": frozenset(
        {
            "run_uri",
            "operation_id",
            "request_digest",
            "readiness_generation",
            "stage_name",
            "attempt_id",
            "request_json",
            "receipt_json",
            "revision_sequence",
        }
    ),
    "managed_attempt_bindings": frozenset(
        {
            "run_uri",
            "assignment_id",
            "attempt_id",
            "state",
            "fence",
            "terminal_status",
            "terminal_digest",
        }
    ),
    "managed_attempt_unbind_receipts": frozenset(
        {"run_uri", "assignment_id", "attempt_id"}
    ),
    "coordinator_admission_receipts": frozenset(
        {
            "run_uri",
            "operation_id",
            "service_principal",
            "request_json",
            "receipt_json",
        }
    ),
    "cancellation_epochs": frozenset({"run_uri", "epoch"}),
    "cancellation_epoch_receipts": frozenset(
        {"run_uri", "operation_id", "request_json", "receipt_json"}
    ),
    "reliability_policy_facts": frozenset(
        {
            "run_uri",
            "fact_key",
            "scope",
            "stage_name",
            "attempt_number",
            "recorded_at",
            "fact_json",
            "revision_sequence",
        }
    ),
    "reliability_status_details": frozenset(
        {
            "run_uri",
            "fact_key",
            "stage_name",
            "attempt_number",
            "created_at",
            "detail_json",
            "revision_sequence",
        }
    ),
    "reliability_transactions": frozenset(
        {
            "run_uri",
            "transaction_id",
            "stage_name",
            "attempt_number",
            "causal_parent_id",
            "record_json",
            "revision_sequence",
        }
    ),
    "retry_decisions": frozenset(
        {
            "run_uri",
            "decision_id",
            "transaction_id",
            "stage_name",
            "attempt_number",
            "record_json",
            "revision_sequence",
        }
    ),
    "timeout_outcomes": frozenset(
        {
            "run_uri",
            "outcome_id",
            "transaction_id",
            "stage_name",
            "attempt_number",
            "record_json",
            "revision_sequence",
        }
    ),
}
_REQUIRED_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "service_generation",
        "created_at",
        "updated_at",
    }
)
_ATTEMPT_ALLOCATABLE_STAGE_STATUSES = frozenset(
    {
        StageStatus.PENDING,
        StageStatus.RUNNING,
        StageStatus.SUBMITTED,
        StageStatus.STALE,
    }
)
_ATTEMPT_TERMINAL_STATUSES = frozenset(
    {
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.STALE,
        StageStatus.CANCELLED,
    }
)


class AuthorityRepositoryError(RuntimeError):
    """Base error for private authority repository failures."""


class AuthorityRepositoryCompatibilityKind(StrEnum):
    """Private repository compatibility failure kinds."""

    MISSING = "missing"
    UNSUPPORTED_OLDER = "unsupported_older"
    UNSUPPORTED_NEWER = "unsupported_newer"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class AuthorityRepositoryCompatibilityFailure:
    """Structured compatibility failure for later server/protocol mapping."""

    kind: AuthorityRepositoryCompatibilityKind
    message: str
    found_version: int | None = None
    current_version: int = AUTHORITY_REPOSITORY_SCHEMA_VERSION
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _coerce_kind(self.kind, "kind"),
        )
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        if self.found_version is not None:
            object.__setattr__(
                self,
                "found_version",
                _positive_int(self.found_version, "found_version"),
            )
        object.__setattr__(
            self,
            "current_version",
            _positive_int(self.current_version, "current_version"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def code(self) -> str:
        return f"authority_repository_{self.kind.value}"

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "message": self.message,
            "found_version": self.found_version,
            "current_version": self.current_version,
            "detail": dict(self.detail),
        }


class AuthorityRepositoryCompatibilityError(AuthorityRepositoryError):
    """Raised when a private repository is missing or incompatible."""

    def __init__(self, failure: AuthorityRepositoryCompatibilityFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class AuthorityRepositoryIdentity:
    """Stable identity facts for a private authority repository."""

    state_dir: Path
    database_path: Path
    schema_version: int
    service_generation: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_dir", Path(self.state_dir))
        object.__setattr__(self, "database_path", Path(self.database_path))
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "service_generation",
            _non_empty(self.service_generation, "service_generation"),
        )
        parse_timestamp(self.created_at)
        parse_timestamp(self.updated_at)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "state_dir": str(self.state_dir),
            "database_path": str(self.database_path),
            "schema_version": self.schema_version,
            "service_generation": self.service_generation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AuthorityRepository:
    """Private SQLite repository handle for an authority service state dir."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        schema_version: int = AUTHORITY_REPOSITORY_SCHEMA_VERSION,
        database_name: str = AUTHORITY_REPOSITORY_DB_NAME,
        clock: Callable[[], datetime | str] | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.schema_version = _positive_int(schema_version, "schema_version")
        self.database_name = _database_name(database_name)
        self.database_path = self.state_dir / self.database_name
        self._clock = clock

    def initialize(
        self,
        *,
        service_generation: str | None = None,
    ) -> AuthorityRepositoryIdentity:
        generation = (
            _non_empty(service_generation, "service_generation")
            if service_generation is not None
            else generate_service_generation()
        )
        now = self._now()
        try:
            with self._connection(create_parent=True) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _migrate_v3_output_commits(
                        conn, current_version=self.schema_version
                    )
                    _migrate_v5_coordinator_principals(
                        conn, current_version=self.schema_version
                    )
                    _initialize_schema(
                        conn,
                        schema_version=self.schema_version,
                        service_generation=generation,
                        timestamp=now,
                    )
                    failure = _compatibility_failure(
                        conn, current_version=self.schema_version
                    )
                    if failure is not None:
                        raise AuthorityRepositoryCompatibilityError(failure)
                    identity = _identity_from_connection(self, conn)
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                    return identity
        except sqlite3.DatabaseError as exc:
            raise AuthorityRepositoryCompatibilityError(
                _corrupt_failure(
                    "authority repository database is corrupt or unreadable",
                    current_version=self.schema_version,
                )
            ) from exc

    def read_identity(self) -> AuthorityRepositoryIdentity:
        with self._read_connection() as conn:
            return _identity_from_connection(self, conn)

    def admit_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
        idempotency_key: str | None = None,
    ) -> BackendRevision:
        """Persist a newly admitted run and return its initial revision."""

        run_uri = _non_empty(run_uri, "run_uri")
        run_status = RunStatus(status)
        run_metadata = _plain_mapping(metadata or {}, "metadata")
        persisted_metadata = _admission_metadata(run_metadata, idempotency_key)
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT metadata_json FROM authority_runs WHERE run_uri = ?",
                (run_uri,),
            ).fetchone()
            if existing is not None:
                existing_metadata = _plain_mapping(
                    _json_loads(cast(str, existing["metadata_json"])), "metadata"
                )
                if _admission_matches(existing_metadata, run_metadata, idempotency_key):
                    return _current_run_revision(conn, run_uri)
                raise AuthorityRepositoryError(f"run already exists: {run_uri}")
            revision = self._next_revision(conn)
            conn.execute(
                """
                INSERT INTO authority_runs (
                    run_uri, status, metadata_json, created_revision_sequence,
                    updated_revision_sequence, reason_json
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_uri,
                    run_status.value,
                    _json_dumps(dict(persisted_metadata)),
                    revision.sequence,
                    revision.sequence,
                ),
            )
            return revision

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        """Read the current run-level snapshot for a persisted run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            return _run_snapshot(
                conn,
                run_uri=run_uri,
                schema_version=self.schema_version,
                now=self._now(),
            )

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        """Persist a run status transition after status and revision checks."""

        run_uri = _non_empty(run_uri, "run_uri")
        from_status = RunStatus(from_status)
        to_status = RunStatus(to_status)
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            row = _require_run_row(conn, run_uri)
            current = RunStatus(cast(str, row["status"]))
            current_revision = _revision_for(
                conn, cast(int, row["updated_revision_sequence"])
            )
            _require_expected_revision(current_revision, expected_revision)
            if current is not from_status:
                raise AuthorityRepositoryError("stale run transition")
            try:
                ensure_run_transition(current, to_status, intent=intent)
            except InvalidRunTransition as exc:
                raise AuthorityRepositoryError(str(exc)) from exc
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE authority_runs
                SET status = ?, updated_revision_sequence = ?, reason_json = ?
                WHERE run_uri = ?
                """,
                (
                    to_status.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    run_uri,
                ),
            )
            return StatusTransition(
                run_uri=run_uri,
                previous_status=current,
                status=to_status,
                revision=revision,
                reason=reason,
            )

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        """Persist a stage status transition after status and revision checks."""

        run_uri = _non_empty(run_uri, "run_uri")
        stage_name = _non_empty(stage_name, "stage_name")
        to_status = StageStatus(to_status)
        expected_status = None if from_status is None else StageStatus(from_status)
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            current_revision = _current_run_revision(conn, run_uri)
            _require_expected_revision(current_revision, expected_revision)
            row = conn.execute(
                """
                SELECT status
                FROM authority_stages
                WHERE run_uri = ? AND stage_name = ?
                """,
                (run_uri, stage_name),
            ).fetchone()
            current = None if row is None else StageStatus(cast(str, row["status"]))
            if current is not expected_status:
                raise AuthorityRepositoryError("stale stage transition")
            try:
                ensure_stage_transition(current, to_status, intent=intent)
            except InvalidStageTransition as exc:
                raise AuthorityRepositoryError(str(exc)) from exc
            revision = self._next_revision(conn)
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=to_status,
                revision=revision,
                reason=reason,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return StatusTransition(
                run_uri=run_uri,
                stage_name=stage_name,
                previous_status=current,
                status=to_status,
                revision=revision,
                reason=reason,
            )

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
        expected_revision: BackendRevision | None = None,
    ) -> AttemptAllocation:
        """Allocate a stage attempt and optionally acquire its stage lease."""

        run_uri = _non_empty(run_uri, "run_uri")
        stage_name = _non_empty(stage_name, "stage_name")
        owner_id = _non_empty(owner_id, "owner_id")
        if lease_ttl_seconds is not None:
            lease_ttl_seconds = _positive_seconds(lease_ttl_seconds)
        with self.transaction() as conn:
            current_revision = _current_run_revision(conn, run_uri)
            _require_expected_revision(current_revision, expected_revision)
            now = self._now()
            active = _active_stage_lease_row(
                conn, run_uri=run_uri, stage_name=stage_name, now=now
            )
            if active is not None:
                raise AuthorityRepositoryError("stage already has an active lease")
            existing_commit = conn.execute(
                """
                SELECT 1
                FROM output_commits
                WHERE run_uri = ? AND stage_name = ?
                """,
                (run_uri, stage_name),
            ).fetchone()
            stage_row = conn.execute(
                """
                SELECT status
                FROM authority_stages
                WHERE run_uri = ? AND stage_name = ?
                """,
                (run_uri, stage_name),
            ).fetchone()
            if stage_row is not None:
                stage_status = StageStatus(cast(str, stage_row["status"]))
                if stage_status not in _ATTEMPT_ALLOCATABLE_STAGE_STATUSES:
                    raise AuthorityRepositoryError("stage is already terminal")
                if (
                    existing_commit is not None
                    and stage_status is not StageStatus.STALE
                ):
                    raise AuthorityRepositoryError(
                        "stage with an output commit must be stale before repair"
                    )
            elif existing_commit is not None:
                raise AuthorityRepositoryError(
                    "stage with an output commit must be stale before repair"
                )
            attempt_number = _next_attempt_number(conn, run_uri, stage_name)
            revision = self._next_revision(conn)
            attempt_id = f"{stage_name}-{attempt_number}"
            conn.execute(
                """
                INSERT INTO stage_attempts (
                    run_uri, attempt_id, stage_name, attempt_number, status,
                    owner_id, created_at, revision_sequence, reason_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_uri,
                    attempt_id,
                    stage_name,
                    attempt_number,
                    StageStatus.RUNNING.value,
                    owner_id,
                    now,
                    revision.sequence,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=StageStatus.RUNNING,
                revision=revision,
                reason=None,
            )
            lease = None
            if lease_ttl_seconds is not None:
                lease = _insert_stage_lease(
                    conn,
                    run_uri=run_uri,
                    stage_name=stage_name,
                    attempt_id=attempt_id,
                    owner_id=owner_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                    revision=revision,
                    now=now,
                )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            attempt = StageAttempt(
                run_uri=run_uri,
                stage_name=stage_name,
                attempt=attempt_number,
                attempt_id=attempt_id,
                status=StageStatus.RUNNING,
                revision=revision,
                created_at=now,
                owner=owner_id,
            )
            return AttemptAllocation(attempt=attempt, lease=lease)

    def ensure_prepared_attempt(
        self, run_uri: str, request: PreparedAttemptRequest
    ) -> PreparedAttemptReceipt:
        """Validate and create one receipt/PENDING attempt atomically."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(request, PreparedAttemptRequest):
            raise AuthorityRepositoryError(
                "request must be a PreparedAttemptRequest"
            )
        request_json = _json_dumps(request.to_dict())
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT request_json, receipt_json, attempt_id
                FROM prepared_attempt_receipts
                WHERE run_uri = ? AND operation_id = ?
                """,
                (run_uri, request.operation_id),
            ).fetchone()
            if row is not None:
                existing_request = PreparedAttemptRequest.from_dict(
                    _json_loads(cast(str, row["request_json"]))
                )
                if existing_request != request:
                    raise AuthorityRepositoryError(
                        "prepared attempt operation conflicts with its receipt"
                    )
                attempt_row = conn.execute(
                    "SELECT 1 FROM stage_attempts "
                    "WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, row["attempt_id"]),
                ).fetchone()
                if attempt_row is None:
                    raise AuthorityRepositoryError(
                        "prepared attempt receipt has no attempt"
                    )
                receipt = PreparedAttemptReceipt.from_dict(
                    _json_loads(cast(str, row["receipt_json"]))
                )
                if receipt.request != request:
                    raise AuthorityRepositoryError(
                        "prepared attempt operation conflicts with its receipt"
                    )
                return receipt
            _require_no_repository_cancellation_epoch(conn, run_uri)
            existing = conn.execute(
                """
                SELECT 1 FROM prepared_attempt_receipts
                WHERE run_uri = ? AND stage_name = ?
                    AND readiness_generation = ?
                """,
                (run_uri, request.stage_name, request.readiness_generation),
            ).fetchone()
            if existing is not None:
                raise AuthorityRepositoryError(
                    "readiness generation was prepared by another operation"
                )

            current_revision = _current_run_revision(conn, run_uri)
            _require_expected_revision(current_revision, request.expected_revision)
            run_status = RunStatus(cast(str, _require_run_row(conn, run_uri)["status"]))
            if run_status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
            }:
                raise AuthorityRepositoryError("run is terminal or cancelling")

            stage_row = conn.execute(
                "SELECT status FROM authority_stages "
                "WHERE run_uri = ? AND stage_name = ?",
                (run_uri, request.stage_name),
            ).fetchone()
            stage_status = (
                None
                if stage_row is None
                else StageStatus(cast(str, stage_row["status"]))
            )
            if stage_status is not request.expected_stage_status:
                raise AuthorityRepositoryError("prepared attempt stage state is stale")
            if stage_status not in {None, StageStatus.STALE, StageStatus.FAILED}:
                raise AuthorityRepositoryError(
                    "stage state does not permit semantic attempt preparation"
                )
            attempt_row = conn.execute(
                """
                SELECT attempt_id, attempt_number
                FROM stage_attempts
                WHERE run_uri = ? AND stage_name = ?
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                (run_uri, request.stage_name),
            ).fetchone()
            current_attempt_id = (
                None if attempt_row is None else cast(str, attempt_row["attempt_id"])
            )
            if current_attempt_id != request.expected_attempt_id:
                raise AuthorityRepositoryError("prepared attempt identity is stale")
            attempt_number = _next_attempt_number(
                conn, run_uri, request.stage_name
            )
            if attempt_number != request.next_attempt:
                raise AuthorityRepositoryError("prepared attempt number is stale")

            for upstream_stage, commit_id in request.upstream_commits.items():
                commit_row = conn.execute(
                    """
                    SELECT commit_id FROM output_commits
                    WHERE run_uri = ? AND stage_name = ?
                    ORDER BY revision_sequence DESC
                    LIMIT 1
                    """,
                    (run_uri, upstream_stage),
                ).fetchone()
                if (
                    commit_row is None
                    or cast(str, commit_row["commit_id"]) != commit_id
                ):
                    raise AuthorityRepositoryError("upstream commit evidence is stale")

            if request.expected_stage_status is StageStatus.FAILED:
                if request.retry_decision_id is None:
                    raise AuthorityRepositoryError(
                        "failed stage retry is not authorized"
                    )
                decision_row = conn.execute(
                    """
                    SELECT record_json FROM retry_decisions
                    WHERE run_uri = ? AND decision_id = ? AND stage_name = ?
                    """,
                    (run_uri, request.retry_decision_id, request.stage_name),
                ).fetchone()
                if decision_row is None:
                    raise AuthorityRepositoryError(
                        "failed stage retry is not authorized"
                    )
                decision = RetryDecisionRecord.from_dict(
                    _json_loads(cast(str, decision_row["record_json"]))
                )
                if not decision.should_retry or decision.next_attempt != attempt_number:
                    raise AuthorityRepositoryError(
                        "failed stage retry is not authorized"
                    )
            elif request.retry_decision_id is not None:
                raise AuthorityRepositoryError(
                    "retry evidence requires a failed stage"
                )

            now = self._now()
            revision = self._next_revision(conn)
            attempt_id = f"{request.stage_name}-{attempt_number}"
            conn.execute(
                """
                INSERT INTO stage_attempts (
                    run_uri, attempt_id, stage_name, attempt_number, status,
                    owner_id, created_at, revision_sequence, reason_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_uri,
                    attempt_id,
                    request.stage_name,
                    attempt_number,
                    StageStatus.PENDING.value,
                    request.owner_id,
                    now,
                    revision.sequence,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=request.stage_name,
                status=StageStatus.PENDING,
                revision=revision,
                reason=None,
            )
            attempt = StageAttempt(
                run_uri=run_uri,
                stage_name=request.stage_name,
                attempt=attempt_number,
                attempt_id=attempt_id,
                status=StageStatus.PENDING,
                revision=revision,
                created_at=now,
                owner=request.owner_id,
            )
            receipt = PreparedAttemptReceipt(request, attempt)
            conn.execute(
                """
                INSERT INTO prepared_attempt_receipts (
                    run_uri, operation_id, request_digest, readiness_generation,
                    stage_name, attempt_id, request_json, receipt_json,
                    revision_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_uri,
                    request.operation_id,
                    request.request_digest,
                    request.readiness_generation,
                    request.stage_name,
                    attempt_id,
                    request_json,
                    _json_dumps(receipt.to_dict()),
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return receipt

    def bind_coordinator_admission(
        self,
        run_uri: str,
        request: CoordinatorAdmissionRequest,
        *,
        service_principal: str | None = None,
    ) -> CoordinatorAdmissionReceipt:
        """Durably bind one accepted operation to the production coordinator."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(request, CoordinatorAdmissionRequest):
            raise AuthorityRepositoryError(
                "request must be a CoordinatorAdmissionRequest"
            )
        if request.run_uri != run_uri:
            raise AuthorityRepositoryError("coordinator admission run_uri conflicts")
        principal = (
            None
            if service_principal is None
            else _non_empty(service_principal, "service_principal")
        )
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            row = conn.execute(
                "SELECT service_principal, request_json, receipt_json "
                "FROM coordinator_admission_receipts "
                "WHERE run_uri = ? AND operation_id = ?",
                (run_uri, request.operation_id),
            ).fetchone()
            if row is not None:
                if row["service_principal"] != principal:
                    raise AuthorityRepositoryError(
                        "coordinator authority principal conflicts with admission"
                    )
                existing = CoordinatorAdmissionRequest.from_dict(
                    _json_loads(cast(str, row["request_json"]))
                )
                if existing != request:
                    raise AuthorityRepositoryError(
                        "coordinator admission operation conflicts"
                    )
                receipt = CoordinatorAdmissionReceipt.from_dict(
                    _json_loads(cast(str, row["receipt_json"]))
                )
                if receipt.request != request:
                    raise AuthorityRepositoryError(
                        "coordinator admission receipt conflicts"
                    )
                return receipt
            binding = conn.execute(
                "SELECT service_principal, request_json "
                "FROM coordinator_admission_receipts "
                "WHERE run_uri = ? LIMIT 1",
                (run_uri,),
            ).fetchone()
            if binding is not None:
                if binding["service_principal"] != principal:
                    raise AuthorityRepositoryError(
                        "coordinator authority principal conflicts with admission"
                    )
                bound = CoordinatorAdmissionRequest.from_dict(
                    _json_loads(cast(str, binding["request_json"]))
                )
                if (
                    bound.coordinator_id != request.coordinator_id
                    or bound.intent_digest != request.intent_digest
                ):
                    raise AuthorityRepositoryError(
                        "coordinator admission owner or intent conflicts"
                    )
                raise AuthorityRepositoryError(
                    "coordinator admission already has an operation"
                )
            receipt = CoordinatorAdmissionReceipt(request=request)
            conn.execute(
                "INSERT INTO coordinator_admission_receipts "
                "(run_uri, operation_id, service_principal, request_json, "
                "receipt_json) VALUES (?, ?, ?, ?, ?)",
                (
                    run_uri,
                    request.operation_id,
                    principal,
                    _json_dumps(request.to_dict()),
                    _json_dumps(receipt.to_dict()),
                ),
            )
            return receipt

    def require_coordinator_principal(
        self, run_uri: str, service_principal: str
    ) -> None:
        """Require the authenticated service that first bound this run."""

        run_uri = _non_empty(run_uri, "run_uri")
        principal = _non_empty(service_principal, "service_principal")
        with self._read_connection() as conn:
            row = conn.execute(
                "SELECT service_principal FROM coordinator_admission_receipts "
                "WHERE run_uri = ? LIMIT 1",
                (run_uri,),
            ).fetchone()
        if row is None:
            raise AuthorityRepositoryError(
                "coordinator operation requires a coordinator admission"
            )
        if row["service_principal"] != principal:
            raise AuthorityRepositoryError(
                "coordinator authority principal conflicts with admission"
            )

    def install_cancellation_epoch(
        self, run_uri: str, request: CancellationEpochRequest
    ) -> CancellationEpochReceipt:
        """Install one authority-owned cancellation epoch before fan-out."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(request, CancellationEpochRequest):
            raise AuthorityRepositoryError(
                "request must be a CancellationEpochRequest"
            )
        if request.run_uri != run_uri:
            raise AuthorityRepositoryError("cancellation epoch run_uri conflicts")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT request_json, receipt_json "
                "FROM cancellation_epoch_receipts "
                "WHERE run_uri = ? AND operation_id = ?",
                (run_uri, request.operation_id),
            ).fetchone()
            if row is not None:
                existing = CancellationEpochRequest.from_dict(
                    _json_loads(cast(str, row["request_json"]))
                )
                if existing != request:
                    raise AuthorityRepositoryError(
                        "cancellation epoch operation conflicts"
                    )
                receipt = CancellationEpochReceipt.from_dict(
                    _json_loads(cast(str, row["receipt_json"]))
                )
                if receipt.request != request:
                    raise AuthorityRepositoryError(
                        "cancellation epoch receipt conflicts"
                    )
                return receipt
            status = RunStatus(cast(str, _require_run_row(conn, run_uri)["status"]))
            if status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
            }:
                raise AuthorityRepositoryError(
                    "terminal run cannot install cancellation"
                )
            binding = conn.execute(
                "SELECT request_json FROM coordinator_admission_receipts "
                "WHERE run_uri = ? LIMIT 1",
                (run_uri,),
            ).fetchone()
            if binding is None:
                raise AuthorityRepositoryError(
                    "cancellation requires a coordinator admission"
                )
            bound = CoordinatorAdmissionRequest.from_dict(
                _json_loads(cast(str, binding["request_json"]))
            )
            if bound.coordinator_id != request.coordinator_id:
                raise AuthorityRepositoryError(
                    "cancellation coordinator conflicts with binding"
                )
            epoch_row = conn.execute(
                "SELECT epoch FROM cancellation_epochs WHERE run_uri = ?",
                (run_uri,),
            ).fetchone()
            if epoch_row is None:
                revision = self._next_revision(conn)
                epoch = f"cancellation-{revision.sequence}-{uuid.uuid4().hex}"
                conn.execute(
                    "INSERT INTO cancellation_epochs (run_uri, epoch) VALUES (?, ?)",
                    (run_uri, epoch),
                )
                _touch_run(conn, run_uri=run_uri, revision=revision)
            else:
                epoch = cast(str, epoch_row["epoch"])
                canonical_row = conn.execute(
                    "SELECT request_json FROM cancellation_epoch_receipts "
                    "WHERE run_uri = ? ORDER BY operation_id LIMIT 1",
                    (run_uri,),
                ).fetchone()
                if canonical_row is None:
                    raise AuthorityRepositoryError(
                        "cancellation epoch has no canonical request"
                    )
                canonical = CancellationEpochRequest.from_dict(
                    _json_loads(cast(str, canonical_row["request_json"]))
                )
                if (
                    canonical.coordinator_id != request.coordinator_id
                    or canonical.run_uri != request.run_uri
                    or canonical.stage_names != request.stage_names
                ):
                    raise AuthorityRepositoryError(
                        "cancellation epoch scope conflicts with its canonical request"
                    )
            receipt = CancellationEpochReceipt(request=request, epoch=epoch)
            conn.execute(
                "INSERT INTO cancellation_epoch_receipts "
                "(run_uri, operation_id, request_json, receipt_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    run_uri,
                    request.operation_id,
                    _json_dumps(request.to_dict()),
                    _json_dumps(receipt.to_dict()),
                ),
            )
            return receipt

    def read_cancellation_epoch_receipt(
        self, run_uri: str, operation_id: str
    ) -> CancellationEpochReceipt | None:
        """Read one durable cancellation receipt."""

        run_uri = _non_empty(run_uri, "run_uri")
        operation_id = _non_empty(operation_id, "operation_id")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            row = conn.execute(
                "SELECT receipt_json FROM cancellation_epoch_receipts "
                "WHERE run_uri = ? AND operation_id = ?",
                (run_uri, operation_id),
            ).fetchone()
        return (
            None
            if row is None
            else CancellationEpochReceipt.from_dict(
                _json_loads(cast(str, row["receipt_json"]))
            )
        )

    def finalize_cancellation(
        self, run_uri: str, request: CancellationEpochRequest
    ) -> RunStatus:
        """Settle unassigned work and atomically CAS the run to CANCELLED."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(request, CancellationEpochRequest):
            raise AuthorityRepositoryError(
                "request must be a CancellationEpochRequest"
            )
        if request.run_uri != run_uri:
            raise AuthorityRepositoryError(
                "cancellation finalization run_uri conflicts"
            )
        with self.transaction() as conn:
            receipt_row = conn.execute(
                "SELECT request_json FROM cancellation_epoch_receipts "
                "WHERE run_uri = ? AND operation_id = ?",
                (run_uri, request.operation_id),
            ).fetchone()
            if receipt_row is None:
                raise AuthorityRepositoryError(
                    "cancellation finalization requires an effective epoch"
                )
            installed = CancellationEpochRequest.from_dict(
                _json_loads(cast(str, receipt_row["request_json"]))
            )
            if installed != request:
                raise AuthorityRepositoryError(
                    "cancellation finalization conflicts"
                )
            status = RunStatus(cast(str, _require_run_row(conn, run_uri)["status"]))
            if status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
            }:
                return status
            live_binding = conn.execute(
                "SELECT 1 FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND state != 'terminal' LIMIT 1",
                (run_uri,),
            ).fetchone()
            if live_binding is not None:
                raise AuthorityRepositoryError(
                    "managed execution binding remains live or unknown"
                )
            stage_names = set(request.stage_names)
            known_stage_names = {
                cast(str, row["stage_name"])
                for row in conn.execute(
                    "SELECT stage_name FROM authority_stages WHERE run_uri = ?",
                    (run_uri,),
                )
            } | {
                cast(str, row["stage_name"])
                for row in conn.execute(
                    "SELECT DISTINCT stage_name FROM stage_attempts "
                    "WHERE run_uri = ?",
                    (run_uri,),
                )
            }
            if not known_stage_names.issubset(stage_names):
                raise AuthorityRepositoryError(
                    "authority work is outside the cancellation stage set"
                )
            active_attempt = conn.execute(
                "SELECT 1 FROM stage_attempts WHERE run_uri = ? "
                "AND status IN (?, ?) LIMIT 1",
                (
                    run_uri,
                    StageStatus.SUBMITTED.value,
                    StageStatus.RUNNING.value,
                ),
            ).fetchone()
            if active_attempt is not None:
                raise AuthorityRepositoryError(
                    "authority execution attempt remains live or unknown"
                )
            active_stage = conn.execute(
                "SELECT 1 FROM authority_stages WHERE run_uri = ? "
                "AND status IN (?, ?) LIMIT 1",
                (
                    run_uri,
                    StageStatus.SUBMITTED.value,
                    StageStatus.RUNNING.value,
                ),
            ).fetchone()
            if active_stage is not None:
                raise AuthorityRepositoryError(
                    "authority stage remains live or unknown"
                )
            try:
                ensure_run_transition(status, RunStatus.CANCELLED)
            except InvalidRunTransition as exc:
                raise AuthorityRepositoryError(str(exc)) from exc
            reason = LifecycleReason(
                code="run.cancelled",
                detail={"operation_id": request.operation_id},
            )
            revision = self._next_revision(conn)
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ?, "
                "reason_json = ? WHERE run_uri = ? AND status = ?",
                (
                    StageStatus.CANCELLED.value,
                    revision.sequence,
                    _json_dumps(reason.to_dict()),
                    run_uri,
                    StageStatus.PENDING.value,
                ),
            )
            terminal_stages = {
                StageStatus.SUCCEEDED,
                StageStatus.FAILED,
                StageStatus.BLOCKED,
                StageStatus.SKIPPED,
                StageStatus.STALE,
                StageStatus.CANCELLED,
            }
            existing_stages = {
                cast(str, row["stage_name"]): StageStatus(cast(str, row["status"]))
                for row in conn.execute(
                    "SELECT stage_name, status FROM authority_stages "
                    "WHERE run_uri = ?",
                    (run_uri,),
                )
            }
            for stage_name in request.stage_names:
                current = existing_stages.get(stage_name)
                if current in terminal_stages:
                    continue
                try:
                    ensure_stage_transition(current, StageStatus.CANCELLED)
                except InvalidStageTransition as exc:
                    raise AuthorityRepositoryError(str(exc)) from exc
                _upsert_stage(
                    conn,
                    run_uri=run_uri,
                    stage_name=stage_name,
                    status=StageStatus.CANCELLED,
                    revision=revision,
                    reason=reason,
                )
            conn.execute(
                "UPDATE authority_runs SET status = ?, "
                "updated_revision_sequence = ?, reason_json = ? "
                "WHERE run_uri = ?",
                (
                    RunStatus.CANCELLED.value,
                    revision.sequence,
                    _json_dumps(reason.to_dict()),
                    run_uri,
                ),
            )
            return RunStatus.CANCELLED

    def bind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        run_uri = _non_empty(run_uri, "run_uri")
        assignment_id = _non_empty(assignment_id, "assignment_id")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        with self.transaction() as conn:
            unbound = conn.execute(
                "SELECT attempt_id FROM managed_attempt_unbind_receipts "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            ).fetchone()
            if unbound is not None:
                if unbound["attempt_id"] != attempt_id:
                    raise AuthorityRepositoryError("assignment binding conflicts")
                return
            row = conn.execute(
                "SELECT attempt_id FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            ).fetchone()
            if row is not None:
                if row["attempt_id"] != attempt_id:
                    raise AuthorityRepositoryError("assignment binding conflicts")
                return
            _require_no_repository_cancellation_epoch(conn, run_uri)
            run_status = RunStatus(
                cast(str, _require_run_row(conn, run_uri)["status"])
            )
            if run_status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
            }:
                raise AuthorityRepositoryError(
                    "terminal run cannot bind prepared work"
                )
            attempt = conn.execute(
                "SELECT stage_name, status FROM stage_attempts "
                "WHERE run_uri = ? AND attempt_id = ?",
                (run_uri, attempt_id),
            ).fetchone()
            if (
                attempt is None
                or StageStatus(cast(str, attempt["status"]))
                is not StageStatus.PENDING
            ):
                raise AuthorityRepositoryError(
                    "only a PENDING prepared attempt may bind"
                )
            receipt_row = conn.execute(
                "SELECT request_json FROM prepared_attempt_receipts "
                "WHERE run_uri = ? AND attempt_id = ?",
                (run_uri, attempt_id),
            ).fetchone()
            if receipt_row is None:
                raise AuthorityRepositoryError("prepared attempt receipt is missing")
            request = PreparedAttemptRequest.from_dict(
                _json_loads(cast(str, receipt_row["request_json"]))
            )
            for upstream_stage, commit_id in request.upstream_commits.items():
                commit = conn.execute(
                    "SELECT commit_id FROM output_commits "
                    "WHERE run_uri = ? AND stage_name = ? "
                    "ORDER BY revision_sequence DESC LIMIT 1",
                    (run_uri, upstream_stage),
                ).fetchone()
                if commit is None or commit["commit_id"] != commit_id:
                    raise AuthorityRepositoryError(
                        "prepared attempt upstream commit evidence is stale"
                    )
            if (
                conn.execute(
                    "SELECT 1 FROM managed_attempt_bindings "
                    "WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, attempt_id),
                ).fetchone()
                is not None
            ):
                raise AuthorityRepositoryError("prepared attempt is already bound")
            conn.execute(
                "INSERT INTO managed_attempt_bindings "
                "(run_uri, assignment_id, attempt_id, state, fence, "
                "terminal_status, terminal_digest) "
                "VALUES (?, ?, ?, 'bound', NULL, NULL, NULL)",
                (run_uri, assignment_id, attempt_id),
            )

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        run_uri = _non_empty(run_uri, "run_uri")
        assignment_id = _non_empty(assignment_id, "assignment_id")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            receipt = conn.execute(
                "SELECT attempt_id FROM managed_attempt_unbind_receipts "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            ).fetchone()
            if receipt is not None:
                if receipt["attempt_id"] != attempt_id:
                    raise AuthorityRepositoryError("assignment unbind conflicts")
                return
            row = conn.execute(
                "SELECT attempt_id, state FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            ).fetchone()
            if (
                row is None
                or row["attempt_id"] != attempt_id
                or row["state"] != "bound"
            ):
                raise AuthorityRepositoryError(
                    "only the same ungranted binding may unbind"
                )
            conn.execute(
                "INSERT INTO managed_attempt_unbind_receipts "
                "(run_uri, assignment_id, attempt_id) VALUES (?, ?, ?)",
                (run_uri, assignment_id, attempt_id),
            )
            conn.execute(
                "DELETE FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            )

    def grant_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> ExecutionFence:
        run_uri = _non_empty(run_uri, "run_uri")
        assignment_id = _non_empty(assignment_id, "assignment_id")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT attempt_id, state, fence FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, assignment_id),
            ).fetchone()
            if row is None or row["attempt_id"] != attempt_id:
                raise AuthorityRepositoryError(
                    "prepared attempt is not bound to assignment"
                )
            if row["state"] in {"granted", "running", "terminal"}:
                return ExecutionFence(
                    assignment_id, attempt_id, cast(str, row["fence"])
                )
            _require_no_repository_cancellation_epoch(conn, run_uri)
            if row["state"] != "bound":
                raise AuthorityRepositoryError(
                    "prepared attempt binding is not grantable"
                )
            attempt = conn.execute(
                "SELECT stage_name, status FROM stage_attempts "
                "WHERE run_uri = ? AND attempt_id = ?",
                (run_uri, attempt_id),
            ).fetchone()
            if (
                attempt is None
                or StageStatus(cast(str, attempt["status"]))
                is not StageStatus.PENDING
            ):
                raise AuthorityRepositoryError(
                    "prepared attempt is no longer pending"
                )
            revision = self._next_revision(conn)
            fence = f"managed-fence-{revision.sequence}-{uuid.uuid4().hex}"
            conn.execute(
                "UPDATE managed_attempt_bindings "
                "SET state = 'granted', fence = ? "
                "WHERE run_uri = ? AND assignment_id = ?",
                (fence, run_uri, assignment_id),
            )
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ? "
                "WHERE run_uri = ? AND attempt_id = ?",
                (
                    StageStatus.SUBMITTED.value,
                    revision.sequence,
                    run_uri,
                    attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=cast(str, attempt["stage_name"]),
                status=StageStatus.SUBMITTED,
                revision=revision,
                reason=None,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return ExecutionFence(assignment_id, attempt_id, fence)

    def confirm_execution_started(
        self, run_uri: str, *, fence: ExecutionFence
    ) -> None:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(fence, ExecutionFence):
            raise AuthorityRepositoryError("execution fence is invalid")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT state FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ? AND attempt_id = ? "
                "AND fence = ?",
                (
                    run_uri,
                    fence.assignment_id,
                    fence.attempt_id,
                    fence.fencing_token,
                ),
            ).fetchone()
            if row is None:
                raise AuthorityRepositoryError("stale execution fence")
            if row["state"] == "running":
                return
            if row["state"] == "terminal":
                terminal = conn.execute(
                    "SELECT reason_json FROM stage_attempts "
                    "WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, fence.attempt_id),
                ).fetchone()
                if terminal is not None and terminal["reason_json"] is not None:
                    terminal_reason = _json_loads(
                        cast(str, terminal["reason_json"])
                    )
                    if (
                        isinstance(terminal_reason, Mapping)
                        and terminal_reason.get("code")
                        == "operator.recovery_close"
                    ):
                        raise AuthorityRepositoryError("stale execution fence")
                return
            _require_no_repository_cancellation_epoch(conn, run_uri)
            if row["state"] != "granted":
                raise AuthorityRepositoryError("execution fence is not granted")
            attempt = conn.execute(
                "SELECT stage_name, status FROM stage_attempts "
                "WHERE run_uri = ? AND attempt_id = ?",
                (run_uri, fence.attempt_id),
            ).fetchone()
            if (
                attempt is None
                or StageStatus(cast(str, attempt["status"]))
                is not StageStatus.SUBMITTED
            ):
                raise AuthorityRepositoryError("attempt is not submitted")
            revision = self._next_revision(conn)
            conn.execute(
                "UPDATE managed_attempt_bindings SET state = 'running' "
                "WHERE run_uri = ? AND assignment_id = ?",
                (run_uri, fence.assignment_id),
            )
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ? "
                "WHERE run_uri = ? AND attempt_id = ?",
                (
                    StageStatus.RUNNING.value,
                    revision.sequence,
                    run_uri,
                    fence.attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=cast(str, attempt["stage_name"]),
                status=StageStatus.RUNNING,
                revision=revision,
                reason=None,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(fence, ExecutionFence):
            raise AuthorityRepositoryError("execution fence is invalid")
        status = StageStatus(status)
        if status not in {StageStatus.FAILED, StageStatus.CANCELLED}:
            raise AuthorityRepositoryError(
                "managed terminal status must be FAILED or CANCELLED"
            )
        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("managed terminal reason is required")
        terminal_digest = _managed_terminal_digest(
            status=status,
            reason=reason,
            outputs={},
        )
        with self.transaction() as conn:
            binding = conn.execute(
                "SELECT state, terminal_status, terminal_digest "
                "FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ? AND attempt_id = ? "
                "AND fence = ?",
                (
                    run_uri,
                    fence.assignment_id,
                    fence.attempt_id,
                    fence.fencing_token,
                ),
            ).fetchone()
            if binding is None:
                raise AuthorityRepositoryError("stale execution fence")
            attempt = _require_row(
                conn.execute(
                    "SELECT stage_name, status, revision_sequence "
                    "FROM stage_attempts WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, fence.attempt_id),
                ).fetchone(),
                "unknown stage attempt",
            )
            stage_name = cast(str, attempt["stage_name"])
            current = StageStatus(cast(str, attempt["status"]))
            if binding["state"] == "terminal":
                if (
                    binding["terminal_status"] != status.value
                    or binding["terminal_digest"] != terminal_digest
                ):
                    raise AuthorityRepositoryError(
                        "managed terminal result conflicts"
                    )
                return StatusTransition(
                    run_uri=run_uri,
                    stage_name=stage_name,
                    previous_status=status,
                    status=status,
                    revision=_revision_for(
                        conn, cast(int, attempt["revision_sequence"])
                    ),
                    reason=reason,
                )
            if binding["state"] not in {"granted", "running"}:
                raise AuthorityRepositoryError(
                    "execution fence is not terminal-writable"
                )
            if current not in {StageStatus.SUBMITTED, StageStatus.RUNNING}:
                raise AuthorityRepositoryError("attempt is not execution-active")
            try:
                ensure_stage_transition(current, status)
            except InvalidStageTransition as exc:
                raise AuthorityRepositoryError(str(exc)) from exc
            revision = self._next_revision(conn)
            conn.execute(
                "UPDATE managed_attempt_bindings "
                "SET state = 'terminal', terminal_status = ?, terminal_digest = ? "
                "WHERE run_uri = ? AND assignment_id = ?",
                (
                    status.value,
                    terminal_digest,
                    run_uri,
                    fence.assignment_id,
                ),
            )
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ?, "
                "reason_json = ? WHERE run_uri = ? AND attempt_id = ?",
                (
                    status.value,
                    revision.sequence,
                    _json_dumps(reason.to_dict()),
                    run_uri,
                    fence.attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=status,
                revision=revision,
                reason=reason,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return StatusTransition(
                run_uri=run_uri,
                stage_name=stage_name,
                previous_status=current,
                status=status,
                revision=revision,
                reason=reason,
            )

    def close_managed_attempt_fence(
        self,
        run_uri: str,
        *,
        recovery_id: str,
        fence: ExecutionFence,
        expected_state_version: int,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        """Arbitrate guarded recovery close against ordinary terminal truth."""

        run_uri = _non_empty(run_uri, "run_uri")
        recovery_id = _non_empty(recovery_id, "recovery_id")
        if not isinstance(fence, ExecutionFence):
            raise AuthorityRepositoryError("execution fence is invalid")
        if isinstance(expected_state_version, bool) or expected_state_version < 0:
            raise AuthorityRepositoryError(
                "recovery expected state version is invalid"
            )
        status = StageStatus(status)
        if status not in {StageStatus.FAILED, StageStatus.CANCELLED}:
            raise AuthorityRepositoryError(
                "recovery close status must be FAILED or CANCELLED"
            )
        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("recovery close reason is required")
        with self.transaction() as conn:
            binding = conn.execute(
                "SELECT state, terminal_status, terminal_digest "
                "FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ? AND attempt_id = ? "
                "AND fence = ?",
                (
                    run_uri,
                    fence.assignment_id,
                    fence.attempt_id,
                    fence.fencing_token,
                ),
            ).fetchone()
            if binding is None:
                raise AuthorityRepositoryError("stale execution fence")
            attempt = _require_row(
                conn.execute(
                    "SELECT stage_name, status, revision_sequence, reason_json "
                    "FROM stage_attempts WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, fence.attempt_id),
                ).fetchone(),
                "unknown stage attempt",
            )
            stage_name = cast(str, attempt["stage_name"])
            current = StageStatus(cast(str, attempt["status"]))
            if binding["state"] == "terminal":
                reason_json = attempt["reason_json"]
                prior_reason = (
                    None
                    if reason_json is None
                    else _json_loads(cast(str, reason_json))
                )
                if (
                    isinstance(prior_reason, Mapping)
                    and isinstance(prior_reason.get("detail"), Mapping)
                    and prior_reason["detail"].get("recovery_id") == recovery_id
                ):
                    resolved_reason = LifecycleReason.from_dict(prior_reason)
                    expected_reason = LifecycleReason(
                        code=reason.code,
                        message=reason.message,
                        detail={**reason.detail, "recovery_id": recovery_id},
                    )
                    if current is not status or resolved_reason != expected_reason:
                        raise AuthorityRepositoryError(
                            "recovery close replay conflicts"
                        )
                    return StatusTransition(
                        run_uri=run_uri,
                        stage_name=stage_name,
                        previous_status=current,
                        status=current,
                        revision=_revision_for(
                            conn, cast(int, attempt["revision_sequence"])
                        ),
                        reason=resolved_reason,
                    )
                raise AuthorityRepositoryError(
                    "ordinary terminal fact supersedes recovery"
                )
            if int(attempt["revision_sequence"]) != expected_state_version:
                raise AuthorityRepositoryError(
                    "recovery expected state version is stale"
                )
            if binding["state"] not in {"granted", "running"} or current not in {
                StageStatus.SUBMITTED,
                StageStatus.RUNNING,
            }:
                raise AuthorityRepositoryError(
                    "execution fence is not recovery-closable"
                )
            try:
                ensure_stage_transition(current, status)
            except InvalidStageTransition as exc:
                raise AuthorityRepositoryError(str(exc)) from exc
            revision = self._next_revision(conn)
            terminal_reason = LifecycleReason(
                code=reason.code,
                message=reason.message,
                detail={**reason.detail, "recovery_id": recovery_id},
            )
            terminal_digest = _managed_terminal_digest(
                status=status,
                reason=terminal_reason,
                outputs={},
            )
            conn.execute(
                "UPDATE managed_attempt_bindings "
                "SET state = 'terminal', terminal_status = ?, terminal_digest = ? "
                "WHERE run_uri = ? AND assignment_id = ?",
                (
                    status.value,
                    terminal_digest,
                    run_uri,
                    fence.assignment_id,
                ),
            )
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ?, "
                "reason_json = ? WHERE run_uri = ? AND attempt_id = ?",
                (
                    status.value,
                    revision.sequence,
                    _json_dumps(terminal_reason.to_dict()),
                    run_uri,
                    fence.attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=status,
                revision=revision,
                reason=terminal_reason,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return StatusTransition(
                run_uri=run_uri,
                stage_name=stage_name,
                previous_status=current,
                status=status,
                revision=revision,
                reason=terminal_reason,
            )

    def renew_stage_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
    ) -> LeaseRecord:
        """Renew an active stage lease after owner, fence, and TTL checks."""

        run_uri = _non_empty(run_uri, "run_uri")
        lease_ttl_seconds = _positive_seconds(lease_ttl_seconds)
        with self.transaction() as conn:
            row = _require_active_stage_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityRepositoryError("stage lease has expired")
            revision = self._next_revision(conn)
            expires_at = _add_seconds(now, lease_ttl_seconds)
            conn.execute(
                """
                UPDATE stage_leases
                SET renewed_at = ?, expires_at = ?, revision_sequence = ?
                WHERE lease_id = ?
                """,
                (now, expires_at, revision.sequence, lease_id),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return _stage_lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM stage_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone(),
                    "unknown stage lease",
                ),
                revision=revision,
            )

    def release_stage_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        """Mark an active stage lease released."""

        return self._finish_stage_lease(
            run_uri,
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            state=LeaseState.RELEASED,
            reason=reason,
        )

    def fail_stage_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
        expected_revision: BackendRevision | None = None,
    ) -> LeaseRecord:
        """Mark an active stage lease failed."""

        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason")
        return self._finish_stage_lease(
            run_uri,
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            state=LeaseState.FAILED,
            reason=reason,
        )

    def finish_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        owner_id: str,
        fencing_token: str,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
        service_generation: str | None = None,
        reason: LifecycleReason | None = None,
    ) -> StageAttempt:
        """Record a terminal non-output stage attempt state."""

        run_uri = _non_empty(run_uri, "run_uri")
        stage_name = _non_empty(stage_name, "stage_name")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        to_status = StageStatus(to_status)
        if to_status not in _ATTEMPT_TERMINAL_STATUSES:
            raise AuthorityRepositoryError("attempt terminal status is required")
        if to_status is StageStatus.SUCCEEDED:
            raise AuthorityRepositoryError(
                "terminal success requires record_output_commit"
            )
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            _require_service_generation(conn, service_generation)
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            lease_row = _require_active_stage_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=_stage_lease_id_for_attempt(conn, run_uri, attempt_id),
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            now = self._now()
            if _timestamp_expired(cast(str, lease_row["expires_at"]), now):
                raise AuthorityRepositoryError("stage lease has expired")
            attempt_row = _require_stage_attempt_row(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
            )
            if StageStatus(cast(str, attempt_row["status"])) not in {
                StageStatus.RUNNING,
                StageStatus.SUBMITTED,
            }:
                raise AuthorityRepositoryError("stage attempt is already terminal")
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE stage_attempts
                SET status = ?, revision_sequence = ?, reason_json = ?
                WHERE run_uri = ? AND attempt_id = ?
                """,
                (
                    to_status.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    run_uri,
                    attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=to_status,
                revision=revision,
                reason=reason,
            )
            conn.execute(
                """
                UPDATE stage_leases
                SET state = ?, revision_sequence = ?, reason_json = ?
                WHERE lease_id = ?
                """,
                (
                    LeaseState.RELEASED.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    cast(str, lease_row["lease_id"]),
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return _attempt_from_row(
                _require_stage_attempt_row(
                    conn,
                    run_uri=run_uri,
                    stage_name=stage_name,
                    attempt_id=attempt_id,
                ),
                conn=conn,
            )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        owner_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        expected_revision: BackendRevision | None = None,
        service_generation: str | None = None,
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        """Persist a fenced stage output commit and artifact facts."""

        run_uri = _non_empty(run_uri, "run_uri")
        stage_name = _non_empty(stage_name, "stage_name")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        owner_id = _non_empty(owner_id, "owner_id")
        fencing_token = _non_empty(fencing_token, "fencing_token")
        if supersedes_commit_id is not None:
            supersedes_commit_id = _non_empty(
                supersedes_commit_id, "supersedes_commit_id"
            )
        artifacts = tuple((name, artifact) for name, artifact in outputs.items())
        for name, artifact in artifacts:
            _non_empty(name, "output_name")
            if not isinstance(artifact, ArtifactRef):
                raise AuthorityRepositoryError(
                    "outputs must contain ArtifactRef values"
                )
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            _require_service_generation(conn, service_generation)
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            lease_row = _require_active_stage_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=_stage_lease_id_for_attempt(conn, run_uri, attempt_id),
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            now = self._now()
            if _timestamp_expired(cast(str, lease_row["expires_at"]), now):
                raise AuthorityRepositoryError("stage lease has expired")
            attempt_row = _require_stage_attempt_row(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
            )
            if StageStatus(cast(str, attempt_row["status"])) not in {
                StageStatus.RUNNING,
                StageStatus.SUBMITTED,
            }:
                raise AuthorityRepositoryError("stage attempt is not running")
            stage_row = conn.execute(
                """
                SELECT status
                FROM authority_stages
                WHERE run_uri = ? AND stage_name = ?
                """,
                (run_uri, stage_name),
            ).fetchone()
            if stage_row is None or StageStatus(cast(str, stage_row["status"])) not in {
                StageStatus.RUNNING,
                StageStatus.SUBMITTED,
            }:
                raise AuthorityRepositoryError("stage is not running")
            existing_commit = conn.execute(
                """
                SELECT commit_id
                FROM output_commits
                WHERE run_uri = ? AND stage_name = ?
                ORDER BY revision_sequence DESC
                LIMIT 1
                """,
                (run_uri, stage_name),
            ).fetchone()
            current_commit_id = (
                None
                if existing_commit is None
                else cast(str, existing_commit["commit_id"])
            )
            if current_commit_id is None and supersedes_commit_id is not None:
                raise AuthorityRepositoryError(
                    "initial output commit cannot supersede another commit"
                )
            if current_commit_id is not None:
                if supersedes_commit_id is None:
                    raise AuthorityRepositoryError(
                        "replacement output commit must name its predecessor"
                    )
                if supersedes_commit_id != current_commit_id:
                    raise AuthorityRepositoryError("stale output commit predecessor")
            revision = self._next_revision(conn)
            commit_id = f"{stage_name}-{attempt_id}-commit-{revision.sequence}"
            output_names = tuple(name for name, _artifact in artifacts)
            conn.execute(
                """
                INSERT INTO output_commits (
                    commit_id, run_uri, stage_name, attempt_id, committed_at,
                    revision_sequence, output_names_json, materialized_refs_json,
                    supersedes_commit_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit_id,
                    run_uri,
                    stage_name,
                    attempt_id,
                    now,
                    revision.sequence,
                    _json_dumps(list(output_names)),
                    _json_dumps([]),
                    supersedes_commit_id,
                ),
            )
            for name, artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO artifact_facts (
                        run_uri, stage_name, artifact_name, artifact_json,
                        commit_id, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_uri,
                        stage_name,
                        name,
                        _json_dumps(artifact.to_dict()),
                        commit_id,
                        revision.sequence,
                    ),
                )
            conn.execute(
                """
                UPDATE stage_attempts
                SET status = ?, revision_sequence = ?, reason_json = ?
                WHERE run_uri = ? AND attempt_id = ?
                """,
                (
                    StageStatus.SUCCEEDED.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    run_uri,
                    attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=StageStatus.SUCCEEDED,
                revision=revision,
                reason=reason,
            )
            conn.execute(
                """
                UPDATE stage_leases
                SET state = ?, revision_sequence = ?, reason_json = ?
                WHERE lease_id = ?
                """,
                (
                    LeaseState.RELEASED.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    cast(str, lease_row["lease_id"]),
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            commit = OutputCommitRecord(
                commit_id=commit_id,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
                committed_at=now,
                revision=revision,
                output_names=output_names,
                supersedes_commit_id=supersedes_commit_id,
            )
            facts = tuple(
                ArtifactFactRecord(
                    artifact_name=name,
                    artifact=artifact,
                    commit_id=commit_id,
                    revision=revision,
                )
                for name, artifact in artifacts
            )
            return OutputCommit(commit=commit, artifact_facts=facts)

    def record_managed_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        assignment_id: str,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        """Persist an output commit through one managed execution fence."""

        run_uri = _non_empty(run_uri, "run_uri")
        stage_name = _non_empty(stage_name, "stage_name")
        assignment_id = _non_empty(assignment_id, "assignment_id")
        attempt_id = _non_empty(attempt_id, "attempt_id")
        fencing_token = _non_empty(fencing_token, "fencing_token")
        if supersedes_commit_id is not None:
            supersedes_commit_id = _non_empty(
                supersedes_commit_id, "supersedes_commit_id"
            )
        artifacts = tuple(outputs.items())
        for name, artifact in artifacts:
            _non_empty(name, "output_name")
            if not isinstance(artifact, ArtifactRef):
                raise AuthorityRepositoryError(
                    "outputs must contain ArtifactRef values"
                )
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError(
                "reason must be a LifecycleReason or None"
            )
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            now = self._now()
            managed = conn.execute(
                "SELECT state, terminal_status, terminal_digest "
                "FROM managed_attempt_bindings "
                "WHERE run_uri = ? AND assignment_id = ? AND attempt_id = ? "
                "AND fence = ?",
                (run_uri, assignment_id, attempt_id, fencing_token),
            ).fetchone()
            if managed is None:
                raise AuthorityRepositoryError("stale execution fence")
            if managed["state"] == "terminal":
                existing = conn.execute(
                    "SELECT * FROM output_commits "
                    "WHERE run_uri = ? AND attempt_id = ?",
                    (run_uri, attempt_id),
                ).fetchone()
                if existing is None:
                    raise AuthorityRepositoryError(
                        "managed terminal binding has no output commit"
                    )
                commit = _commit_from_row(existing, conn=conn)
                facts = tuple(
                    _artifact_fact_from_row(row, conn=conn)
                    for row in conn.execute(
                        "SELECT * FROM artifact_facts "
                        "WHERE run_uri = ? AND commit_id = ? "
                        "ORDER BY artifact_name",
                        (run_uri, commit.commit_id),
                    )
                )
                replay = OutputCommit(commit=commit, artifact_facts=facts)
                replay_digest = _managed_terminal_digest(
                    status=StageStatus.SUCCEEDED,
                    reason=reason,
                    outputs=outputs,
                )
                if (
                    managed["terminal_status"] != StageStatus.SUCCEEDED.value
                    or managed["terminal_digest"] != replay_digest
                    or replay.commit.stage_name != stage_name
                    or dict(outputs)
                    != {
                        fact.artifact_name: fact.artifact
                        for fact in replay.artifact_facts
                    }
                    or replay.commit.supersedes_commit_id != supersedes_commit_id
                ):
                    raise AuthorityRepositoryError(
                        "managed output result conflicts"
                    )
                return replay
            if managed["state"] not in {"granted", "running"}:
                raise AuthorityRepositoryError(
                    "execution fence is not output-writable"
                )

            attempt_row = conn.execute(
                "SELECT * FROM stage_attempts "
                "WHERE run_uri = ? AND attempt_id = ? AND stage_name = ?",
                (run_uri, attempt_id, stage_name),
            ).fetchone()
            if attempt_row is None:
                raise AuthorityRepositoryError("unknown stage attempt")
            if StageStatus(cast(str, attempt_row["status"])) not in {
                StageStatus.SUBMITTED,
                StageStatus.RUNNING,
            }:
                raise AuthorityRepositoryError("stage attempt is not running")
            stage_row = conn.execute(
                "SELECT status FROM authority_stages "
                "WHERE run_uri = ? AND stage_name = ?",
                (run_uri, stage_name),
            ).fetchone()
            if stage_row is None or StageStatus(cast(str, stage_row["status"])) not in {
                StageStatus.RUNNING,
                StageStatus.SUBMITTED,
            }:
                raise AuthorityRepositoryError("stage is not running")
            existing_commit = conn.execute(
                "SELECT * FROM output_commits "
                "WHERE run_uri = ? AND stage_name = ? "
                "ORDER BY revision_sequence DESC LIMIT 1",
                (run_uri, stage_name),
            ).fetchone()
            if existing_commit is None:
                if supersedes_commit_id is not None:
                    raise AuthorityRepositoryError(
                        "output commit has no current predecessor"
                    )
            elif supersedes_commit_id != cast(str, existing_commit["commit_id"]):
                raise AuthorityRepositoryError(
                    "stale or missing output commit current head"
                )
            revision = self._next_revision(conn)
            commit_id = f"{stage_name}-{attempt_id}-commit-{revision.sequence}"
            output_names = tuple(name for name, _artifact in artifacts)
            conn.execute(
                """
                INSERT INTO output_commits (
                    commit_id, run_uri, stage_name, attempt_id, committed_at,
                    revision_sequence, output_names_json, materialized_refs_json,
                    supersedes_commit_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit_id,
                    run_uri,
                    stage_name,
                    attempt_id,
                    now,
                    revision.sequence,
                    _json_dumps(list(output_names)),
                    _json_dumps([]),
                    supersedes_commit_id,
                ),
            )
            for name, artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO artifact_facts (
                        run_uri, stage_name, artifact_name, artifact_json,
                        commit_id, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_uri,
                        stage_name,
                        name,
                        _json_dumps(artifact.to_dict()),
                        commit_id,
                        revision.sequence,
                    ),
                )
            conn.execute(
                "UPDATE stage_attempts SET status = ?, revision_sequence = ?, "
                "reason_json = ? WHERE run_uri = ? AND attempt_id = ?",
                (
                    StageStatus.SUCCEEDED.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    run_uri,
                    attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                run_uri=run_uri,
                stage_name=stage_name,
                status=StageStatus.SUCCEEDED,
                revision=revision,
                reason=reason,
            )
            terminal_digest = _managed_terminal_digest(
                status=StageStatus.SUCCEEDED,
                reason=reason,
                outputs=dict(outputs),
            )
            conn.execute(
                "UPDATE managed_attempt_bindings SET state = 'terminal', "
                "terminal_status = ?, terminal_digest = ? "
                "WHERE run_uri = ? AND assignment_id = ?",
                (
                    StageStatus.SUCCEEDED.value,
                    terminal_digest,
                    run_uri,
                    assignment_id,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            commit = OutputCommitRecord(
                commit_id=commit_id,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
                committed_at=now,
                revision=revision,
                output_names=output_names,
                supersedes_commit_id=supersedes_commit_id,
            )
            facts = tuple(
                ArtifactFactRecord(
                    artifact_name=name,
                    artifact=artifact,
                    commit_id=commit_id,
                    revision=revision,
                )
                for name, artifact in artifacts
            )
            return OutputCommit(commit=commit, artifact_facts=facts)

    def list_output_commits(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[OutputCommit, ...]:
        """Return append-only output commits with their own artifact facts."""

        run_uri = _non_empty(run_uri, "run_uri")
        if stage_name is not None:
            stage_name = _non_empty(stage_name, "stage_name")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            query = "SELECT * FROM output_commits WHERE run_uri = ?"
            values: tuple[object, ...] = (run_uri,)
            if stage_name is not None:
                query += " AND stage_name = ?"
                values = (run_uri, stage_name)
            rows = conn.execute(
                query + " ORDER BY revision_sequence", values
            ).fetchall()
            return tuple(
                OutputCommit(
                    commit=_commit_from_row(row, conn=conn),
                    artifact_facts=tuple(
                        _artifact_fact_from_row(fact, conn=conn)
                        for fact in conn.execute(
                            """
                            SELECT * FROM artifact_facts
                            WHERE commit_id = ?
                            ORDER BY artifact_name
                            """,
                            (row["commit_id"],),
                        )
                    ),
                )
                for row in rows
            )

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
    ) -> LeaseRecord:
        """Acquire the single active controller lease for a run."""

        run_uri = _non_empty(run_uri, "run_uri")
        owner_id = _non_empty(owner_id, "owner_id")
        lease_ttl_seconds = _positive_seconds(lease_ttl_seconds)
        with self.transaction() as conn:
            row = _require_run_row(conn, run_uri)
            _require_expected_revision(
                _revision_for(conn, cast(int, row["updated_revision_sequence"])),
                expected_revision,
            )
            now = self._now()
            active = _active_controller_lease_row(conn, run_uri=run_uri, now=now)
            if active is not None:
                raise AuthorityRepositoryError(
                    "run already has an active controller lease"
                )
            revision = self._next_revision(conn)
            lease = _insert_controller_lease(
                conn,
                run_uri=run_uri,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                revision=revision,
                now=now,
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return lease

    def renew_controller_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
    ) -> LeaseRecord:
        """Renew an active controller lease after owner, fence, and TTL checks."""

        run_uri = _non_empty(run_uri, "run_uri")
        lease_ttl_seconds = _positive_seconds(lease_ttl_seconds)
        with self.transaction() as conn:
            row = _require_active_controller_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityRepositoryError("controller lease has expired")
            revision = self._next_revision(conn)
            expires_at = _add_seconds(now, lease_ttl_seconds)
            conn.execute(
                """
                UPDATE controller_leases
                SET renewed_at = ?, expires_at = ?, revision_sequence = ?
                WHERE lease_id = ?
                """,
                (now, expires_at, revision.sequence, lease_id),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return _controller_lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM controller_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone(),
                    "unknown controller lease",
                ),
                revision=revision,
            )

    def release_controller_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        """Mark an active controller lease released."""

        return self._finish_controller_lease(
            run_uri,
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            state=LeaseState.RELEASED,
            reason=reason,
        )

    def fail_controller_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
        expected_revision: BackendRevision | None = None,
    ) -> LeaseRecord:
        """Mark an active controller lease failed."""

        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason")
        return self._finish_controller_lease(
            run_uri,
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            state=LeaseState.FAILED,
            reason=reason,
        )

    def write_submitted_operation(
        self,
        run_uri: str,
        record: SubmittedOperationRecord,
        *,
        expected_revision: BackendRevision | None = None,
    ) -> BackendRevision:
        """Persist a submitted operation summary for a run."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(record, SubmittedOperationRecord):
            raise AuthorityRepositoryError("record must be a SubmittedOperationRecord")
        with self.transaction() as conn:
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            revision = self._next_revision(conn)
            data = record.to_dict()
            data["run_uri"] = run_uri
            conn.execute(
                """
                INSERT INTO submitted_operations (
                    run_uri, submission_id, record_json, revision_sequence
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_uri, submission_id) DO UPDATE SET
                    record_json = excluded.record_json,
                    revision_sequence = excluded.revision_sequence
                """,
                (
                    run_uri,
                    record.submission_id,
                    _json_dumps(data),
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return revision

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        """Read one submitted operation summary by ID."""

        run_uri = _non_empty(run_uri, "run_uri")
        submission_id = _non_empty(submission_id, "submission_id")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            row = conn.execute(
                """
                SELECT record_json
                FROM submitted_operations
                WHERE run_uri = ? AND submission_id = ?
                """,
                (run_uri, submission_id),
            ).fetchone()
            if row is None:
                return None
            return _submitted_from_json(cast(str, row["record_json"]), run_uri)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        """List submitted operation summaries for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _submitted_operations(conn, run_uri)

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(fact, ReliabilityPolicyFact):
            raise AuthorityRepositoryError("fact must be a ReliabilityPolicyFact")
        validate_policy_fact_run(fact, run_uri)
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            key = reliability_policy_fact_key(fact)
            return self._insert_reliability_fact(
                conn,
                run_uri=run_uri,
                table="reliability_policy_facts",
                key_column="fact_key",
                key=key,
                payload_column="fact_json",
                payload=fact.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_policy_facts (
                        run_uri, fact_key, scope, stage_name, attempt_number,
                        recorded_at, fact_json, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
                    run_uri,
                    key,
                    fact.scope.value,
                    fact.stage_name,
                    fact.attempt,
                    fact.recorded_at,
                    _json_dumps(fact.to_dict()),
                ),
            )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            if stage_name is None:
                rows = conn.execute(
                    """
                    SELECT fact_json FROM reliability_policy_facts
                    WHERE run_uri = ?
                    ORDER BY scope, COALESCE(stage_name, ''),
                        COALESCE(attempt_number, 0), recorded_at
                    """,
                    (run_uri,),
                ).fetchall()
            else:
                stage_name = _non_empty(stage_name, "stage_name")
                rows = conn.execute(
                    """
                    SELECT fact_json FROM reliability_policy_facts
                    WHERE run_uri = ? AND stage_name = ?
                    ORDER BY scope, COALESCE(attempt_number, 0), recorded_at
                    """,
                    (run_uri, stage_name),
                ).fetchall()
            return tuple(
                ReliabilityPolicyFact.from_dict(
                    _json_loads(cast(str, row["fact_json"]))
                )
                for row in rows
            )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(detail, ReliabilityStatusDetail):
            raise AuthorityRepositoryError(
                "detail must be a ReliabilityStatusDetail"
            )
        validate_status_detail_run(detail, run_uri)
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            key = reliability_status_detail_key(detail)
            return self._insert_reliability_fact(
                conn,
                run_uri=run_uri,
                table="reliability_status_details",
                key_column="fact_key",
                key=key,
                payload_column="detail_json",
                payload=detail.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_status_details (
                        run_uri, fact_key, stage_name, attempt_number,
                        created_at, detail_json, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
                    run_uri,
                    key,
                    detail.stage_id,
                    detail.attempt,
                    detail.created_at,
                    _json_dumps(detail.to_dict()),
                ),
            )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            table="reliability_status_details",
            payload_column="detail_json",
            parser=ReliabilityStatusDetail.from_dict,
            stage_name=stage_name,
            order_by="stage_name, attempt_number, created_at",
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(transaction, StageAttemptTransaction):
            raise AuthorityRepositoryError(
                "transaction must be a StageAttemptTransaction"
            )
        validate_transaction_run(transaction, run_uri)
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            return self._insert_reliability_fact(
                conn,
                run_uri=run_uri,
                table="reliability_transactions",
                key_column="transaction_id",
                key=transaction.transaction_id,
                payload_column="record_json",
                payload=transaction.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_transactions (
                        run_uri, transaction_id, stage_name, attempt_number,
                        causal_parent_id, record_json, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
                    run_uri,
                    transaction.transaction_id,
                    transaction.stage_id,
                    transaction.attempt,
                    transaction.causal_parent_id,
                    _json_dumps(transaction.to_dict()),
                ),
            )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        transaction_id = _non_empty(transaction_id, "transaction_id")
        transactions = {
            transaction.transaction_id: transaction
            for transaction in self.list_stage_attempt_transactions(run_uri)
        }
        current = transactions.get(transaction_id)
        if current is None:
            return ()
        chain: list[StageAttemptTransaction] = []
        seen: set[str] = set()
        while current is not None:
            if current.transaction_id in seen:
                raise AuthorityRepositoryError(
                    "reliability transaction chain contains a cycle"
                )
            seen.add(current.transaction_id)
            chain.append(current)
            parent_id = current.causal_parent_id
            current = None if parent_id is None else transactions.get(parent_id)
        return tuple(reversed(chain))

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            table="reliability_transactions",
            payload_column="record_json",
            parser=StageAttemptTransaction.from_dict,
            stage_name=stage_name,
            order_by="stage_name, attempt_number, transaction_id",
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(decision, RetryDecisionRecord):
            raise AuthorityRepositoryError(
                "decision must be a RetryDecisionRecord"
            )
        validate_retry_decision_run(decision, run_uri)
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            return self._insert_reliability_fact(
                conn,
                run_uri=run_uri,
                table="retry_decisions",
                key_column="decision_id",
                key=decision.decision_id,
                payload_column="record_json",
                payload=decision.to_dict(),
                insert_sql="""
                    INSERT INTO retry_decisions (
                        run_uri, decision_id, transaction_id, stage_name,
                        attempt_number, record_json, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
                    run_uri,
                    decision.decision_id,
                    decision.transaction_id,
                    decision.status.stage_id,
                    decision.status.attempt,
                    _json_dumps(decision.to_dict()),
                ),
            )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            table="retry_decisions",
            payload_column="record_json",
            parser=RetryDecisionRecord.from_dict,
            stage_name=stage_name,
            order_by="stage_name, attempt_number, decision_id",
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(outcome, TimeoutOutcomeRecord):
            raise AuthorityRepositoryError(
                "outcome must be a TimeoutOutcomeRecord"
            )
        validate_timeout_outcome_run(outcome, run_uri)
        with self.transaction() as conn:
            _require_run_row(conn, run_uri)
            return self._insert_reliability_fact(
                conn,
                run_uri=run_uri,
                table="timeout_outcomes",
                key_column="outcome_id",
                key=outcome.outcome_id,
                payload_column="record_json",
                payload=outcome.to_dict(),
                insert_sql="""
                    INSERT INTO timeout_outcomes (
                        run_uri, outcome_id, transaction_id, stage_name,
                        attempt_number, record_json, revision_sequence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
                    run_uri,
                    outcome.outcome_id,
                    outcome.transaction_id,
                    outcome.status.stage_id,
                    outcome.status.attempt,
                    _json_dumps(outcome.to_dict()),
                ),
            )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            table="timeout_outcomes",
            payload_column="record_json",
            parser=TimeoutOutcomeRecord.from_dict,
            stage_name=stage_name,
            order_by="stage_name, attempt_number, outcome_id",
        )

    def append_audit_event(
        self,
        run_uri: str,
        event: PipelineEvent,
        *,
        expected_revision: BackendRevision | None = None,
    ) -> PipelineEventRecord:
        """Append a run audit event and advance the run revision."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(event, PipelineEvent):
            raise AuthorityRepositoryError("event must be a PipelineEvent")
        with self.transaction() as conn:
            _ensure_audit_event_json_column(conn)
            current = _current_run_revision(conn, run_uri)
            for row in conn.execute(
                "SELECT * FROM audit_events WHERE run_uri = ? ORDER BY sequence",
                (run_uri,),
            ):
                existing = _audit_event_from_row(row, run_uri=run_uri)
                if existing.event_id == event.event_id:
                    if not _event_matches_record(event, existing):
                        raise AuthorityRepositoryError(
                            f"event_id {event.event_id!r} conflicts with an existing event"
                        )
                    return existing
            _require_expected_revision(current, expected_revision)
            revision = self._next_revision(conn)
            timestamp = event.timestamp or self._now()
            payload = cast(
                Mapping[str, PlainData],
                thaw_plain_data(event.payload, path="event.payload"),
            )
            sequence = _next_audit_event_sequence(conn, run_uri=run_uri)
            record = PipelineEventRecord(
                run_uri=run_uri,
                sequence=sequence,
                timestamp=timestamp,
                scope=event.scope,
                event_type=event.event_type,
                payload=payload,
                event_id=event.event_id,
            )
            conn.execute(
                """
                INSERT INTO audit_events (
                    run_uri, sequence, timestamp, scope_json, event_type, payload_json,
                    event_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_uri,
                    sequence,
                    timestamp,
                    _json_dumps(event.scope.to_dict()),
                    event.event_type,
                    _json_dumps(payload),
                    _json_dumps(record.to_dict()),
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return record

    def list_audit_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]:
        """List persisted audit events for a run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return tuple(
                _audit_event_from_row(row, run_uri=run_uri)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM audit_events
                    WHERE run_uri = ?
                    ORDER BY sequence
                    """,
                    (run_uri,),
                )
            )

    def import_offline_evidence_manifest(
        self,
        manifest: OfflineEvidenceManifest,
        *,
        imported_by: str = "offline-import",
        workspace_id: str | None = None,
    ) -> AuthoritativeRunSnapshot:
        """Atomically import accepted v10 offline evidence into authority truth."""

        if not isinstance(manifest, OfflineEvidenceManifest):
            raise AuthorityRepositoryError(
                "manifest must be an OfflineEvidenceManifest"
            )
        imported_by = _non_empty(imported_by, "imported_by")
        if workspace_id is not None:
            workspace_id = _non_empty(workspace_id, "workspace_id")
        run_uri = _non_empty(manifest.run_uri, "run_uri")
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT 1 FROM authority_runs WHERE run_uri = ?",
                (run_uri,),
            ).fetchone()
            if existing is not None:
                raise AuthorityRepositoryError(f"run already exists: {run_uri}")
            now = self._now()
            import_provenance = _offline_import_provenance(
                manifest,
                imported_at=now,
                imported_by=imported_by,
                workspace_id=workspace_id,
            )
            run_status = _offline_import_run_status(manifest)
            run_metadata = dict(
                _plain_mapping(run_status.get("metadata", {}), "metadata")
            )
            run_metadata["authority_import"] = import_provenance
            run_revision = self._next_revision(conn)
            conn.execute(
                """
                INSERT INTO authority_runs (
                    run_uri, status, metadata_json, created_revision_sequence,
                    updated_revision_sequence, reason_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_uri,
                    RunStatus(cast(str, run_status["status"])).value,
                    _json_dumps(run_metadata),
                    run_revision.sequence,
                    run_revision.sequence,
                    _json_dumps(_offline_import_reason(import_provenance).to_dict()),
                ),
            )
            _insert_import_audit_event(
                conn,
                run_uri=run_uri,
                event_type="offline_import.accepted",
                timestamp=now,
                payload={
                    "import_provenance": import_provenance,
                    "stage_count": len(manifest.stages),
                    "artifact_count": sum(
                        len(stage.artifacts) for stage in manifest.stages
                    ),
                },
                revision=run_revision,
            )
            latest_revision = run_revision
            for stage in manifest.stages:
                latest_revision = self._import_offline_stage(
                    conn,
                    manifest=manifest,
                    stage=stage,
                    import_provenance=import_provenance,
                )
            for event in manifest.events:
                latest_revision = self._next_revision(conn)
                record = PipelineEventRecord.from_dict(event)
                _insert_import_audit_event(
                    conn,
                    run_uri=run_uri,
                    event_type=f"offline_import.replay.{record.event_type}",
                    timestamp=record.timestamp,
                    payload={"offline_event": record.to_dict()},
                    revision=latest_revision,
                    scope=record.scope,
                )
            _touch_run(conn, run_uri=run_uri, revision=latest_revision)
            return _run_snapshot(
                conn,
                run_uri=run_uri,
                schema_version=self.schema_version,
                now=now,
            )

    def _import_offline_stage(
        self,
        conn: sqlite3.Connection,
        *,
        manifest: OfflineEvidenceManifest,
        stage: OfflineStageEvidence,
        import_provenance: Mapping[str, PlainData],
    ) -> BackendRevision:
        run_uri = manifest.run_uri
        status_data = _offline_import_stage_status(stage)
        status = StageStatus(cast(str, status_data["status"]))
        attempt_number = cast(int, status_data["attempt"])
        revision = self._next_revision(conn)
        reason = _offline_import_reason(import_provenance, stage_name=stage.stage_name)
        _upsert_stage(
            conn,
            run_uri=run_uri,
            stage_name=stage.stage_name,
            status=status,
            revision=revision,
            reason=reason,
        )
        attempt_id = f"{stage.stage_name}-{attempt_number}"
        conn.execute(
            """
            INSERT INTO stage_attempts (
                run_uri, attempt_id, stage_name, attempt_number, status,
                owner_id, created_at, revision_sequence, reason_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_uri,
                attempt_id,
                stage.stage_name,
                attempt_number,
                status.value,
                "offline-import",
                cast(str, status_data.get("started_at") or manifest.generated_at),
                revision.sequence,
                _json_dumps(reason.to_dict()),
            ),
        )
        output_refs = _offline_import_output_refs(stage)
        if output_refs:
            revision = self._next_revision(conn)
            commit_id = (
                f"{stage.stage_name}-{attempt_id}-offline-import-{revision.sequence}"
            )
            conn.execute(
                """
                INSERT INTO output_commits (
                    commit_id, run_uri, stage_name, attempt_id, committed_at,
                    revision_sequence, output_names_json, materialized_refs_json,
                    supersedes_commit_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    commit_id,
                    run_uri,
                    stage.stage_name,
                    attempt_id,
                    cast(str, status_data.get("finished_at") or manifest.generated_at),
                    revision.sequence,
                    _json_dumps(list(output_refs)),
                    _json_dumps([]),
                ),
            )
            for name, artifact in output_refs.items():
                conn.execute(
                    """
                    INSERT INTO artifact_facts (
                        run_uri, stage_name, artifact_name, artifact_json,
                        commit_id, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_uri,
                        stage.stage_name,
                        name,
                        _json_dumps(artifact.to_dict()),
                        commit_id,
                        revision.sequence,
                    ),
                )
        _touch_run(conn, run_uri=run_uri, revision=revision)
        return revision

    def record_cleanup_candidate(
        self,
        run_uri: str,
        *,
        kind: CleanupCandidateKind,
        uri: str,
        reason: LifecycleReason,
        candidate_id: str | None = None,
        expected_revision: BackendRevision | None = None,
    ) -> CleanupCandidate:
        """Persist a cleanup candidate for later diagnostics or cleanup."""

        run_uri = _non_empty(run_uri, "run_uri")
        kind = CleanupCandidateKind(kind)
        uri = _non_empty(uri, "uri")
        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason")
        with self.transaction() as conn:
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            revision = self._next_revision(conn)
            recorded_at = self._now()
            resolved_id = (
                candidate_id or f"cleanup-{revision.sequence}-{uuid.uuid4().hex[:12]}"
            )
            resolved_id = _non_empty(resolved_id, "candidate_id")
            conn.execute(
                """
                INSERT INTO cleanup_candidates (
                    candidate_id, run_uri, kind, uri, reason_json, recorded_at,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    run_uri,
                    kind.value,
                    uri,
                    _json_dumps(reason.to_dict()),
                    recorded_at,
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return CleanupCandidate(
                candidate_id=resolved_id,
                kind=kind,
                uri=uri,
                reason=reason,
                recorded_at=recorded_at,
                revision=revision,
            )

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        """List persisted cleanup candidates for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _cleanup_candidates(conn, run_uri)

    def append_cleanup_report(
        self,
        run_uri: str,
        report: CleanupReport,
        *,
        expected_revision: BackendRevision | None = None,
    ) -> CleanupReportFact:
        """Append a recorded cleanup report fact."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(report, CleanupReport):
            raise AuthorityRepositoryError("report must be a CleanupReport")
        if report.run_uri != run_uri:
            raise AuthorityRepositoryError("cleanup report run_uri does not match run")
        with self.transaction() as conn:
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            payload = report.to_dict()
            existing = conn.execute(
                """
                SELECT record_json
                FROM cleanup_reports
                WHERE run_uri = ? AND report_id = ?
                """,
                (run_uri, report.report_id),
            ).fetchone()
            if existing is not None:
                if _json_loads(cast(str, existing["record_json"])) == payload:
                    return _cleanup_report_fact(conn, run_uri, report.report_id)
                raise AuthorityRepositoryError(
                    "conflicting cleanup report already exists"
                )
            revision = self._next_revision(conn)
            recorded_at = self._now()
            conn.execute(
                """
                INSERT INTO cleanup_reports (
                    report_id, run_uri, record_json, recorded_at, revision_sequence
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    run_uri,
                    _json_dumps(payload),
                    recorded_at,
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return CleanupReportFact(
                report=report,
                recorded_at=recorded_at,
                revision=revision,
            )

    def list_cleanup_reports(self, run_uri: str) -> tuple[CleanupReportFact, ...]:
        """List recorded cleanup report facts for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _cleanup_report_facts(conn, run_uri)

    def append_cleanup_result(
        self,
        run_uri: str,
        result: CleanupResult,
        *,
        expected_revision: BackendRevision | None = None,
    ) -> CleanupResultFact:
        """Append a cleanup result fact."""

        run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(result, CleanupResult):
            raise AuthorityRepositoryError("result must be a CleanupResult")
        if result.run_uri != run_uri:
            raise AuthorityRepositoryError("cleanup result run_uri does not match run")
        with self.transaction() as conn:
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            payload = result.to_dict()
            existing = conn.execute(
                """
                SELECT record_json
                FROM cleanup_results
                WHERE run_uri = ? AND result_id = ?
                """,
                (run_uri, result.result_id),
            ).fetchone()
            if existing is not None:
                if _json_loads(cast(str, existing["record_json"])) == payload:
                    return _cleanup_result_fact(conn, run_uri, result.result_id)
                raise AuthorityRepositoryError(
                    "conflicting cleanup result already exists"
                )
            revision = self._next_revision(conn)
            recorded_at = self._now()
            conn.execute(
                """
                INSERT INTO cleanup_results (
                    result_id, run_uri, record_json, recorded_at, revision_sequence
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result.result_id,
                    run_uri,
                    _json_dumps(payload),
                    recorded_at,
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return CleanupResultFact(
                result=result,
                recorded_at=recorded_at,
                revision=revision,
            )

    def list_cleanup_results(self, run_uri: str) -> tuple[CleanupResultFact, ...]:
        """List cleanup result facts for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _cleanup_result_facts(conn, run_uri)

    def record_recovery(
        self,
        run_uri: str,
        *,
        kind: RecoveryKind,
        reason: LifecycleReason,
        recovery_id: str | None = None,
        stage_name: str | None = None,
        attempt_id: str | None = None,
        expected_revision: BackendRevision | None = None,
    ) -> RecoveryRecord:
        """Persist a recovery record for a run."""

        run_uri = _non_empty(run_uri, "run_uri")
        kind = RecoveryKind(kind)
        if not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason")
        if stage_name is not None:
            stage_name = _non_empty(stage_name, "stage_name")
        if attempt_id is not None:
            attempt_id = _non_empty(attempt_id, "attempt_id")
        with self.transaction() as conn:
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            revision = self._next_revision(conn)
            detected_at = self._now()
            resolved_id = (
                recovery_id or f"recovery-{revision.sequence}-{uuid.uuid4().hex[:12]}"
            )
            resolved_id = _non_empty(resolved_id, "recovery_id")
            conn.execute(
                """
                INSERT INTO recovery_records (
                    recovery_id, run_uri, kind, reason_json, detected_at,
                    revision_sequence, stage_name, attempt_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    run_uri,
                    kind.value,
                    _json_dumps(reason.to_dict()),
                    detected_at,
                    revision.sequence,
                    stage_name,
                    attempt_id,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return RecoveryRecord(
                recovery_id=resolved_id,
                kind=kind,
                reason=reason,
                detected_at=detected_at,
                revision=revision,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
            )

    def list_recovery_records(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        """List persisted recovery records for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _recovery_records(conn, run_uri)

    def create_workspace(self, identity: WorkspaceIdentity) -> BackendRevision:
        """Persist a workspace identity in service-owned coordination state."""

        return self._coordination_store().create_workspace(identity)

    def create_sweep(self, identity: SweepIdentity) -> BackendRevision:
        """Persist a sweep identity in service-owned coordination state."""

        return self._coordination_store().create_sweep(identity)

    def record_trial(self, trial: TrialReference) -> BackendRevision:
        """Persist a trial reference in service-owned coordination state."""

        return self._coordination_store().record_trial(trial)

    def list_trials(self, sweep_id: str) -> tuple[TrialReference, ...]:
        """List trial references for one sweep."""

        return self._coordination_store().list_trials(sweep_id)

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> TrialLeaseRecord:
        """Acquire a trial coordination lease."""

        return self._coordination_store().acquire_trial_lease(
            sweep_id,
            trial_id,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
    ) -> ResourceLeaseRecord:
        """Acquire a service-owned generic resource lease."""

        return self._coordination_store().acquire_resource_lease(
            workspace_id,
            resource_key,
            owner_id=owner_id,
            amount=amount,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def renew_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        """Renew a service-owned workspace coordination lease."""

        return self._coordination_store().renew_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def release_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        """Release a service-owned workspace coordination lease."""

        return self._coordination_store().release_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def fail_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        """Fail a service-owned workspace coordination lease."""

        return self._coordination_store().fail_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def set_counter_limit(
        self, workspace_id: str, counter_name: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        """Set a service-owned non-resource counter limit."""

        return self._coordination_store().set_counter_limit(
            workspace_id,
            counter_name,
            limit=limit,
        )

    def set_resource_limit(
        self, workspace_id: str, resource_key: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        """Set a service-owned generic resource limit."""

        return self._coordination_store().set_resource_limit(
            workspace_id,
            resource_key,
            limit=limit,
        )

    def ensure_resource_limits(
        self, workspace_id: str, limits: Mapping[str, int]
    ) -> tuple[ConcurrencyCounter, ...]:
        """Atomically create missing generic resource limits or match existing ones."""

        return self._coordination_store().ensure_resource_limits(workspace_id, limits)

    def read_resource_limit(
        self, workspace_id: str, resource_key: str
    ) -> ConcurrencyCounter | None:
        """Read a service-owned generic resource limit without mutating state."""

        return self._coordination_store().read_resource_limit(
            workspace_id,
            resource_key,
        )

    def increment_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        limit: int | None = None,
    ) -> ConcurrencyCounter:
        """Increment a service-owned non-resource counter."""

        return self._coordination_store().increment_counter(
            workspace_id,
            counter_name,
            amount=amount,
            limit=limit,
        )

    def decrement_counter(
        self, workspace_id: str, counter_name: str, *, amount: int = 1
    ) -> ConcurrencyCounter:
        """Decrement a service-owned non-resource counter."""

        return self._coordination_store().decrement_counter(
            workspace_id,
            counter_name,
            amount=amount,
        )

    def read_counter(
        self, workspace_id: str, counter_name: str
    ) -> ConcurrencyCounter | None:
        """Read a service-owned non-resource counter."""

        return self._coordination_store().read_counter(workspace_id, counter_name)

    def scan_coordination_recovery(
        self, workspace_id: str
    ) -> tuple[CoordinationRecoveryRecord, ...]:
        """Scan service-owned coordination recovery facts."""

        return self._coordination_store().scan_recovery(workspace_id)

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        """Return persisted and currently detectable run-level recovery facts."""

        run_uri = _non_empty(run_uri, "run_uri")
        now = self._now()
        with self._read_connection() as conn:
            revision = _current_run_revision(conn, run_uri)
            records = list(_recovery_records(conn, run_uri))
            for row in conn.execute(
                """
                SELECT *
                FROM controller_leases
                WHERE run_uri = ? AND state = ?
                ORDER BY lease_id
                """,
                (run_uri, LeaseState.ACTIVE.value),
            ):
                if not _timestamp_expired(cast(str, row["expires_at"]), now):
                    continue
                lease_id = cast(str, row["lease_id"])
                records.append(
                    RecoveryRecord(
                        recovery_id=f"expired-{lease_id}",
                        kind=RecoveryKind.EXPIRED_LEASE,
                        reason=LifecycleReason(code="lease_expired"),
                        detected_at=now,
                        revision=revision,
                        run_uri=run_uri,
                    )
                )
            for row in conn.execute(
                """
                SELECT *
                FROM stage_leases
                WHERE run_uri = ? AND state = ?
                ORDER BY lease_id
                """,
                (run_uri, LeaseState.ACTIVE.value),
            ):
                if not _timestamp_expired(cast(str, row["expires_at"]), now):
                    continue
                lease_id = cast(str, row["lease_id"])
                records.append(
                    RecoveryRecord(
                        recovery_id=f"expired-{lease_id}",
                        kind=RecoveryKind.EXPIRED_LEASE,
                        reason=LifecycleReason(code="lease_expired"),
                        detected_at=now,
                        revision=revision,
                        run_uri=run_uri,
                        stage_name=cast(str, row["stage_name"]),
                        attempt_id=cast(str, row["attempt_id"]),
                    )
                )
            for row in conn.execute(
                """
                SELECT *
                FROM stage_attempts
                WHERE run_uri = ? AND status IN (?, ?)
                ORDER BY stage_name, attempt_number
                """,
                (
                    run_uri,
                    StageStatus.RUNNING.value,
                    StageStatus.SUBMITTED.value,
                ),
            ):
                if (
                    _active_attempt_lease_row(
                        conn,
                        run_uri=run_uri,
                        stage_name=cast(str, row["stage_name"]),
                        attempt_id=cast(str, row["attempt_id"]),
                        now=now,
                    )
                    is not None
                ):
                    continue
                attempt_id = cast(str, row["attempt_id"])
                records.append(
                    RecoveryRecord(
                        recovery_id=f"abandoned-{attempt_id}",
                        kind=RecoveryKind.ABANDONED_ATTEMPT,
                        reason=LifecycleReason(code="attempt_without_active_lease"),
                        detected_at=now,
                        revision=revision,
                        run_uri=run_uri,
                        stage_name=cast(str, row["stage_name"]),
                        attempt_id=attempt_id,
                    )
                )
            for record in _submitted_operations(conn, run_uri):
                if record.active:
                    records.append(
                        RecoveryRecord(
                            recovery_id=f"submitted-{record.submission_id}",
                            kind=RecoveryKind.INTERRUPTED_SUBMISSION,
                            reason=LifecycleReason(code="submitted_operation_active"),
                            detected_at=now,
                            revision=revision,
                            run_uri=run_uri,
                        )
                    )
            return tuple(records)

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        with self._connection(create_parent=False) as conn:
            failure = _compatibility_failure(conn, current_version=self.schema_version)
            if failure is not None:
                raise AuthorityRepositoryCompatibilityError(failure)
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open an explicit private repository write transaction."""

        with self._connection(create_parent=False) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                failure = _compatibility_failure(
                    conn, current_version=self.schema_version
                )
                if failure is not None:
                    raise AuthorityRepositoryCompatibilityError(failure)
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _finish_stage_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None,
        state: LeaseState,
        reason: LifecycleReason | None,
    ) -> LeaseRecord:
        run_uri = _non_empty(run_uri, "run_uri")
        state = LeaseState(state)
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            row = _require_active_stage_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityRepositoryError("stage lease has expired")
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE stage_leases
                SET state = ?, revision_sequence = ?, reason_json = ?
                WHERE lease_id = ?
                """,
                (
                    state.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    lease_id,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return _stage_lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM stage_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone(),
                    "unknown stage lease",
                ),
                revision=revision,
            )

    def _finish_controller_lease(
        self,
        run_uri: str,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None,
        state: LeaseState,
        reason: LifecycleReason | None,
    ) -> LeaseRecord:
        run_uri = _non_empty(run_uri, "run_uri")
        state = LeaseState(state)
        if reason is not None and not isinstance(reason, LifecycleReason):
            raise AuthorityRepositoryError("reason must be a LifecycleReason or None")
        with self.transaction() as conn:
            row = _require_active_controller_lease_row(
                conn,
                run_uri=run_uri,
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityRepositoryError("controller lease has expired")
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE controller_leases
                SET state = ?, revision_sequence = ?, reason_json = ?
                WHERE lease_id = ?
                """,
                (
                    state.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    lease_id,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return _controller_lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM controller_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone(),
                    "unknown controller lease",
                ),
                revision=revision,
            )

    def _insert_reliability_fact(
        self,
        conn: sqlite3.Connection,
        *,
        run_uri: str,
        table: str,
        key_column: str,
        key: str,
        payload_column: str,
        payload: Mapping[str, PlainData],
        insert_sql: str,
        insert_values: tuple[object, ...],
    ) -> BackendRevision:
        existing = conn.execute(
            f"SELECT {payload_column}, revision_sequence FROM {table} "
            f"WHERE run_uri = ? AND {key_column} = ?",
            (run_uri, key),
        ).fetchone()
        if existing is not None:
            existing_payload = _json_loads(cast(str, existing[payload_column]))
            if not isinstance(existing_payload, Mapping):
                raise AuthorityRepositoryError(
                    "stored reliability fact must be a mapping"
                )
            if reliability_payload_matches(
                cast(Mapping[str, PlainData], existing_payload),
                payload,
            ):
                return _revision_for(
                    conn, cast(int, existing["revision_sequence"])
                )
            raise AuthorityRepositoryError(
                "conflicting reliability fact already exists"
            )
        revision = self._next_revision(conn)
        conn.execute(insert_sql, (*insert_values, revision.sequence))
        _touch_run(conn, run_uri=run_uri, revision=revision)
        return revision

    def _list_stage_reliability_records[T](
        self,
        run_uri: str,
        *,
        table: str,
        payload_column: str,
        parser: Callable[[object], T],
        stage_name: str | None,
        order_by: str,
    ) -> tuple[T, ...]:
        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            if stage_name is None:
                rows = conn.execute(
                    f"SELECT {payload_column} FROM {table} "
                    f"WHERE run_uri = ? ORDER BY {order_by}",
                    (run_uri,),
                ).fetchall()
            else:
                stage_name = _non_empty(stage_name, "stage_name")
                rows = conn.execute(
                    f"SELECT {payload_column} FROM {table} "
                    f"WHERE run_uri = ? AND stage_name = ? ORDER BY {order_by}",
                    (run_uri, stage_name),
                ).fetchall()
            return tuple(
                parser(_json_loads(cast(str, row[payload_column]))) for row in rows
            )

    def _next_revision(self, conn: sqlite3.Connection) -> BackendRevision:
        created_at = self._now()
        seed = uuid.uuid4().hex
        cursor = conn.execute(
            "INSERT INTO repository_revisions (token, created_at) VALUES (?, ?)",
            (seed, created_at),
        )
        sequence = cast(int, cursor.lastrowid)
        token = f"authority-rev-{sequence}-{seed}"
        conn.execute(
            "UPDATE repository_revisions SET token = ? WHERE sequence = ?",
            (token, sequence),
        )
        return BackendRevision(sequence=sequence, token=token, created_at=created_at)

    def _now(self) -> str:
        if self._clock is None:
            return utc_timestamp(utc_now())
        value = self._clock()
        if isinstance(value, str):
            parse_timestamp(value)
            return value
        return utc_timestamp(value)

    def _coordination_store(self) -> SQLiteWorkspaceCoordinationStore:
        return SQLiteWorkspaceCoordinationStore(
            self.state_dir / AUTHORITY_REPOSITORY_COORDINATION_DB_NAME,
            clock=self._clock,
        )

    @contextmanager
    def _connection(self, *, create_parent: bool) -> Iterator[sqlite3.Connection]:
        if create_parent:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        elif not self.database_path.exists():
            raise AuthorityRepositoryCompatibilityError(
                AuthorityRepositoryCompatibilityFailure(
                    kind=AuthorityRepositoryCompatibilityKind.MISSING,
                    message="authority repository database is missing",
                    current_version=self.schema_version,
                    detail={"database_path": str(self.database_path)},
                )
            )
        conn = sqlite3.connect(
            self.database_path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()


def initialize_authority_repository(
    state_dir: str | Path,
    *,
    service_generation: str | None = None,
) -> AuthorityRepository:
    """Initialize and return a private authority repository handle."""

    repository = AuthorityRepository(state_dir)
    repository.initialize(service_generation=service_generation)
    return repository


def generate_service_generation() -> str:
    """Return a new opaque service generation token."""

    return f"authority-generation-{uuid.uuid4().hex}"


def _migrate_v3_output_commits(
    conn: sqlite3.Connection, *, current_version: int
) -> None:
    """Atomically migrate one known-complete v3 repository to v4."""

    if current_version != 4:
        return
    tables = {
        cast(str, row["name"])
        for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    }
    if _METADATA_TABLE not in tables:
        return
    metadata_columns = {
        cast(str, row["name"])
        for row in conn.execute(f"PRAGMA table_info({_METADATA_TABLE})")
    }
    if not _REQUIRED_SCHEMA_COLUMNS[_METADATA_TABLE].issubset(metadata_columns):
        return
    row = conn.execute(
        f"SELECT value FROM {_METADATA_TABLE} WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return
    try:
        version = int(cast(str, row["value"]))
    except (TypeError, ValueError):
        return
    if version != 3:
        return

    missing_tables = set(_REQUIRED_SCHEMA_COLUMNS) - tables
    if missing_tables:
        raise AuthorityRepositoryCompatibilityError(
            _corrupt_failure(
                "authority repository v3 schema is incomplete",
                current_version=current_version,
            )
        )
    for table_name, expected_columns in _REQUIRED_SCHEMA_COLUMNS.items():
        v3_columns = (
            expected_columns - {"supersedes_commit_id"}
            if table_name == "output_commits"
            else expected_columns
        )
        actual_columns = {
            cast(str, info["name"])
            for info in conn.execute(f"PRAGMA table_info({table_name})")
        }
        if not v3_columns.issubset(actual_columns):
            raise AuthorityRepositoryCompatibilityError(
                _corrupt_failure(
                    "authority repository v3 schema is incomplete",
                    current_version=current_version,
                )
            )
    metadata = {
        cast(str, item["key"]): cast(str, item["value"])
        for item in conn.execute(f"SELECT key, value FROM {_METADATA_TABLE}")
    }
    if not _REQUIRED_METADATA_KEYS.issubset(metadata):
        raise AuthorityRepositoryCompatibilityError(
            _corrupt_failure(
                "authority repository v3 metadata is incomplete",
                current_version=current_version,
            )
        )

    conn.execute("DROP INDEX IF EXISTS idx_output_commits_stage")
    conn.execute("ALTER TABLE output_commits RENAME TO output_commits_v3")
    conn.execute(
        """
        CREATE TABLE output_commits (
            commit_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            output_names_json TEXT NOT NULL,
            materialized_refs_json TEXT NOT NULL,
            supersedes_commit_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO output_commits (
            commit_id, run_uri, stage_name, attempt_id, committed_at,
            revision_sequence, output_names_json, materialized_refs_json,
            supersedes_commit_id
        )
        SELECT commit_id, run_uri, stage_name, attempt_id, committed_at,
               revision_sequence, output_names_json, materialized_refs_json,
               NULL
        FROM output_commits_v3
        """
    )
    conn.execute("DROP TABLE output_commits_v3")
    conn.execute(
        f"UPDATE {_METADATA_TABLE} SET value = ? WHERE key = 'schema_version'",
        (str(current_version),),
    )


def _migrate_v5_coordinator_principals(
    conn: sqlite3.Connection, *, current_version: int
) -> None:
    """Atomically add authenticated coordinator ownership to a complete v5 DB."""

    if current_version != 6:
        return
    tables = {
        cast(str, row["name"])
        for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    }
    if _METADATA_TABLE not in tables:
        return
    metadata_columns = {
        cast(str, row["name"])
        for row in conn.execute(f"PRAGMA table_info({_METADATA_TABLE})")
    }
    if not _REQUIRED_SCHEMA_COLUMNS[_METADATA_TABLE].issubset(metadata_columns):
        return
    row = conn.execute(
        f"SELECT value FROM {_METADATA_TABLE} WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return
    try:
        version = int(cast(str, row["value"]))
    except (TypeError, ValueError):
        return
    if version != 5:
        return
    missing_tables = set(_REQUIRED_SCHEMA_COLUMNS) - tables
    if missing_tables:
        raise AuthorityRepositoryCompatibilityError(
            _corrupt_failure(
                "authority repository v5 schema is incomplete",
                current_version=current_version,
            )
        )
    for table_name, expected_columns in _REQUIRED_SCHEMA_COLUMNS.items():
        v5_columns = (
            expected_columns - {"service_principal"}
            if table_name == "coordinator_admission_receipts"
            else expected_columns
        )
        actual_columns = {
            cast(str, info["name"])
            for info in conn.execute(f"PRAGMA table_info({table_name})")
        }
        if not v5_columns.issubset(actual_columns):
            raise AuthorityRepositoryCompatibilityError(
                _corrupt_failure(
                    "authority repository v5 schema is incomplete",
                    current_version=current_version,
                )
            )
    metadata = {
        cast(str, item["key"]): cast(str, item["value"])
        for item in conn.execute(f"SELECT key, value FROM {_METADATA_TABLE}")
    }
    if not _REQUIRED_METADATA_KEYS.issubset(metadata):
        raise AuthorityRepositoryCompatibilityError(
            _corrupt_failure(
                "authority repository v5 metadata is incomplete",
                current_version=current_version,
            )
        )
    conn.execute(
        "ALTER TABLE coordinator_admission_receipts "
        "ADD COLUMN service_principal TEXT"
    )
    conn.execute(
        f"UPDATE {_METADATA_TABLE} SET value = ? WHERE key = 'schema_version'",
        (str(current_version),),
    )


def _initialize_schema(
    conn: sqlite3.Connection,
    *,
    schema_version: int,
    service_generation: str,
    timestamp: str,
) -> None:
    schema_statements = (
        """
        CREATE TABLE IF NOT EXISTS repository_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS repository_revisions (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS authority_runs (
            run_uri TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_revision_sequence INTEGER NOT NULL,
            updated_revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS controller_leases (
            lease_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            fencing_token TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            renewed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            state TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS submitted_operations (
            run_uri TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, submission_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleanup_candidates (
            candidate_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            reason_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleanup_reports (
            report_id TEXT NOT NULL,
            run_uri TEXT NOT NULL,
            record_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, report_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleanup_results (
            result_id TEXT NOT NULL,
            run_uri TEXT NOT NULL,
            record_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, result_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS recovery_records (
            recovery_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            kind TEXT NOT NULL,
            reason_json TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            stage_name TEXT,
            attempt_id TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER NOT NULL,
            run_uri TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            event_json TEXT,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY(run_uri, sequence)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS authority_stages (
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT,
            PRIMARY KEY (run_uri, stage_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stage_attempts (
            run_uri TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            owner_id TEXT,
            created_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT,
            PRIMARY KEY (run_uri, attempt_id),
            UNIQUE (run_uri, stage_name, attempt_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stage_leases (
            lease_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            fencing_token TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            renewed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            state TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS output_commits (
            commit_id TEXT PRIMARY KEY,
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            output_names_json TEXT NOT NULL,
            materialized_refs_json TEXT NOT NULL,
            supersedes_commit_id TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS artifact_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            artifact_name TEXT NOT NULL,
            artifact_json TEXT NOT NULL,
            commit_id TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            UNIQUE (commit_id, artifact_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS prepared_attempt_receipts (
            run_uri TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            readiness_generation TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            request_json TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, operation_id),
            UNIQUE (run_uri, stage_name, readiness_generation),
            UNIQUE (run_uri, attempt_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS managed_attempt_bindings (
            run_uri TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            state TEXT NOT NULL,
            fence TEXT,
            terminal_status TEXT,
            terminal_digest TEXT,
            PRIMARY KEY (run_uri, assignment_id),
            UNIQUE (run_uri, attempt_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS managed_attempt_unbind_receipts (
            run_uri TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            PRIMARY KEY (run_uri, assignment_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS coordinator_admission_receipts (
            run_uri TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            service_principal TEXT,
            request_json TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            PRIMARY KEY (run_uri, operation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cancellation_epochs (
            run_uri TEXT PRIMARY KEY,
            epoch TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cancellation_epoch_receipts (
            run_uri TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            request_json TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            PRIMARY KEY (run_uri, operation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_policy_facts (
            run_uri TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            scope TEXT NOT NULL,
            stage_name TEXT,
            attempt_number INTEGER,
            recorded_at TEXT NOT NULL,
            fact_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, fact_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_status_details (
            run_uri TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, fact_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_transactions (
            run_uri TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            causal_parent_id TEXT,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, transaction_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS retry_decisions (
            run_uri TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, decision_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS timeout_outcomes (
            run_uri TEXT NOT NULL,
            outcome_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY (run_uri, outcome_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_controller_leases_run
            ON controller_leases(run_uri, state, expires_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_submitted_operations_run
            ON submitted_operations(run_uri, submission_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_cleanup_candidates_run
            ON cleanup_candidates(run_uri, candidate_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_cleanup_reports_run
            ON cleanup_reports(run_uri, report_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_cleanup_results_run
            ON cleanup_results(run_uri, result_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_recovery_records_run
            ON recovery_records(run_uri, recovery_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_run
            ON audit_events(run_uri, sequence)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_authority_stages_run
            ON authority_stages(run_uri, stage_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_stage_attempts_stage
            ON stage_attempts(run_uri, stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_stage_leases_stage
            ON stage_leases(run_uri, stage_name, state, expires_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_stage_leases_attempt
            ON stage_leases(run_uri, attempt_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_output_commits_stage
            ON output_commits(run_uri, stage_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_artifact_facts_stage
            ON artifact_facts(run_uri, stage_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_policy_stage
            ON reliability_policy_facts(run_uri, stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_status_stage
            ON reliability_status_details(run_uri, stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_transactions_stage
            ON reliability_transactions(run_uri, stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_retry_decisions_stage
            ON retry_decisions(run_uri, stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_timeout_outcomes_stage
            ON timeout_outcomes(run_uri, stage_name, attempt_number)
        """,
    )
    for statement in schema_statements:
        conn.execute(statement)
    _ensure_audit_event_json_column(conn)
    _insert_metadata_if_missing(conn, "schema_version", str(schema_version))
    _insert_metadata_if_missing(conn, "service_generation", service_generation)
    _insert_metadata_if_missing(conn, "created_at", timestamp)
    conn.execute(
        """
        INSERT INTO repository_metadata(key, value)
        VALUES ('updated_at', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (timestamp,),
    )


def _insert_metadata_if_missing(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO repository_metadata(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO NOTHING
        """,
        (key, value),
    )


def _compatibility_failure(
    conn: sqlite3.Connection, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        tables = {
            cast(str, row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_schema
                WHERE type = 'table'
                """
            )
        }
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository database is corrupt or unreadable",
            current_version=current_version,
        )
    if _METADATA_TABLE not in tables:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.MISSING,
            message="authority repository metadata is missing",
            current_version=current_version,
        )
    metadata_shape_failure = _metadata_shape_failure(
        conn, current_version=current_version
    )
    if metadata_shape_failure is not None:
        return metadata_shape_failure
    metadata = _read_metadata(conn, current_version=current_version)
    if isinstance(metadata, AuthorityRepositoryCompatibilityFailure):
        return metadata
    missing_keys = _REQUIRED_METADATA_KEYS - set(metadata)
    if missing_keys:
        missing_key_values: list[PlainData] = list(sorted(missing_keys))
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.MISSING,
            message="authority repository metadata is incomplete",
            current_version=current_version,
            detail={"missing_keys": missing_key_values},
        )
    version_failure = _schema_version_failure(
        metadata["schema_version"], current_version=current_version
    )
    if version_failure is not None:
        return version_failure
    shape_failure = _schema_shape_failure(conn, current_version=current_version)
    if shape_failure is not None:
        return shape_failure
    for metadata_field in ("service_generation", "created_at", "updated_at"):
        if not metadata[metadata_field]:
            return _corrupt_failure(
                f"authority repository metadata field {metadata_field!r} is empty",
                current_version=current_version,
            )
    try:
        parse_timestamp(metadata["created_at"])
        parse_timestamp(metadata["updated_at"])
    except ValueError:
        return _corrupt_failure(
            "authority repository timestamps are invalid",
            current_version=current_version,
        )
    return None


def _metadata_shape_failure(
    conn: sqlite3.Connection, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        columns = {
            cast(str, row["name"])
            for row in conn.execute(f"PRAGMA table_info({_METADATA_TABLE})")
        }
        if not _REQUIRED_SCHEMA_COLUMNS[_METADATA_TABLE].issubset(columns):
            return _corrupt_failure(
                "authority repository metadata schema is incomplete or invalid",
                current_version=current_version,
            )
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository metadata schema is corrupt or unreadable",
            current_version=current_version,
        )
    return None


def _schema_shape_failure(
    conn: sqlite3.Connection, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        for table_name, expected_columns in _REQUIRED_SCHEMA_COLUMNS.items():
            columns = {
                cast(str, row["name"])
                for row in conn.execute(f"PRAGMA table_info({table_name})")
            }
            if not expected_columns.issubset(columns):
                return _corrupt_failure(
                    "authority repository schema is incomplete or invalid",
                    current_version=current_version,
                )
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository schema is corrupt or unreadable",
            current_version=current_version,
        )
    return None


def _read_metadata(
    conn: sqlite3.Connection, *, current_version: int
) -> dict[str, str] | AuthorityRepositoryCompatibilityFailure:
    try:
        return {
            cast(str, row["key"]): cast(str, row["value"])
            for row in conn.execute("SELECT key, value FROM repository_metadata")
        }
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository metadata is corrupt or unreadable",
            current_version=current_version,
        )


def _schema_version_failure(
    raw_version: str, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        version = int(raw_version)
    except ValueError:
        return _corrupt_failure(
            "authority repository schema version is invalid",
            current_version=current_version,
        )
    if version <= 0:
        return _corrupt_failure(
            "authority repository schema version is invalid",
            current_version=current_version,
        )
    if version < current_version:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER,
            message=(
                f"unsupported older authority repository schema {version}; "
                f"expected {current_version}"
            ),
            found_version=version,
            current_version=current_version,
        )
    if version > current_version:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER,
            message=(
                f"unsupported newer authority repository schema {version}; "
                f"this Loom version supports {current_version}"
            ),
            found_version=version,
            current_version=current_version,
        )
    return None


def _identity_from_connection(
    repository: AuthorityRepository, conn: sqlite3.Connection
) -> AuthorityRepositoryIdentity:
    metadata = _read_metadata(conn, current_version=repository.schema_version)
    if isinstance(metadata, AuthorityRepositoryCompatibilityFailure):
        raise AuthorityRepositoryCompatibilityError(metadata)
    return AuthorityRepositoryIdentity(
        state_dir=repository.state_dir,
        database_path=repository.database_path,
        schema_version=int(metadata["schema_version"]),
        service_generation=metadata["service_generation"],
        created_at=metadata["created_at"],
        updated_at=metadata["updated_at"],
    )


def _run_snapshot(
    conn: sqlite3.Connection, *, run_uri: str, schema_version: int, now: str
) -> AuthoritativeRunSnapshot:
    run_row = _require_run_row(conn, run_uri)
    revision = _revision_for(conn, cast(int, run_row["updated_revision_sequence"]))
    stage_names = _stage_names(conn, run_uri)
    return AuthoritativeRunSnapshot(
        run_uri=run_uri,
        status=RunStatus(cast(str, run_row["status"])),
        schema_version=schema_version,
        revision=revision,
        stages=tuple(
            _stage_snapshot(conn, run_uri=run_uri, stage_name=stage_name, now=now)
            for stage_name in stage_names
        ),
        submitted_operations=_submitted_operations(conn, run_uri),
        cleanup_candidates=_cleanup_candidates(conn, run_uri),
        cleanup_reports=_cleanup_report_facts(conn, run_uri),
        cleanup_results=_cleanup_result_facts(conn, run_uri),
        metadata=_public_run_metadata(
            _plain_mapping(_json_loads(cast(str, run_row["metadata_json"])), "metadata")
        ),
    )


def _admission_metadata(
    metadata: Mapping[str, PlainData], idempotency_key: str | None
) -> dict[str, PlainData]:
    if _ADMISSION_IDEMPOTENCY_METADATA_KEY in metadata:
        raise AuthorityRepositoryError("metadata uses a reserved authority key")
    persisted = dict(metadata)
    if idempotency_key is not None:
        persisted[_ADMISSION_IDEMPOTENCY_METADATA_KEY] = _non_empty(
            idempotency_key, "idempotency_key"
        )
    return persisted


def _admission_matches(
    existing: Mapping[str, PlainData],
    metadata: Mapping[str, PlainData],
    idempotency_key: str | None,
) -> bool:
    if idempotency_key is None:
        return False
    return existing.get(
        _ADMISSION_IDEMPOTENCY_METADATA_KEY
    ) == idempotency_key and _public_run_metadata(existing) == dict(metadata)


def _public_run_metadata(metadata: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {
        key: value
        for key, value in metadata.items()
        if key != _ADMISSION_IDEMPOTENCY_METADATA_KEY
    }


def _event_matches_record(event: PipelineEvent, record: PipelineEventRecord) -> bool:
    if (
        record.scope != event.scope
        or record.event_type != event.event_type
        or record.payload != event.payload
    ):
        return False
    return event.timestamp is None or record.timestamp == event.timestamp


def _offline_import_provenance(
    manifest: OfflineEvidenceManifest,
    *,
    imported_at: str,
    imported_by: str,
    workspace_id: str | None,
) -> dict[str, PlainData]:
    provenance: dict[str, PlainData] = {
        "source": "offline_evidence",
        "historical_only": True,
        "resumable_live": False,
        "import_policy": "strict_reject_collisions",
        "manifest_kind": manifest.kind,
        "manifest_schema_version": manifest.schema_version,
        "manifest_generated_at": manifest.generated_at,
        "manifest_status": manifest.manifest_status.value,
        "imported_at": imported_at,
        "imported_by": imported_by,
        "state_source": dict(manifest.state_source),
        "diagnostic_count": len(manifest.diagnostics),
    }
    if workspace_id is not None:
        provenance["workspace_id"] = workspace_id
    return provenance


def _offline_import_reason(
    import_provenance: Mapping[str, PlainData],
    *,
    stage_name: str | None = None,
) -> LifecycleReason:
    detail: dict[str, PlainData] = {
        "source": "offline_evidence",
        "manifest_generated_at": import_provenance.get("manifest_generated_at"),
        "imported_at": import_provenance.get("imported_at"),
    }
    if stage_name is not None:
        detail["stage_name"] = stage_name
    return LifecycleReason(
        code="offline_import",
        message="imported from v10 offline evidence",
        detail=detail,
    )


def _offline_import_run_status(
    manifest: OfflineEvidenceManifest,
) -> Mapping[str, PlainData]:
    if not isinstance(manifest.run_status, Mapping):
        raise AuthorityRepositoryError("offline evidence run status is missing")
    return manifest.run_status


def _offline_import_stage_status(
    stage: OfflineStageEvidence,
) -> Mapping[str, PlainData]:
    if not isinstance(stage.status, Mapping):
        raise AuthorityRepositoryError(
            f"offline evidence stage status is missing: {stage.stage_name}"
        )
    return stage.status


def _offline_import_output_refs(
    stage: OfflineStageEvidence,
) -> dict[str, ArtifactRef]:
    outputs: dict[str, ArtifactRef] = {}
    for name, data in (stage.outputs or {}).items():
        if not isinstance(data, Mapping):
            raise AuthorityRepositoryError(
                f"offline evidence output is invalid: {stage.stage_name}.{name}"
            )
        outputs[name] = ArtifactRef.from_dict(data)
    return outputs


def _insert_import_audit_event(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData],
    revision: BackendRevision,
    scope: EventScope | None = None,
) -> None:
    event_scope = scope or EventScope.run()
    _ensure_audit_event_json_column(conn)
    sequence = _next_audit_event_sequence(conn, run_uri=run_uri)
    record = PipelineEventRecord(
        run_uri=run_uri,
        sequence=sequence,
        timestamp=timestamp,
        scope=event_scope,
        event_type=event_type,
        payload=payload,
    )
    conn.execute(
        """
        INSERT INTO audit_events (
            run_uri, sequence, timestamp, scope_json, event_type, payload_json,
            event_json,
            revision_sequence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uri,
            sequence,
            timestamp,
            _json_dumps(event_scope.to_dict()),
            event_type,
            _json_dumps(dict(payload)),
            _json_dumps(record.to_dict()),
            revision.sequence,
        ),
    )


def _require_run_row(conn: sqlite3.Connection, run_uri: str) -> sqlite3.Row:
    return _require_row(
        conn.execute(
            "SELECT * FROM authority_runs WHERE run_uri = ?",
            (run_uri,),
        ).fetchone(),
        "unknown run",
    )


def _current_run_revision(conn: sqlite3.Connection, run_uri: str) -> BackendRevision:
    row = _require_run_row(conn, run_uri)
    return _revision_for(conn, cast(int, row["updated_revision_sequence"]))


def _touch_run(
    conn: sqlite3.Connection, *, run_uri: str, revision: BackendRevision
) -> None:
    conn.execute(
        """
        UPDATE authority_runs
        SET updated_revision_sequence = ?
        WHERE run_uri = ?
        """,
        (revision.sequence, run_uri),
    )


def _revision_for(conn: sqlite3.Connection, sequence: int) -> BackendRevision:
    row = _require_row(
        conn.execute(
            """
            SELECT sequence, token, created_at
            FROM repository_revisions
            WHERE sequence = ?
            """,
            (sequence,),
        ).fetchone(),
        "unknown repository revision",
    )
    return BackendRevision(
        sequence=cast(int, row["sequence"]),
        token=cast(str, row["token"]),
        created_at=cast(str, row["created_at"]),
    )


def _require_expected_revision(
    actual: BackendRevision, expected: BackendRevision | None
) -> None:
    if expected is None:
        return
    if not isinstance(expected, BackendRevision):
        raise AuthorityRepositoryError(
            "expected_revision must be a BackendRevision or None"
        )
    if actual.sequence != expected.sequence or actual.token != expected.token:
        raise AuthorityRepositoryError("stale run revision")


def _require_service_generation(
    conn: sqlite3.Connection, expected_generation: str | None
) -> None:
    if expected_generation is None:
        return
    expected_generation = _non_empty(expected_generation, "service_generation")
    metadata = _read_metadata(conn, current_version=AUTHORITY_REPOSITORY_SCHEMA_VERSION)
    if isinstance(metadata, AuthorityRepositoryCompatibilityFailure):
        raise AuthorityRepositoryCompatibilityError(metadata)
    if metadata["service_generation"] != expected_generation:
        raise AuthorityRepositoryError("stale service generation")


def _upsert_stage(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    stage_name: str,
    status: StageStatus,
    revision: BackendRevision,
    reason: LifecycleReason | None,
) -> None:
    conn.execute(
        """
        INSERT INTO authority_stages (
            run_uri, stage_name, status, revision_sequence, reason_json
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(run_uri, stage_name) DO UPDATE SET
            status = excluded.status,
            revision_sequence = excluded.revision_sequence,
            reason_json = excluded.reason_json
        """,
        (
            run_uri,
            stage_name,
            StageStatus(status).value,
            revision.sequence,
            _json_dumps_or_none(reason),
        ),
    )


def _next_attempt_number(
    conn: sqlite3.Connection, run_uri: str, stage_name: str
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt
        FROM stage_attempts
        WHERE run_uri = ? AND stage_name = ?
        """,
        (run_uri, stage_name),
    ).fetchone()
    return cast(
        int, _require_row(row, "could not allocate stage attempt")["next_attempt"]
    )


def _require_stage_attempt_row(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    stage_name: str,
    attempt_id: str,
) -> sqlite3.Row:
    return _require_row(
        conn.execute(
            """
            SELECT *
            FROM stage_attempts
            WHERE run_uri = ? AND stage_name = ? AND attempt_id = ?
            """,
            (run_uri, stage_name, attempt_id),
        ).fetchone(),
        "unknown stage attempt",
    )


def _insert_stage_lease(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    stage_name: str,
    attempt_id: str,
    owner_id: str,
    lease_ttl_seconds: int,
    revision: BackendRevision,
    now: str,
) -> LeaseRecord:
    lease_id = f"stage-lease-{revision.sequence}-{uuid.uuid4().hex[:12]}"
    fencing_token = f"fence-{revision.sequence}-{uuid.uuid4().hex}"
    expires_at = _add_seconds(now, lease_ttl_seconds)
    conn.execute(
        """
        INSERT INTO stage_leases (
            lease_id, run_uri, stage_name, attempt_id, owner_id, fencing_token,
            acquired_at, renewed_at, expires_at, state, revision_sequence, reason_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            lease_id,
            run_uri,
            stage_name,
            attempt_id,
            owner_id,
            fencing_token,
            now,
            now,
            expires_at,
            LeaseState.ACTIVE.value,
            revision.sequence,
        ),
    )
    return LeaseRecord(
        lease_id=lease_id,
        kind=LeaseKind.STAGE,
        owner_id=owner_id,
        fencing_token=fencing_token,
        acquired_at=now,
        renewed_at=now,
        expires_at=expires_at,
        revision=revision,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt_id=attempt_id,
    )


def _active_stage_lease_row(
    conn: sqlite3.Connection, *, run_uri: str, stage_name: str, now: str
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM stage_leases
        WHERE run_uri = ? AND stage_name = ? AND state = ?
        ORDER BY acquired_at DESC
        """,
        (run_uri, stage_name, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _active_attempt_lease_row(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    stage_name: str,
    attempt_id: str,
    now: str,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM stage_leases
        WHERE run_uri = ?
            AND stage_name = ?
            AND attempt_id = ?
            AND state = ?
        ORDER BY acquired_at DESC
        """,
        (run_uri, stage_name, attempt_id, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _require_active_stage_lease_row(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    lease_id: str,
    owner_id: str,
    fencing_token: str,
) -> sqlite3.Row:
    lease_id = _non_empty(lease_id, "lease_id")
    owner_id = _non_empty(owner_id, "owner_id")
    fencing_token = _non_empty(fencing_token, "fencing_token")
    row = conn.execute(
        """
        SELECT *
        FROM stage_leases
        WHERE run_uri = ? AND lease_id = ?
        """,
        (run_uri, lease_id),
    ).fetchone()
    row = _require_row(row, "unknown stage lease")
    if (
        cast(str, row["owner_id"]) != owner_id
        or cast(str, row["fencing_token"]) != fencing_token
    ):
        raise AuthorityRepositoryError("stale or foreign fencing token")
    if LeaseState(cast(str, row["state"])) is not LeaseState.ACTIVE:
        raise AuthorityRepositoryError("stage lease is not active")
    return row


def _stage_lease_id_for_attempt(
    conn: sqlite3.Connection, run_uri: str, attempt_id: str
) -> str:
    row = conn.execute(
        """
        SELECT lease_id
        FROM stage_leases
        WHERE run_uri = ? AND attempt_id = ? AND state = ?
        ORDER BY acquired_at DESC
        LIMIT 1
        """,
        (run_uri, attempt_id, LeaseState.ACTIVE.value),
    ).fetchone()
    return cast(str, _require_row(row, "missing active stage lease")["lease_id"])


def _stage_lease_from_row(
    row: sqlite3.Row, *, revision: BackendRevision
) -> LeaseRecord:
    return LeaseRecord(
        lease_id=cast(str, row["lease_id"]),
        kind=LeaseKind.STAGE,
        owner_id=cast(str, row["owner_id"]),
        fencing_token=cast(str, row["fencing_token"]),
        acquired_at=cast(str, row["acquired_at"]),
        renewed_at=cast(str, row["renewed_at"]),
        expires_at=cast(str, row["expires_at"]),
        revision=revision,
        state=LeaseState(cast(str, row["state"])),
        run_uri=cast(str, row["run_uri"]),
        stage_name=cast(str, row["stage_name"]),
        attempt_id=cast(str, row["attempt_id"]),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _stage_names(conn: sqlite3.Connection, run_uri: str) -> tuple[str, ...]:
    stage_names = {
        cast(str, row["stage_name"])
        for row in conn.execute(
            "SELECT stage_name FROM authority_stages WHERE run_uri = ?",
            (run_uri,),
        )
    }
    stage_names.update(
        cast(str, row["stage_name"])
        for row in conn.execute(
            "SELECT DISTINCT stage_name FROM stage_attempts WHERE run_uri = ?",
            (run_uri,),
        )
    )
    stage_names.update(
        cast(str, row["stage_name"])
        for row in conn.execute(
            "SELECT DISTINCT stage_name FROM output_commits WHERE run_uri = ?",
            (run_uri,),
        )
    )
    return tuple(sorted(stage_names))


def _stage_snapshot(
    conn: sqlite3.Connection, *, run_uri: str, stage_name: str, now: str
) -> StageLifecycleSnapshot:
    stage_row = conn.execute(
        """
        SELECT *
        FROM authority_stages
        WHERE run_uri = ? AND stage_name = ?
        """,
        (run_uri, stage_name),
    ).fetchone()
    if stage_row is None:
        status = StageStatus.PENDING
        revision = _current_run_revision(conn, run_uri)
        reason = None
    else:
        status = StageStatus(cast(str, stage_row["status"]))
        revision = _revision_for(conn, cast(int, stage_row["revision_sequence"]))
        reason = _reason_from_json(cast(str | None, stage_row["reason_json"]))
    attempts = tuple(
        _attempt_from_row(row, conn=conn)
        for row in conn.execute(
            """
            SELECT *
            FROM stage_attempts
            WHERE run_uri = ? AND stage_name = ?
            ORDER BY attempt_number
            """,
            (run_uri, stage_name),
        )
    )
    lease_row = _active_stage_lease_row(
        conn, run_uri=run_uri, stage_name=stage_name, now=now
    )
    active_lease = (
        None
        if lease_row is None
        else _stage_lease_from_row(
            lease_row,
            revision=_revision_for(conn, cast(int, lease_row["revision_sequence"])),
        )
    )
    commit_row = conn.execute(
        """
        SELECT *
        FROM output_commits
        WHERE run_uri = ? AND stage_name = ?
        ORDER BY revision_sequence DESC
        LIMIT 1
        """,
        (run_uri, stage_name),
    ).fetchone()
    latest_commit = (
        None if commit_row is None else _commit_from_row(commit_row, conn=conn)
    )
    artifact_facts = tuple(
        _artifact_fact_from_row(row, conn=conn)
        for row in conn.execute(
            """
            SELECT *
            FROM artifact_facts
            WHERE commit_id = ?
            ORDER BY artifact_name
            """,
            (None if commit_row is None else commit_row["commit_id"],),
        )
    )
    return StageLifecycleSnapshot(
        stage_name=stage_name,
        status=status,
        revision=revision,
        attempts=attempts,
        active_lease=active_lease,
        latest_commit=latest_commit,
        artifact_facts=artifact_facts,
        reason=reason,
    )


def _attempt_from_row(row: sqlite3.Row, *, conn: sqlite3.Connection) -> StageAttempt:
    return StageAttempt(
        run_uri=cast(str, row["run_uri"]),
        stage_name=cast(str, row["stage_name"]),
        attempt=cast(int, row["attempt_number"]),
        attempt_id=cast(str, row["attempt_id"]),
        status=StageStatus(cast(str, row["status"])),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        created_at=cast(str, row["created_at"]),
        owner=cast(str | None, row["owner_id"]),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _commit_from_row(
    row: sqlite3.Row, *, conn: sqlite3.Connection
) -> OutputCommitRecord:
    return OutputCommitRecord(
        commit_id=cast(str, row["commit_id"]),
        run_uri=cast(str, row["run_uri"]),
        stage_name=cast(str, row["stage_name"]),
        attempt_id=cast(str, row["attempt_id"]),
        committed_at=cast(str, row["committed_at"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        output_names=tuple(
            cast(str, name) for name in _json_loads(cast(str, row["output_names_json"]))
        ),
        supersedes_commit_id=cast(str | None, row["supersedes_commit_id"]),
    )


def _artifact_fact_from_row(
    row: sqlite3.Row, *, conn: sqlite3.Connection
) -> ArtifactFactRecord:
    return ArtifactFactRecord(
        artifact_name=cast(str, row["artifact_name"]),
        artifact=ArtifactRef.from_dict(_json_loads(cast(str, row["artifact_json"]))),
        commit_id=cast(str, row["commit_id"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
    )


def _insert_controller_lease(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    owner_id: str,
    lease_ttl_seconds: int,
    revision: BackendRevision,
    now: str,
) -> LeaseRecord:
    lease_id = f"controller-lease-{revision.sequence}-{uuid.uuid4().hex[:12]}"
    fencing_token = f"fence-{revision.sequence}-{uuid.uuid4().hex}"
    expires_at = _add_seconds(now, lease_ttl_seconds)
    conn.execute(
        """
        INSERT INTO controller_leases (
            lease_id, run_uri, owner_id, fencing_token, acquired_at,
            renewed_at, expires_at, state, revision_sequence, reason_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            lease_id,
            run_uri,
            owner_id,
            fencing_token,
            now,
            now,
            expires_at,
            LeaseState.ACTIVE.value,
            revision.sequence,
        ),
    )
    return LeaseRecord(
        lease_id=lease_id,
        kind=LeaseKind.CONTROLLER,
        owner_id=owner_id,
        fencing_token=fencing_token,
        acquired_at=now,
        renewed_at=now,
        expires_at=expires_at,
        revision=revision,
        run_uri=run_uri,
    )


def _active_controller_lease_row(
    conn: sqlite3.Connection, *, run_uri: str, now: str
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM controller_leases
        WHERE run_uri = ? AND state = ?
        ORDER BY acquired_at DESC
        """,
        (run_uri, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _require_active_controller_lease_row(
    conn: sqlite3.Connection,
    *,
    run_uri: str,
    lease_id: str,
    owner_id: str,
    fencing_token: str,
) -> sqlite3.Row:
    lease_id = _non_empty(lease_id, "lease_id")
    owner_id = _non_empty(owner_id, "owner_id")
    fencing_token = _non_empty(fencing_token, "fencing_token")
    row = conn.execute(
        """
        SELECT *
        FROM controller_leases
        WHERE run_uri = ? AND lease_id = ?
        """,
        (run_uri, lease_id),
    ).fetchone()
    row = _require_row(row, "unknown controller lease")
    if (
        cast(str, row["owner_id"]) != owner_id
        or cast(str, row["fencing_token"]) != fencing_token
    ):
        raise AuthorityRepositoryError("stale or foreign fencing token")
    if LeaseState(cast(str, row["state"])) is not LeaseState.ACTIVE:
        raise AuthorityRepositoryError("controller lease is not active")
    return row


def _controller_lease_from_row(
    row: sqlite3.Row, *, revision: BackendRevision
) -> LeaseRecord:
    return LeaseRecord(
        lease_id=cast(str, row["lease_id"]),
        kind=LeaseKind.CONTROLLER,
        owner_id=cast(str, row["owner_id"]),
        fencing_token=cast(str, row["fencing_token"]),
        acquired_at=cast(str, row["acquired_at"]),
        renewed_at=cast(str, row["renewed_at"]),
        expires_at=cast(str, row["expires_at"]),
        revision=revision,
        state=LeaseState(cast(str, row["state"])),
        run_uri=cast(str, row["run_uri"]),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _submitted_operations(
    conn: sqlite3.Connection, run_uri: str
) -> tuple[SubmittedOperationRecord, ...]:
    return tuple(
        _submitted_from_json(cast(str, row["record_json"]), run_uri)
        for row in conn.execute(
            """
            SELECT record_json
            FROM submitted_operations
            WHERE run_uri = ?
            ORDER BY submission_id
            """,
            (run_uri,),
        )
    )


def _submitted_from_json(data: str, run_uri: str) -> SubmittedOperationRecord:
    raw = _json_loads(data)
    if not isinstance(raw, dict):
        raise AuthorityRepositoryError("submitted operation record must be a mapping")
    raw["run_uri"] = run_uri
    return SubmittedOperationRecord.from_dict(raw)


def _cleanup_candidates(
    conn: sqlite3.Connection, run_uri: str
) -> tuple[CleanupCandidate, ...]:
    return tuple(
        CleanupCandidate(
            candidate_id=cast(str, row["candidate_id"]),
            kind=CleanupCandidateKind(cast(str, row["kind"])),
            uri=cast(str, row["uri"]),
            reason=LifecycleReason.from_dict(
                _json_loads(cast(str, row["reason_json"]))
            ),
            recorded_at=cast(str, row["recorded_at"]),
            revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        )
        for row in conn.execute(
            """
            SELECT *
            FROM cleanup_candidates
            WHERE run_uri = ?
            ORDER BY candidate_id
            """,
            (run_uri,),
        )
    )


def _cleanup_report_fact(
    conn: sqlite3.Connection, run_uri: str, report_id: str
) -> CleanupReportFact:
    row = _require_row(
        conn.execute(
            """
            SELECT *
            FROM cleanup_reports
            WHERE run_uri = ? AND report_id = ?
            """,
            (run_uri, report_id),
        ).fetchone(),
        "unknown cleanup report",
    )
    return _cleanup_report_fact_from_row(conn, row)


def _cleanup_report_facts(
    conn: sqlite3.Connection, run_uri: str
) -> tuple[CleanupReportFact, ...]:
    return tuple(
        _cleanup_report_fact_from_row(conn, row)
        for row in conn.execute(
            """
            SELECT *
            FROM cleanup_reports
            WHERE run_uri = ?
            ORDER BY recorded_at, report_id
            """,
            (run_uri,),
        )
    )


def _cleanup_report_fact_from_row(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> CleanupReportFact:
    return CleanupReportFact(
        report=CleanupReport.from_dict(_json_loads(cast(str, row["record_json"]))),
        recorded_at=cast(str, row["recorded_at"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
    )


def _cleanup_result_fact(
    conn: sqlite3.Connection, run_uri: str, result_id: str
) -> CleanupResultFact:
    row = _require_row(
        conn.execute(
            """
            SELECT *
            FROM cleanup_results
            WHERE run_uri = ? AND result_id = ?
            """,
            (run_uri, result_id),
        ).fetchone(),
        "unknown cleanup result",
    )
    return _cleanup_result_fact_from_row(conn, row)


def _cleanup_result_facts(
    conn: sqlite3.Connection, run_uri: str
) -> tuple[CleanupResultFact, ...]:
    return tuple(
        _cleanup_result_fact_from_row(conn, row)
        for row in conn.execute(
            """
            SELECT *
            FROM cleanup_results
            WHERE run_uri = ?
            ORDER BY recorded_at, result_id
            """,
            (run_uri,),
        )
    )


def _cleanup_result_fact_from_row(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> CleanupResultFact:
    return CleanupResultFact(
        result=CleanupResult.from_dict(_json_loads(cast(str, row["record_json"]))),
        recorded_at=cast(str, row["recorded_at"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
    )


def _recovery_records(
    conn: sqlite3.Connection, run_uri: str
) -> tuple[RecoveryRecord, ...]:
    return tuple(
        RecoveryRecord(
            recovery_id=cast(str, row["recovery_id"]),
            kind=RecoveryKind(cast(str, row["kind"])),
            reason=LifecycleReason.from_dict(
                _json_loads(cast(str, row["reason_json"]))
            ),
            detected_at=cast(str, row["detected_at"]),
            revision=_revision_for(conn, cast(int, row["revision_sequence"])),
            run_uri=run_uri,
            stage_name=cast(str | None, row["stage_name"]),
            attempt_id=cast(str | None, row["attempt_id"]),
        )
        for row in conn.execute(
            """
            SELECT *
            FROM recovery_records
            WHERE run_uri = ?
            ORDER BY recovery_id
            """,
            (run_uri,),
        )
    )


def _audit_event_from_row(row: sqlite3.Row, *, run_uri: str) -> PipelineEventRecord:
    if "event_json" in row.keys() and row["event_json"] is not None:
        return PipelineEventRecord.from_dict(_json_loads(cast(str, row["event_json"])))
    payload = _json_loads(cast(str, row["payload_json"]))
    if not isinstance(payload, Mapping):
        raise AuthorityRepositoryError("stored audit event payload must be a mapping")
    return PipelineEventRecord(
        run_uri=run_uri,
        sequence=cast(int, row["sequence"]),
        timestamp=cast(str, row["timestamp"]),
        scope=EventScope.from_dict(_json_loads(cast(str, row["scope_json"]))),
        event_type=cast(str, row["event_type"]),
        payload=cast(Mapping[str, PlainData], payload),
    )


def _ensure_audit_event_json_column(conn: sqlite3.Connection) -> None:
    table_info = tuple(conn.execute("PRAGMA table_info(audit_events)"))
    columns = {cast(str, row["name"]) for row in table_info}
    if "event_json" not in columns:
        conn.execute("ALTER TABLE audit_events ADD COLUMN event_json TEXT")
        columns.add("event_json")
    pk_columns = {cast(str, row["name"]) for row in table_info if row["pk"]}
    if pk_columns != {"run_uri", "sequence"}:
        _migrate_audit_events_to_per_run_primary_key(conn)


def _migrate_audit_events_to_per_run_primary_key(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_audit_events_run")
    conn.execute("ALTER TABLE audit_events RENAME TO audit_events_legacy_migration")
    conn.execute(
        """
        CREATE TABLE audit_events (
            sequence INTEGER NOT NULL,
            run_uri TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            event_json TEXT,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY(run_uri, sequence)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO audit_events (
            sequence, run_uri, timestamp, scope_json, event_type, payload_json,
            event_json, revision_sequence
        )
        SELECT sequence, run_uri, timestamp, scope_json, event_type, payload_json,
            event_json, revision_sequence
        FROM audit_events_legacy_migration
        """
    )
    conn.execute("DROP TABLE audit_events_legacy_migration")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_run
            ON audit_events(run_uri, sequence)
        """
    )


def _require_no_repository_cancellation_epoch(
    conn: sqlite3.Connection, run_uri: str
) -> None:
    """Fence lifecycle creation while effective cancellation settles."""

    if conn.execute(
        "SELECT 1 FROM cancellation_epochs WHERE run_uri = ?", (run_uri,)
    ).fetchone():
        raise AuthorityRepositoryError("run cancellation epoch is effective")


def _managed_terminal_digest(
    *,
    status: StageStatus,
    reason: LifecycleReason | None,
    outputs: Mapping[str, ArtifactRef],
) -> str:
    payload: dict[str, PlainData] = {
        "status": status.value,
        "reason": None if reason is None else reason.to_dict(),
        "outputs": {
            name: artifact.to_dict() for name, artifact in sorted(outputs.items())
        },
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _next_audit_event_sequence(conn: sqlite3.Connection, *, run_uri: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sequence), 0) + 1
        FROM audit_events
        WHERE run_uri = ?
        """,
        (run_uri,),
    ).fetchone()
    return cast(int, row[0])


def _require_row(row: sqlite3.Row | None, message: str) -> sqlite3.Row:
    if row is None:
        raise AuthorityRepositoryError(message)
    return row


def _timestamp_expired(expires_at: str, now: str) -> bool:
    return parse_timestamp(expires_at) <= parse_timestamp(now)


def _add_seconds(timestamp: str, seconds: int) -> str:
    return utc_timestamp(parse_timestamp(timestamp) + timedelta(seconds=seconds))


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise AuthorityRepositoryError("stored repository JSON is invalid") from exc


def _json_dumps_or_none(value: LifecycleReason | None) -> str | None:
    if value is None:
        return None
    return _json_dumps(value.to_dict())


def _reason_from_json(value: str | None) -> LifecycleReason | None:
    if value is None:
        return None
    return LifecycleReason.from_dict(_json_loads(value))


def _corrupt_failure(
    message: str, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure:
    return AuthorityRepositoryCompatibilityFailure(
        kind=AuthorityRepositoryCompatibilityKind.CORRUPT,
        message=message,
        current_version=current_version,
    )


def _coerce_kind(value: object, field: str) -> AuthorityRepositoryCompatibilityKind:
    if isinstance(value, AuthorityRepositoryCompatibilityKind):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    try:
        return AuthorityRepositoryCompatibilityKind(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field} {value!r}") from exc


def _database_name(value: object) -> str:
    name = _non_empty(value, "database_name")
    if Path(name).name != name:
        raise ValueError("database_name must not include path separators")
    return name


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _positive_seconds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("lease_ttl_seconds must be positive")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise ValueError(f"{field} must contain plain data") from exc
    if not isinstance(normalized, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "AUTHORITY_REPOSITORY_DB_NAME",
    "AUTHORITY_REPOSITORY_SCHEMA_VERSION",
    "AuthorityRepository",
    "AuthorityRepositoryCompatibilityError",
    "AuthorityRepositoryCompatibilityFailure",
    "AuthorityRepositoryCompatibilityKind",
    "AuthorityRepositoryError",
    "AuthorityRepositoryIdentity",
    "generate_service_generation",
    "initialize_authority_repository",
]
