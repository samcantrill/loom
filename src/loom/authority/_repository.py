"""Private SQLite repository foundation for the authority service."""

from __future__ import annotations

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

from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.status import RunStatus
from loom.pipeline.stores.authority import StatusTransition
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    RecoveryKind,
    RecoveryRecord,
)
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp


AUTHORITY_REPOSITORY_SCHEMA_VERSION = 2
AUTHORITY_REPOSITORY_DB_NAME = "authority.sqlite3"
_SQLITE_TIMEOUT_SECONDS = 30.0
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
}
_REQUIRED_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "service_generation",
        "created_at",
        "updated_at",
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
    ) -> BackendRevision:
        """Persist a newly admitted run and return its initial revision."""

        run_uri = _non_empty(run_uri, "run_uri")
        run_status = RunStatus(status)
        run_metadata = _plain_mapping(metadata or {}, "metadata")
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT 1 FROM authority_runs WHERE run_uri = ?",
                (run_uri,),
            ).fetchone()
            if existing is not None:
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
                    _json_dumps(dict(run_metadata)),
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
            )

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
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
            raise AuthorityRepositoryError(
                "record must be a SubmittedOperationRecord"
            )
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
            current = _current_run_revision(conn, run_uri)
            _require_expected_revision(current, expected_revision)
            revision = self._next_revision(conn)
            timestamp = event.timestamp or self._now()
            payload = cast(
                Mapping[str, PlainData],
                thaw_plain_data(event.payload, path="event.payload"),
            )
            cursor = conn.execute(
                """
                INSERT INTO audit_events (
                    run_uri, timestamp, scope_json, event_type, payload_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_uri,
                    timestamp,
                    _json_dumps(event.scope.to_dict()),
                    event.event_type,
                    _json_dumps(payload),
                    revision.sequence,
                ),
            )
            _touch_run(conn, run_uri=run_uri, revision=revision)
            return PipelineEventRecord(
                run_uri=run_uri,
                sequence=cast(int, cursor.lastrowid),
                timestamp=timestamp,
                scope=event.scope,
                event_type=event.event_type,
                payload=payload,
            )

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
            resolved_id = candidate_id or f"cleanup-{revision.sequence}-{uuid.uuid4().hex[:12]}"
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

    def list_cleanup_candidates(
        self, run_uri: str
    ) -> tuple[CleanupCandidate, ...]:
        """List persisted cleanup candidates for one run."""

        run_uri = _non_empty(run_uri, "run_uri")
        with self._read_connection() as conn:
            _require_run_row(conn, run_uri)
            return _cleanup_candidates(conn, run_uri)

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
            resolved_id = recovery_id or f"recovery-{revision.sequence}-{uuid.uuid4().hex[:12]}"
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
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uri TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
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
        CREATE INDEX IF NOT EXISTS idx_recovery_records_run
            ON recovery_records(run_uri, recovery_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_run
            ON audit_events(run_uri, sequence)
        """,
    )
    for statement in schema_statements:
        conn.execute(statement)
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


def _insert_metadata_if_missing(
    conn: sqlite3.Connection, key: str, value: str
) -> None:
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
            for row in conn.execute(
                "SELECT key, value FROM repository_metadata"
            )
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
    conn: sqlite3.Connection, *, run_uri: str, schema_version: int
) -> AuthoritativeRunSnapshot:
    run_row = _require_run_row(conn, run_uri)
    revision = _revision_for(conn, cast(int, run_row["updated_revision_sequence"]))
    return AuthoritativeRunSnapshot(
        run_uri=run_uri,
        status=RunStatus(cast(str, run_row["status"])),
        schema_version=schema_version,
        revision=revision,
        stages=(),
        submitted_operations=_submitted_operations(conn, run_uri),
        cleanup_candidates=_cleanup_candidates(conn, run_uri),
    )


def _require_run_row(conn: sqlite3.Connection, run_uri: str) -> sqlite3.Row:
    return _require_row(
        conn.execute(
            "SELECT * FROM authority_runs WHERE run_uri = ?",
            (run_uri,),
        ).fetchone(),
        "unknown run",
    )


def _current_run_revision(
    conn: sqlite3.Connection, run_uri: str
) -> BackendRevision:
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


def _audit_event_from_row(
    row: sqlite3.Row, *, run_uri: str
) -> PipelineEventRecord:
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


def _coerce_kind(
    value: object, field: str
) -> AuthorityRepositoryCompatibilityKind:
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
