"""Run-local SQLite implementation of the per-run authority contract."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp

from .authority import (
    AttemptAllocation,
    AuthorityStoreError,
    OutputCommit,
    StatusTransition,
)
from .capabilities import (
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
)
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
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
from .reliability_facts import (
    reliability_payload_matches,
    reliability_policy_fact_key,
    reliability_status_detail_key,
    validate_policy_fact_run,
    validate_retry_decision_run,
    validate_status_detail_run,
    validate_timeout_outcome_run,
    validate_transaction_run,
)
from .run_uri import run_uri_to_path
from .schema_policy import (
    AUTHORITY_SCHEMA_VERSION,
    AuthoritySchemaCheck,
    AuthoritySchemaError,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
)


_AUTHORITY_DIR = ".loom"
_AUTHORITY_DB_NAME = "authority.sqlite3"
_SQLITE_TIMEOUT_SECONDS = 30.0

_SUPPORTED_PER_RUN_CAPABILITIES = (
    BackendCapability.RUN_ADMISSION,
    BackendCapability.ATOMIC_TRANSITIONS,
    BackendCapability.ATTEMPT_ALLOCATION,
    BackendCapability.RUN_LEASES,
    BackendCapability.STAGE_LEASES,
    BackendCapability.LEASE_TTL,
    BackendCapability.FENCING_TOKENS,
    BackendCapability.BACKEND_LEASE_TIME,
    BackendCapability.ATOMIC_OUTPUT_COMMIT,
    BackendCapability.ARTIFACT_FACTS,
    BackendCapability.RELIABILITY_FACTS,
    BackendCapability.SUBMITTED_OPERATIONS,
    BackendCapability.REVISIONED_SNAPSHOTS,
    BackendCapability.MONOTONIC_REVISIONS,
    BackendCapability.RECOVERY_SCANS,
    BackendCapability.CONSISTENT_READS,
    BackendCapability.TRANSACTION_ISOLATION,
    BackendCapability.CLOCK_SEMANTICS,
    BackendCapability.AUDIT_EVENTS,
    BackendCapability.PER_RUN_COORDINATION,
    BackendCapability.SINGLE_HOST_AUTHORITY,
)

_ATTEMPT_ALLOCATABLE_STAGE_STATUSES = frozenset(
    {
        StageStatus.FAILED,
        StageStatus.PENDING,
        StageStatus.RUNNING,
        StageStatus.SUBMITTED,
    }
)

_REQUIRED_SCHEMA_COLUMNS = {
    "metadata": frozenset({"key", "value"}),
    "revisions": frozenset({"sequence", "token", "created_at"}),
    "run_state": frozenset(
        {
            "id",
            "status",
            "metadata_json",
            "created_revision_sequence",
            "updated_revision_sequence",
            "reason_json",
        }
    ),
    "stages": frozenset({"stage_name", "status", "revision_sequence", "reason_json"}),
    "attempts": frozenset(
        {
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
    "leases": frozenset(
        {
            "lease_id",
            "kind",
            "owner_id",
            "fencing_token",
            "acquired_at",
            "renewed_at",
            "expires_at",
            "state",
            "stage_name",
            "attempt_id",
            "revision_sequence",
            "reason_json",
        }
    ),
    "submitted_operations": frozenset(
        {"submission_id", "record_json", "revision_sequence"}
    ),
    "commits": frozenset(
        {
            "commit_id",
            "stage_name",
            "attempt_id",
            "committed_at",
            "revision_sequence",
            "output_names_json",
            "materialized_refs_json",
        }
    ),
    "artifact_facts": frozenset(
        {
            "id",
            "stage_name",
            "artifact_name",
            "artifact_json",
            "commit_id",
            "revision_sequence",
        }
    ),
    "cleanup_candidates": frozenset(
        {
            "candidate_id",
            "kind",
            "uri",
            "reason_json",
            "recorded_at",
            "revision_sequence",
        }
    ),
    "audit_events": frozenset(
        {
            "sequence",
            "timestamp",
            "scope_json",
            "event_type",
            "payload_json",
            "revision_sequence",
        }
    ),
    "reliability_policy_facts": frozenset(
        {
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
            "outcome_id",
            "transaction_id",
            "stage_name",
            "attempt_number",
            "record_json",
            "revision_sequence",
        }
    ),
}


class SQLitePerRunAuthorityStore:
    """SQLite-backed per-run authority store.

    The database location and schema are private implementation details. The
    class intentionally is not re-exported from ``loom.pipeline.stores`` so the
    package root remains import-light.
    """

    def __init__(
        self,
        run_uri: str | None = None,
        *,
        clock: Callable[[], datetime | str] | None = None,
    ) -> None:
        self._run_uri = run_uri
        self._clock = clock
        self._lease_run_uris: dict[str, str] = {}

    def capabilities(self) -> BackendCapabilitySet:
        records: list[BackendCapabilityRecord] = [
            BackendCapabilityRecord(
                capability=capability,
                scope=CapabilityScope.PER_RUN,
            )
            for capability in _SUPPORTED_PER_RUN_CAPABILITIES
        ]
        records.append(
            BackendCapabilityRecord(
                capability=BackendCapability.MATERIALIZATION_REFS,
                scope=CapabilityScope.PER_RUN,
                support=CapabilitySupport.UNSUPPORTED,
                message=(
                    "the SQLite authority backend records committed artifact facts "
                    "but does not materialize payload references in Phase 2"
                ),
            )
        )
        for capability in (
            BackendCapability.RUN_ADMISSION,
            BackendCapability.CROSS_RUN_COORDINATION,
            BackendCapability.GLOBAL_COUNTERS,
            BackendCapability.MULTI_HOST_AUTHORITY,
            BackendCapability.SERVICE_ENDPOINT,
            BackendCapability.SHARED_FILESYSTEM_SAFE,
            BackendCapability.DEFERRED_FINALIZATION,
        ):
            records.append(
                BackendCapabilityRecord(
                    capability=capability,
                    scope=CapabilityScope.CROSS_RUN,
                    support=CapabilitySupport.UNSUPPORTED,
                    message=(
                        "the run-local SQLite authority backend does not own "
                        "workspace or sweep coordination facts"
                    ),
                )
            )
        return BackendCapabilitySet(
            backend_name="sqlite-per-run-authority",
            records=tuple(records),
        )

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
        database_path = _authority_database_path(run_uri)
        if not database_path.exists():
            return AuthoritySchemaCheck(
                current_version=AUTHORITY_SCHEMA_VERSION,
                found_version=None,
                failure=AuthoritySchemaFailure(
                    kind=AuthoritySchemaFailureKind.MISSING,
                    message="SQLite authority database is missing",
                    current_version=AUTHORITY_SCHEMA_VERSION,
                ),
            )
        try:
            with self._connect(database_path) as conn:
                return _check_schema_connection(conn)
        except sqlite3.DatabaseError:
            return AuthoritySchemaCheck(
                current_version=AUTHORITY_SCHEMA_VERSION,
                found_version=None,
                failure=AuthoritySchemaFailure(
                    kind=AuthoritySchemaFailureKind.INVALID,
                    message="SQLite authority database is not readable",
                    current_version=AUTHORITY_SCHEMA_VERSION,
                ),
            )

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision:
        self._bind_run_uri(run_uri)
        database_path = _authority_database_path(run_uri)
        database_exists = database_path.exists()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_connection(
            database_path, initialize=not database_exists
        ) as conn:
            _raise_for_schema(conn)
            existing = conn.execute("SELECT 1 FROM run_state WHERE id = 1").fetchone()
            if existing is not None:
                raise AuthorityStoreError(f"run already exists: {run_uri}")
            revision = self._next_revision(conn)
            conn.execute(
                """
                INSERT INTO run_state (
                    id, status, metadata_json, created_revision_sequence,
                    updated_revision_sequence, reason_json
                )
                VALUES (1, ?, ?, ?, ?, NULL)
                """,
                (
                    RunStatus(status).value,
                    _json_dumps(_plain_mapping(metadata or {}, "metadata")),
                    revision.sequence,
                    revision.sequence,
                ),
            )
            return revision

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return self.snapshot(run_uri)

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        self._bind_run_uri(run_uri)
        with self._transaction(run_uri) as conn:
            current = _require_run_status(conn)
            if current is not RunStatus(from_status):
                raise AuthorityStoreError("stale run transition")
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE run_state
                SET status = ?, updated_revision_sequence = ?, reason_json = ?
                WHERE id = 1
                """,
                (
                    RunStatus(to_status).value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                ),
            )
            return StatusTransition(
                run_uri=run_uri,
                previous_status=current,
                status=RunStatus(to_status),
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
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        self._bind_run_uri(run_uri)
        _non_empty(stage_name, "stage_name")
        with self._transaction(run_uri) as conn:
            row = conn.execute(
                "SELECT status FROM stages WHERE stage_name = ?",
                (stage_name,),
            ).fetchone()
            current = None if row is None else StageStatus(cast(str, row["status"]))
            expected = None if from_status is None else StageStatus(from_status)
            if current is not expected:
                raise AuthorityStoreError("stale stage transition")
            revision = self._next_revision(conn)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO stages (
                        stage_name, status, revision_sequence, reason_json
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        stage_name,
                        StageStatus(to_status).value,
                        revision.sequence,
                        _json_dumps_or_none(reason),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE stages
                    SET status = ?, revision_sequence = ?, reason_json = ?
                    WHERE stage_name = ?
                    """,
                    (
                        StageStatus(to_status).value,
                        revision.sequence,
                        _json_dumps_or_none(reason),
                        stage_name,
                    ),
                )
            _touch_run(conn, revision)
            return StatusTransition(
                run_uri=run_uri,
                stage_name=stage_name,
                previous_status=current,
                status=StageStatus(to_status),
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
    ) -> AttemptAllocation:
        self._bind_run_uri(run_uri)
        _non_empty(stage_name, "stage_name")
        _non_empty(owner_id, "owner_id")
        if lease_ttl_seconds is not None:
            _positive_seconds(lease_ttl_seconds)
        with self._transaction(run_uri) as conn:
            now = self._now()
            active = _active_stage_lease_row(conn, stage_name, now)
            if active is not None:
                raise AuthorityStoreError("stage already has an active lease")
            existing_commit = conn.execute(
                "SELECT 1 FROM commits WHERE stage_name = ?",
                (stage_name,),
            ).fetchone()
            if existing_commit is not None:
                raise AuthorityStoreError("stage already has an output commit")
            stage_row = conn.execute(
                "SELECT status FROM stages WHERE stage_name = ?",
                (stage_name,),
            ).fetchone()
            if stage_row is not None:
                stage_status = StageStatus(cast(str, stage_row["status"]))
                if stage_status not in _ATTEMPT_ALLOCATABLE_STAGE_STATUSES:
                    raise AuthorityStoreError("stage is already terminal")
            attempt_number = _next_attempt_number(conn, stage_name)
            revision = self._next_revision(conn)
            attempt_id = f"{stage_name}-{attempt_number}"
            conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id, stage_name, attempt_number, status, owner_id,
                    created_at, revision_sequence, reason_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
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
                stage_name=stage_name,
                status=StageStatus.RUNNING,
                revision=revision,
                reason=None,
            )
            lease = None
            if lease_ttl_seconds is not None:
                lease = self._insert_lease(
                    conn,
                    run_uri=run_uri,
                    kind=LeaseKind.STAGE,
                    owner_id=owner_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                    revision=revision,
                    now=now,
                    stage_name=stage_name,
                    attempt_id=attempt_id,
                )
            _touch_run(conn, revision)
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

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        self._bind_run_uri(run_uri)
        _non_empty(owner_id, "owner_id")
        _positive_seconds(lease_ttl_seconds)
        with self._transaction(run_uri) as conn:
            now = self._now()
            active = _active_controller_lease_row(conn, now)
            if active is not None:
                raise AuthorityStoreError("run already has an active controller lease")
            revision = self._next_revision(conn)
            lease = self._insert_lease(
                conn,
                run_uri=run_uri,
                kind=LeaseKind.CONTROLLER,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                revision=revision,
                now=now,
            )
            _touch_run(conn, revision)
            return lease

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        run_uri = self._run_uri_for_lease(lease_id)
        _positive_seconds(lease_ttl_seconds)
        with self._transaction(run_uri) as conn:
            row = self._require_active_lease_row(
                conn,
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityStoreError("lease has expired")
            revision = self._next_revision(conn)
            expires_at = _add_seconds(now, lease_ttl_seconds)
            conn.execute(
                """
                UPDATE leases
                SET renewed_at = ?, expires_at = ?, revision_sequence = ?
                WHERE lease_id = ?
                """,
                (now, expires_at, revision.sequence, lease_id),
            )
            _touch_run(conn, revision)
            return _lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
                    ).fetchone(),
                    "unknown lease",
                ),
                run_uri=run_uri,
                revision=_revision_for(conn, revision.sequence),
            )

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        return self._finish_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            state=LeaseState.RELEASED,
            reason=reason,
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        if not isinstance(reason, LifecycleReason):
            raise AuthorityStoreError("reason must be a LifecycleReason")
        return self._finish_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            state=LeaseState.FAILED,
            reason=reason,
        )

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision:
        self._bind_run_uri(run_uri)
        if not isinstance(record, SubmittedOperationRecord):
            raise AuthorityStoreError("record must be a SubmittedOperationRecord")
        with self._transaction(run_uri) as conn:
            revision = self._next_revision(conn)
            data = record.to_dict()
            data["run_uri"] = run_uri
            conn.execute(
                """
                INSERT INTO submitted_operations (
                    submission_id, record_json, revision_sequence
                )
                VALUES (?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    record_json = excluded.record_json,
                    revision_sequence = excluded.revision_sequence
                """,
                (record.submission_id, _json_dumps(data), revision.sequence),
            )
            _touch_run(conn, revision)
            return revision

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        self._bind_run_uri(run_uri)
        _non_empty(submission_id, "submission_id")
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            row = conn.execute(
                """
                SELECT record_json
                FROM submitted_operations
                WHERE submission_id = ?
                """,
                (submission_id,),
            ).fetchone()
            if row is None:
                return None
            return _submitted_from_json(cast(str, row["record_json"]), run_uri)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        self._bind_run_uri(run_uri)
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            rows = conn.execute(
                "SELECT record_json FROM submitted_operations ORDER BY submission_id"
            ).fetchall()
            return tuple(
                _submitted_from_json(cast(str, row["record_json"]), run_uri)
                for row in rows
            )

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        self._bind_run_uri(run_uri)
        if not isinstance(fact, ReliabilityPolicyFact):
            raise AuthorityStoreError("fact must be a ReliabilityPolicyFact")
        validate_policy_fact_run(fact, run_uri)
        with self._transaction(run_uri) as conn:
            key = reliability_policy_fact_key(fact)
            return self._insert_reliability_fact(
                conn,
                table="reliability_policy_facts",
                key_column="fact_key",
                key=key,
                payload_column="fact_json",
                payload=fact.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_policy_facts (
                        fact_key, scope, stage_name, attempt_number, recorded_at,
                        fact_json, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
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
        self._bind_run_uri(run_uri)
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            if stage_name is None:
                rows = conn.execute(
                    """
                    SELECT fact_json
                    FROM reliability_policy_facts
                    ORDER BY scope, COALESCE(stage_name, ''), COALESCE(attempt_number, 0), recorded_at
                    """
                ).fetchall()
            else:
                _non_empty(stage_name, "stage_name")
                rows = conn.execute(
                    """
                    SELECT fact_json
                    FROM reliability_policy_facts
                    WHERE stage_name = ?
                    ORDER BY scope, COALESCE(attempt_number, 0), recorded_at
                    """,
                    (stage_name,),
                ).fetchall()
            return tuple(
                ReliabilityPolicyFact.from_dict(_json_loads(cast(str, row["fact_json"])))
                for row in rows
            )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        self._bind_run_uri(run_uri)
        if not isinstance(detail, ReliabilityStatusDetail):
            raise AuthorityStoreError("detail must be a ReliabilityStatusDetail")
        validate_status_detail_run(detail, run_uri)
        with self._transaction(run_uri) as conn:
            key = reliability_status_detail_key(detail)
            return self._insert_reliability_fact(
                conn,
                table="reliability_status_details",
                key_column="fact_key",
                key=key,
                payload_column="detail_json",
                payload=detail.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_status_details (
                        fact_key, stage_name, attempt_number, created_at,
                        detail_json, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
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
        self._bind_run_uri(run_uri)
        if not isinstance(transaction, StageAttemptTransaction):
            raise AuthorityStoreError("transaction must be a StageAttemptTransaction")
        validate_transaction_run(transaction, run_uri)
        with self._transaction(run_uri) as conn:
            return self._insert_reliability_fact(
                conn,
                table="reliability_transactions",
                key_column="transaction_id",
                key=transaction.transaction_id,
                payload_column="record_json",
                payload=transaction.to_dict(),
                insert_sql="""
                    INSERT INTO reliability_transactions (
                        transaction_id, stage_name, attempt_number,
                        causal_parent_id, record_json, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
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
        _non_empty(transaction_id, "transaction_id")
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
                raise AuthorityStoreError(
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
        self._bind_run_uri(run_uri)
        if not isinstance(decision, RetryDecisionRecord):
            raise AuthorityStoreError("decision must be a RetryDecisionRecord")
        validate_retry_decision_run(decision, run_uri)
        with self._transaction(run_uri) as conn:
            return self._insert_reliability_fact(
                conn,
                table="retry_decisions",
                key_column="decision_id",
                key=decision.decision_id,
                payload_column="record_json",
                payload=decision.to_dict(),
                insert_sql="""
                    INSERT INTO retry_decisions (
                        decision_id, transaction_id, stage_name, attempt_number,
                        record_json, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
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
        self._bind_run_uri(run_uri)
        if not isinstance(outcome, TimeoutOutcomeRecord):
            raise AuthorityStoreError("outcome must be a TimeoutOutcomeRecord")
        validate_timeout_outcome_run(outcome, run_uri)
        with self._transaction(run_uri) as conn:
            return self._insert_reliability_fact(
                conn,
                table="timeout_outcomes",
                key_column="outcome_id",
                key=outcome.outcome_id,
                payload_column="record_json",
                payload=outcome.to_dict(),
                insert_sql="""
                    INSERT INTO timeout_outcomes (
                        outcome_id, transaction_id, stage_name, attempt_number,
                        record_json, revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                insert_values=(
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

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        self._bind_run_uri(run_uri)
        _non_empty(stage_name, "stage_name")
        _non_empty(attempt_id, "attempt_id")
        _non_empty(fencing_token, "fencing_token")
        artifacts = tuple((name, artifact) for name, artifact in outputs.items())
        for name, artifact in artifacts:
            _non_empty(name, "output_name")
            if not isinstance(artifact, ArtifactRef):
                raise AuthorityStoreError("outputs must contain ArtifactRef values")
        with self._transaction(run_uri) as conn:
            now = self._now()
            lease_row = _active_stage_lease_row(conn, stage_name, now)
            if lease_row is None:
                expired_lease_row = _stage_lease_row(
                    conn,
                    stage_name=stage_name,
                    attempt_id=attempt_id,
                    fencing_token=fencing_token,
                )
                if expired_lease_row is not None and _timestamp_expired(
                    cast(str, expired_lease_row["expires_at"]), now
                ):
                    raise AuthorityStoreError("stage lease has expired")
                raise AuthorityStoreError(
                    "missing active stage lease for output commit"
                )
            if cast(str, lease_row["attempt_id"]) != attempt_id:
                raise AuthorityStoreError(
                    "missing active stage lease for output commit"
                )
            if cast(str, lease_row["fencing_token"]) != fencing_token:
                raise AuthorityStoreError("stale or foreign lease token")
            if _timestamp_expired(cast(str, lease_row["expires_at"]), now):
                raise AuthorityStoreError("stage lease has expired")
            attempt_row = conn.execute(
                """
                SELECT * FROM attempts
                WHERE attempt_id = ? AND stage_name = ?
                """,
                (attempt_id, stage_name),
            ).fetchone()
            if attempt_row is None:
                raise AuthorityStoreError("unknown stage attempt")
            if StageStatus(cast(str, attempt_row["status"])) is not StageStatus.RUNNING:
                raise AuthorityStoreError("stage attempt is not running")
            stage_row = conn.execute(
                "SELECT status FROM stages WHERE stage_name = ?",
                (stage_name,),
            ).fetchone()
            if stage_row is None or StageStatus(cast(str, stage_row["status"])) not in {
                StageStatus.RUNNING,
                StageStatus.SUBMITTED,
            }:
                raise AuthorityStoreError("stage is not running")
            existing_commit = conn.execute(
                "SELECT 1 FROM commits WHERE stage_name = ?",
                (stage_name,),
            ).fetchone()
            if existing_commit is not None:
                raise AuthorityStoreError("stage already has an output commit")
            revision = self._next_revision(conn)
            commit_id = f"{stage_name}-{attempt_id}-commit-{revision.sequence}"
            output_names = tuple(name for name, _artifact in artifacts)
            conn.execute(
                """
                INSERT INTO commits (
                    commit_id, stage_name, attempt_id, committed_at,
                    revision_sequence, output_names_json, materialized_refs_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit_id,
                    stage_name,
                    attempt_id,
                    now,
                    revision.sequence,
                    _json_dumps(list(output_names)),
                    _json_dumps([]),
                ),
            )
            for name, artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO artifact_facts (
                        stage_name, artifact_name, artifact_json, commit_id,
                        revision_sequence
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        stage_name,
                        name,
                        _json_dumps(artifact.to_dict()),
                        commit_id,
                        revision.sequence,
                    ),
                )
            conn.execute(
                """
                UPDATE attempts
                SET status = ?, revision_sequence = ?, reason_json = ?
                WHERE attempt_id = ?
                """,
                (
                    StageStatus.SUCCEEDED.value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    attempt_id,
                ),
            )
            _upsert_stage(
                conn,
                stage_name=stage_name,
                status=StageStatus.SUCCEEDED,
                revision=revision,
                reason=reason,
            )
            conn.execute(
                """
                UPDATE leases
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
            _touch_run(conn, revision)
            commit = OutputCommitRecord(
                commit_id=commit_id,
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
                committed_at=now,
                revision=revision,
                output_names=output_names,
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

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord:
        self._bind_run_uri(run_uri)
        if not isinstance(event, PipelineEvent):
            raise AuthorityStoreError("event must be a PipelineEvent")
        with self._transaction(run_uri) as conn:
            revision = self._next_revision(conn)
            timestamp = event.timestamp or self._now()
            payload = cast(
                Mapping[str, PlainData],
                thaw_plain_data(event.payload, path="event.payload"),
            )
            cursor = conn.execute(
                """
                INSERT INTO audit_events (
                    timestamp, scope_json, event_type, payload_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    _json_dumps(event.scope.to_dict()),
                    event.event_type,
                    _json_dumps(payload),
                    revision.sequence,
                ),
            )
            _touch_run(conn, revision)
            return PipelineEventRecord(
                run_uri=run_uri,
                sequence=cast(int, cursor.lastrowid),
                timestamp=timestamp,
                scope=event.scope,
                event_type=event.event_type,
                payload=payload,
            )

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        self._bind_run_uri(run_uri)
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            return _snapshot(conn, run_uri=run_uri, now=self._now())

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        self._bind_run_uri(run_uri)
        now = self._now()
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            snapshot_revision = _current_run_revision(conn)
            records: list[RecoveryRecord] = []
            for row in conn.execute(
                """
                SELECT *
                FROM leases
                WHERE state = ?
                ORDER BY lease_id
                """,
                (LeaseState.ACTIVE.value,),
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
                        revision=snapshot_revision,
                        run_uri=run_uri,
                        stage_name=cast(str | None, row["stage_name"]),
                        attempt_id=cast(str | None, row["attempt_id"]),
                    )
                )
            for row in conn.execute(
                """
                SELECT *
                FROM attempts
                WHERE status IN (?, ?)
                ORDER BY stage_name, attempt_number
                """,
                (
                    StageStatus.RUNNING.value,
                    StageStatus.SUBMITTED.value,
                ),
            ):
                attempt_id = cast(str, row["attempt_id"])
                stage_name = cast(str, row["stage_name"])
                if (
                    _active_attempt_lease_row(
                        conn,
                        stage_name=stage_name,
                        attempt_id=attempt_id,
                        now=now,
                    )
                    is not None
                ):
                    continue
                records.append(
                    RecoveryRecord(
                        recovery_id=f"abandoned-{attempt_id}",
                        kind=RecoveryKind.ABANDONED_ATTEMPT,
                        reason=LifecycleReason(code="attempt_without_active_lease"),
                        detected_at=now,
                        revision=snapshot_revision,
                        run_uri=run_uri,
                        stage_name=stage_name,
                        attempt_id=attempt_id,
                    )
                )
            for row in conn.execute(
                """
                SELECT submitted_operations.record_json
                FROM submitted_operations
                ORDER BY submitted_operations.submission_id
                """
            ):
                record = _submitted_from_json(cast(str, row["record_json"]), run_uri)
                if record.active:
                    records.append(
                        RecoveryRecord(
                            recovery_id=f"submitted-{record.submission_id}",
                            kind=RecoveryKind.INTERRUPTED_SUBMISSION,
                            reason=LifecycleReason(code="submitted_operation_active"),
                            detected_at=now,
                            revision=snapshot_revision,
                            run_uri=run_uri,
                        )
                    )
            return tuple(records)

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        self._bind_run_uri(run_uri)
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            return _cleanup_candidates(conn)

    def _finish_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        state: LeaseState,
        reason: LifecycleReason | None,
    ) -> LeaseRecord:
        run_uri = self._run_uri_for_lease(lease_id)
        with self._transaction(run_uri) as conn:
            row = self._require_active_lease_row(
                conn,
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            now = self._now()
            if _timestamp_expired(cast(str, row["expires_at"]), now):
                raise AuthorityStoreError("lease has expired")
            revision = self._next_revision(conn)
            conn.execute(
                """
                UPDATE leases
                SET state = ?, revision_sequence = ?, reason_json = ?
                WHERE lease_id = ?
                """,
                (
                    LeaseState(state).value,
                    revision.sequence,
                    _json_dumps_or_none(reason),
                    lease_id,
                ),
            )
            _touch_run(conn, revision)
            return _lease_from_row(
                _require_row(
                    conn.execute(
                        "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
                    ).fetchone(),
                    "unknown lease",
                ),
                run_uri=run_uri,
                revision=revision,
            )

    def _require_active_lease_row(
        self,
        conn: sqlite3.Connection,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
    ) -> sqlite3.Row:
        _non_empty(lease_id, "lease_id")
        _non_empty(owner_id, "owner_id")
        _non_empty(fencing_token, "fencing_token")
        row = conn.execute(
            "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        if row is None:
            raise AuthorityStoreError(f"unknown lease: {lease_id}")
        if (
            cast(str, row["owner_id"]) != owner_id
            or cast(str, row["fencing_token"]) != fencing_token
        ):
            raise AuthorityStoreError("stale or foreign lease token")
        if LeaseState(cast(str, row["state"])) is not LeaseState.ACTIVE:
            raise AuthorityStoreError("lease is not active")
        return cast(sqlite3.Row, row)

    def _insert_lease(
        self,
        conn: sqlite3.Connection,
        *,
        run_uri: str,
        kind: LeaseKind,
        owner_id: str,
        lease_ttl_seconds: int,
        revision: BackendRevision,
        now: str,
        stage_name: str | None = None,
        attempt_id: str | None = None,
    ) -> LeaseRecord:
        lease_id = f"lease-{revision.sequence}-{uuid.uuid4().hex[:12]}"
        fencing_token = f"fence-{revision.sequence}-{uuid.uuid4().hex}"
        expires_at = _add_seconds(now, lease_ttl_seconds)
        conn.execute(
            """
            INSERT INTO leases (
                lease_id, kind, owner_id, fencing_token, acquired_at, renewed_at,
                expires_at, state, stage_name, attempt_id, revision_sequence,
                reason_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                lease_id,
                LeaseKind(kind).value,
                owner_id,
                fencing_token,
                now,
                now,
                expires_at,
                LeaseState.ACTIVE.value,
                stage_name,
                attempt_id,
                revision.sequence,
            ),
        )
        self._lease_run_uris[lease_id] = run_uri
        return LeaseRecord(
            lease_id=lease_id,
            kind=LeaseKind(kind),
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

    def _insert_reliability_fact(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        key_column: str,
        key: str,
        payload_column: str,
        payload: Mapping[str, PlainData],
        insert_sql: str,
        insert_values: tuple[object, ...],
    ) -> BackendRevision:
        existing = conn.execute(
            f"SELECT {payload_column}, revision_sequence FROM {table} WHERE {key_column} = ?",
            (key,),
        ).fetchone()
        if existing is not None:
            existing_payload = _json_loads(cast(str, existing[payload_column]))
            if not isinstance(existing_payload, Mapping):
                raise AuthorityStoreError("stored reliability fact must be a mapping")
            if reliability_payload_matches(
                cast(Mapping[str, PlainData], existing_payload),
                payload,
            ):
                return _revision_for(conn, cast(int, existing["revision_sequence"]))
            raise AuthorityStoreError("conflicting reliability fact already exists")
        revision = self._next_revision(conn)
        conn.execute(insert_sql, (*insert_values, revision.sequence))
        _touch_run(conn, revision)
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
        self._bind_run_uri(run_uri)
        with self._read_connection_for_run(run_uri) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            if stage_name is None:
                rows = conn.execute(
                    f"SELECT {payload_column} FROM {table} ORDER BY {order_by}"
                ).fetchall()
            else:
                _non_empty(stage_name, "stage_name")
                rows = conn.execute(
                    f"SELECT {payload_column} FROM {table} WHERE stage_name = ? ORDER BY {order_by}",
                    (stage_name,),
                ).fetchall()
            return tuple(
                parser(_json_loads(cast(str, row[payload_column]))) for row in rows
            )

    def _bind_run_uri(self, run_uri: str) -> str:
        run_uri_to_path(run_uri)
        if self._run_uri is None:
            self._run_uri = run_uri
        elif self._run_uri != run_uri:
            raise AuthorityStoreError(
                "SQLite per-run authority store is bound to another run"
            )
        return run_uri

    def _run_uri_for_lease(self, lease_id: str) -> str:
        _non_empty(lease_id, "lease_id")
        if self._run_uri is not None:
            return self._run_uri
        try:
            return self._lease_run_uris[lease_id]
        except KeyError as exc:
            raise AuthorityStoreError(
                "lease operations require a store bound to the lease run"
            ) from exc

    @contextmanager
    def _read_connection_for_run(self, run_uri: str) -> Iterator[sqlite3.Connection]:
        database_path = _authority_database_path(run_uri)
        if not database_path.exists():
            raise AuthoritySchemaError("SQLite authority database is missing")
        with self._connect(database_path) as conn:
            yield conn

    @contextmanager
    def _transaction(self, run_uri: str) -> Iterator[sqlite3.Connection]:
        database_path = _authority_database_path(run_uri)
        if not database_path.exists():
            raise AuthoritySchemaError("SQLite authority database is missing")
        with self._write_connection(database_path, initialize=False) as conn:
            _raise_for_schema(conn)
            _require_run_status(conn)
            yield conn

    @contextmanager
    def _write_connection(
        self, database_path: Path, *, initialize: bool
    ) -> Iterator[sqlite3.Connection]:
        with self._connect(database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if initialize:
                    _initialize_schema(conn)
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    @contextmanager
    def _connect(self, database_path: Path) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            database_path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _next_revision(self, conn: sqlite3.Connection) -> BackendRevision:
        created_at = self._now()
        seed = uuid.uuid4().hex
        cursor = conn.execute(
            "INSERT INTO revisions (token, created_at) VALUES (?, ?)",
            (seed, created_at),
        )
        sequence = cast(int, cursor.lastrowid)
        token = f"sqlite-rev-{sequence}-{seed}"
        conn.execute(
            "UPDATE revisions SET token = ? WHERE sequence = ?",
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


def _authority_database_path(run_uri: str) -> Path:
    run_root = run_uri_to_path(run_uri)
    return run_root / _AUTHORITY_DIR / _AUTHORITY_DB_NAME


def _initialize_schema(conn: sqlite3.Connection) -> None:
    schema_statements = (
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS revisions (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS run_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_revision_sequence INTEGER NOT NULL,
            updated_revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stages (
            stage_name TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            owner_id TEXT,
            created_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT,
            UNIQUE(stage_name, attempt_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS leases (
            lease_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            fencing_token TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            renewed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            state TEXT NOT NULL,
            stage_name TEXT,
            attempt_id TEXT,
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS submitted_operations (
            submission_id TEXT PRIMARY KEY,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS commits (
            commit_id TEXT PRIMARY KEY,
            stage_name TEXT NOT NULL UNIQUE,
            attempt_id TEXT NOT NULL,
            committed_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            output_names_json TEXT NOT NULL,
            materialized_refs_json TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS artifact_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_name TEXT NOT NULL,
            artifact_name TEXT NOT NULL,
            artifact_json TEXT NOT NULL,
            commit_id TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            UNIQUE(commit_id, artifact_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleanup_candidates (
            candidate_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            reason_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_policy_facts (
            fact_key TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            stage_name TEXT,
            attempt_number INTEGER,
            recorded_at TEXT NOT NULL,
            fact_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_status_details (
            fact_key TEXT PRIMARY KEY,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reliability_transactions (
            transaction_id TEXT PRIMARY KEY,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            causal_parent_id TEXT,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS retry_decisions (
            decision_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS timeout_outcomes (
            outcome_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_attempts_stage
            ON attempts(stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leases_stage
            ON leases(stage_name, state, expires_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leases_attempt
            ON leases(attempt_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_artifact_facts_stage
            ON artifact_facts(stage_name)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_policy_stage
            ON reliability_policy_facts(stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_status_stage
            ON reliability_status_details(stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reliability_transactions_stage
            ON reliability_transactions(stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_retry_decisions_stage
            ON retry_decisions(stage_name, attempt_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_timeout_outcomes_stage
            ON timeout_outcomes(stage_name, attempt_number)
        """,
    )
    for statement in schema_statements:
        conn.execute(statement)
    conn.execute(
        """
        INSERT INTO metadata(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO NOTHING
        """,
        (str(AUTHORITY_SCHEMA_VERSION),),
    )


def _check_schema_connection(conn: sqlite3.Connection) -> AuthoritySchemaCheck:
    try:
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.MISSING,
                message="SQLite authority schema metadata is missing",
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    if row is None:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.MISSING,
                message="SQLite authority schema metadata is missing",
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    raw_version = row["value"]
    try:
        version = int(cast(str, raw_version))
    except (TypeError, ValueError):
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message="SQLite authority schema version is invalid",
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    if version <= 0:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message="SQLite authority schema version is invalid",
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    if version < AUTHORITY_SCHEMA_VERSION:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=version,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.UNSUPPORTED_OLDER,
                message=(
                    f"unsupported older SQLite authority schema {version}; "
                    f"expected {AUTHORITY_SCHEMA_VERSION}"
                ),
                found_version=version,
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    if version > AUTHORITY_SCHEMA_VERSION:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=version,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.UNSUPPORTED_NEWER,
                message=(
                    f"unsupported newer SQLite authority schema {version}; "
                    f"this Loom version supports {AUTHORITY_SCHEMA_VERSION}"
                ),
                found_version=version,
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    shape_failure = _schema_shape_failure(conn)
    if shape_failure is not None:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=version,
            failure=shape_failure,
        )
    return AuthoritySchemaCheck(
        current_version=AUTHORITY_SCHEMA_VERSION,
        found_version=version,
    )


def _schema_shape_failure(conn: sqlite3.Connection) -> AuthoritySchemaFailure | None:
    try:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE type = 'table'
            """
        ).fetchall()
        existing_tables = {cast(str, row["name"]) for row in rows}
        if set(_REQUIRED_SCHEMA_COLUMNS) - existing_tables:
            return _invalid_schema_shape_failure()
        for table_name, expected_columns in _REQUIRED_SCHEMA_COLUMNS.items():
            columns = {
                cast(str, row["name"])
                for row in conn.execute(f"PRAGMA table_info({table_name})")
            }
            if not expected_columns.issubset(columns):
                return _invalid_schema_shape_failure()
    except sqlite3.DatabaseError:
        return _invalid_schema_shape_failure()
    return None


def _invalid_schema_shape_failure() -> AuthoritySchemaFailure:
    return AuthoritySchemaFailure(
        kind=AuthoritySchemaFailureKind.INVALID,
        message="SQLite authority schema is incomplete or invalid",
        current_version=AUTHORITY_SCHEMA_VERSION,
    )


def _raise_for_schema(conn: sqlite3.Connection) -> None:
    check = _check_schema_connection(conn)
    if check.failure is not None:
        raise AuthoritySchemaError(check.failure.message)


def _snapshot(
    conn: sqlite3.Connection, *, run_uri: str, now: str
) -> AuthoritativeRunSnapshot:
    run_row = _require_row(
        conn.execute("SELECT * FROM run_state WHERE id = 1").fetchone(),
        "unknown run",
    )
    revision = _revision_for(conn, cast(int, run_row["updated_revision_sequence"]))
    stage_names = {
        cast(str, row["stage_name"])
        for row in conn.execute("SELECT stage_name FROM stages")
    }
    stage_names.update(
        cast(str, row["stage_name"])
        for row in conn.execute("SELECT DISTINCT stage_name FROM attempts")
    )
    stage_names.update(
        cast(str, row["stage_name"])
        for row in conn.execute("SELECT DISTINCT stage_name FROM commits")
    )
    stage_names.update(
        cast(str, row["stage_name"])
        for row in conn.execute(
            """
            SELECT DISTINCT stage_name
            FROM reliability_policy_facts
            WHERE stage_name IS NOT NULL
            """
        )
    )
    for table_name in (
        "reliability_status_details",
        "reliability_transactions",
        "retry_decisions",
        "timeout_outcomes",
    ):
        stage_names.update(
            cast(str, row["stage_name"])
            for row in conn.execute(f"SELECT DISTINCT stage_name FROM {table_name}")
        )
    stages = tuple(
        _stage_snapshot(conn, run_uri=run_uri, stage_name=stage_name, now=now)
        for stage_name in sorted(stage_names)
    )
    submitted = tuple(
        _submitted_from_json(cast(str, row["record_json"]), run_uri)
        for row in conn.execute(
            "SELECT record_json FROM submitted_operations ORDER BY submission_id"
        )
    )
    return AuthoritativeRunSnapshot(
        run_uri=run_uri,
        status=RunStatus(cast(str, run_row["status"])),
        schema_version=AUTHORITY_SCHEMA_VERSION,
        revision=revision,
        stages=stages,
        submitted_operations=submitted,
        cleanup_candidates=_cleanup_candidates(conn),
        reliability_policy_facts=_reliability_policy_facts(conn, stage_name=None),
    )


def _stage_snapshot(
    conn: sqlite3.Connection, *, run_uri: str, stage_name: str, now: str
) -> StageLifecycleSnapshot:
    stage_row = conn.execute(
        "SELECT * FROM stages WHERE stage_name = ?", (stage_name,)
    ).fetchone()
    if stage_row is None:
        status = StageStatus.PENDING
        revision = _current_run_revision(conn)
        reason = None
    else:
        status = StageStatus(cast(str, stage_row["status"]))
        revision = _revision_for(conn, cast(int, stage_row["revision_sequence"]))
        reason = _reason_from_json(cast(str | None, stage_row["reason_json"]))
    attempt_rows = conn.execute(
        """
        SELECT *
        FROM attempts
        WHERE stage_name = ?
        ORDER BY attempt_number
        """,
        (stage_name,),
    ).fetchall()
    attempts = tuple(
        _attempt_from_row(row, run_uri=run_uri, conn=conn) for row in attempt_rows
    )
    lease_row = _active_stage_lease_row(conn, stage_name, now)
    active_lease = (
        None
        if lease_row is None
        else _lease_from_row(
            lease_row,
            run_uri=run_uri,
            revision=_revision_for(conn, cast(int, lease_row["revision_sequence"])),
        )
    )
    commit_row = conn.execute(
        """
        SELECT *
        FROM commits
        WHERE stage_name = ?
        ORDER BY revision_sequence DESC
        LIMIT 1
        """,
        (stage_name,),
    ).fetchone()
    latest_commit = (
        None
        if commit_row is None
        else _commit_from_row(commit_row, run_uri=run_uri, conn=conn)
    )
    facts = tuple(
        _artifact_fact_from_row(row, conn=conn)
        for row in conn.execute(
            """
            SELECT *
            FROM artifact_facts
            WHERE stage_name = ?
            ORDER BY artifact_name
            """,
            (stage_name,),
        )
    )
    return StageLifecycleSnapshot(
        stage_name=stage_name,
        status=status,
        revision=revision,
        attempts=attempts,
        active_lease=active_lease,
        latest_commit=latest_commit,
        artifact_facts=facts,
        reliability_policy_facts=_reliability_policy_facts(
            conn,
            stage_name=stage_name,
        ),
        reliability_status_details=_reliability_status_details(
            conn,
            stage_name=stage_name,
        ),
        reliability_transactions=_reliability_transactions(
            conn,
            stage_name=stage_name,
        ),
        retry_decisions=_retry_decisions(conn, stage_name=stage_name),
        timeout_outcomes=_timeout_outcomes(conn, stage_name=stage_name),
        reason=reason,
    )


def _attempt_from_row(
    row: sqlite3.Row, *, run_uri: str, conn: sqlite3.Connection
) -> StageAttempt:
    return StageAttempt(
        run_uri=run_uri,
        stage_name=cast(str, row["stage_name"]),
        attempt=cast(int, row["attempt_number"]),
        attempt_id=cast(str, row["attempt_id"]),
        status=StageStatus(cast(str, row["status"])),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        created_at=cast(str, row["created_at"]),
        owner=cast(str | None, row["owner_id"]),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _lease_from_row(
    row: sqlite3.Row, *, run_uri: str, revision: BackendRevision
) -> LeaseRecord:
    return LeaseRecord(
        lease_id=cast(str, row["lease_id"]),
        kind=LeaseKind(cast(str, row["kind"])),
        owner_id=cast(str, row["owner_id"]),
        fencing_token=cast(str, row["fencing_token"]),
        acquired_at=cast(str, row["acquired_at"]),
        renewed_at=cast(str, row["renewed_at"]),
        expires_at=cast(str, row["expires_at"]),
        revision=revision,
        state=LeaseState(cast(str, row["state"])),
        run_uri=run_uri,
        stage_name=cast(str | None, row["stage_name"]),
        attempt_id=cast(str | None, row["attempt_id"]),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _commit_from_row(
    row: sqlite3.Row, *, run_uri: str, conn: sqlite3.Connection
) -> OutputCommitRecord:
    return OutputCommitRecord(
        commit_id=cast(str, row["commit_id"]),
        run_uri=run_uri,
        stage_name=cast(str, row["stage_name"]),
        attempt_id=cast(str, row["attempt_id"]),
        committed_at=cast(str, row["committed_at"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        output_names=tuple(
            cast(str, name) for name in _json_loads(cast(str, row["output_names_json"]))
        ),
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


def _reliability_policy_facts(
    conn: sqlite3.Connection, *, stage_name: str | None
) -> tuple[ReliabilityPolicyFact, ...]:
    if stage_name is None:
        rows = conn.execute(
            """
            SELECT fact_json
            FROM reliability_policy_facts
            WHERE stage_name IS NULL
            ORDER BY scope, recorded_at
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT fact_json
            FROM reliability_policy_facts
            WHERE stage_name = ?
            ORDER BY scope, COALESCE(attempt_number, 0), recorded_at
            """,
            (stage_name,),
        ).fetchall()
    return tuple(
        ReliabilityPolicyFact.from_dict(_json_loads(cast(str, row["fact_json"])))
        for row in rows
    )


def _reliability_status_details(
    conn: sqlite3.Connection, *, stage_name: str
) -> tuple[ReliabilityStatusDetail, ...]:
    return tuple(
        ReliabilityStatusDetail.from_dict(_json_loads(cast(str, row["detail_json"])))
        for row in conn.execute(
            """
            SELECT detail_json
            FROM reliability_status_details
            WHERE stage_name = ?
            ORDER BY attempt_number, created_at
            """,
            (stage_name,),
        )
    )


def _reliability_transactions(
    conn: sqlite3.Connection, *, stage_name: str
) -> tuple[StageAttemptTransaction, ...]:
    return tuple(
        StageAttemptTransaction.from_dict(_json_loads(cast(str, row["record_json"])))
        for row in conn.execute(
            """
            SELECT record_json
            FROM reliability_transactions
            WHERE stage_name = ?
            ORDER BY attempt_number, transaction_id
            """,
            (stage_name,),
        )
    )


def _retry_decisions(
    conn: sqlite3.Connection, *, stage_name: str
) -> tuple[RetryDecisionRecord, ...]:
    return tuple(
        RetryDecisionRecord.from_dict(_json_loads(cast(str, row["record_json"])))
        for row in conn.execute(
            """
            SELECT record_json
            FROM retry_decisions
            WHERE stage_name = ?
            ORDER BY attempt_number, decision_id
            """,
            (stage_name,),
        )
    )


def _timeout_outcomes(
    conn: sqlite3.Connection, *, stage_name: str
) -> tuple[TimeoutOutcomeRecord, ...]:
    return tuple(
        TimeoutOutcomeRecord.from_dict(_json_loads(cast(str, row["record_json"])))
        for row in conn.execute(
            """
            SELECT record_json
            FROM timeout_outcomes
            WHERE stage_name = ?
            ORDER BY attempt_number, outcome_id
            """,
            (stage_name,),
        )
    )


def _cleanup_candidates(conn: sqlite3.Connection) -> tuple[CleanupCandidate, ...]:
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
            "SELECT * FROM cleanup_candidates ORDER BY candidate_id"
        )
    )


def _submitted_from_json(data: str, run_uri: str) -> SubmittedOperationRecord:
    raw = _json_loads(data)
    if not isinstance(raw, dict):
        raise AuthorityStoreError("submitted operation record must be a mapping")
    raw["run_uri"] = run_uri
    return SubmittedOperationRecord.from_dict(raw)


def _revision_for(conn: sqlite3.Connection, sequence: int) -> BackendRevision:
    row = _require_row(
        conn.execute(
            "SELECT sequence, token, created_at FROM revisions WHERE sequence = ?",
            (sequence,),
        ).fetchone(),
        "unknown backend revision",
    )
    return BackendRevision(
        sequence=cast(int, row["sequence"]),
        token=cast(str, row["token"]),
        created_at=cast(str, row["created_at"]),
    )


def _current_run_revision(conn: sqlite3.Connection) -> BackendRevision:
    row = _require_row(
        conn.execute(
            "SELECT updated_revision_sequence FROM run_state WHERE id = 1"
        ).fetchone(),
        "unknown run",
    )
    return _revision_for(conn, cast(int, row["updated_revision_sequence"]))


def _require_run_status(conn: sqlite3.Connection) -> RunStatus:
    row = conn.execute("SELECT status FROM run_state WHERE id = 1").fetchone()
    if row is None:
        raise AuthorityStoreError("unknown run")
    return RunStatus(cast(str, row["status"]))


def _touch_run(conn: sqlite3.Connection, revision: BackendRevision) -> None:
    conn.execute(
        "UPDATE run_state SET updated_revision_sequence = ? WHERE id = 1",
        (revision.sequence,),
    )


def _upsert_stage(
    conn: sqlite3.Connection,
    *,
    stage_name: str,
    status: StageStatus,
    revision: BackendRevision,
    reason: LifecycleReason | None,
) -> None:
    conn.execute(
        """
        INSERT INTO stages (stage_name, status, revision_sequence, reason_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(stage_name) DO UPDATE SET
            status = excluded.status,
            revision_sequence = excluded.revision_sequence,
            reason_json = excluded.reason_json
        """,
        (
            stage_name,
            StageStatus(status).value,
            revision.sequence,
            _json_dumps_or_none(reason),
        ),
    )


def _next_attempt_number(conn: sqlite3.Connection, stage_name: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt FROM attempts WHERE stage_name = ?",
        (stage_name,),
    ).fetchone()
    return cast(
        int, _require_row(row, "could not allocate stage attempt")["next_attempt"]
    )


def _active_controller_lease_row(
    conn: sqlite3.Connection, now: str
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM leases
        WHERE kind = ? AND state = ?
        ORDER BY acquired_at DESC
        """,
        (LeaseKind.CONTROLLER.value, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _active_stage_lease_row(
    conn: sqlite3.Connection, stage_name: str, now: str
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM leases
        WHERE kind = ? AND stage_name = ? AND state = ?
        ORDER BY acquired_at DESC
        """,
        (LeaseKind.STAGE.value, stage_name, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _stage_lease_row(
    conn: sqlite3.Connection,
    *,
    stage_name: str,
    attempt_id: str,
    fencing_token: str,
) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT *
            FROM leases
            WHERE kind = ?
                AND stage_name = ?
                AND attempt_id = ?
                AND fencing_token = ?
                AND state = ?
            ORDER BY acquired_at DESC
            LIMIT 1
            """,
            (
                LeaseKind.STAGE.value,
                stage_name,
                attempt_id,
                fencing_token,
                LeaseState.ACTIVE.value,
            ),
        ).fetchone(),
    )


def _active_attempt_lease_row(
    conn: sqlite3.Connection,
    *,
    stage_name: str,
    attempt_id: str,
    now: str,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM leases
        WHERE kind = ?
            AND stage_name = ?
            AND attempt_id = ?
            AND state = ?
        ORDER BY acquired_at DESC
        """,
        (
            LeaseKind.STAGE.value,
            stage_name,
            attempt_id,
            LeaseState.ACTIVE.value,
        ),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


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
        raise AuthorityStoreError("stored authority JSON is invalid") from exc


def _json_dumps_or_none(value: LifecycleReason | None) -> str | None:
    if value is None:
        return None
    return _json_dumps(value.to_dict())


def _reason_from_json(value: str | None) -> LifecycleReason | None:
    if value is None:
        return None
    return LifecycleReason.from_dict(_json_loads(value))


def _plain_mapping(
    value: Mapping[str, PlainData], field: str
) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthorityStoreError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthorityStoreError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _require_row(row: sqlite3.Row | None, message: str) -> sqlite3.Row:
    if row is None:
        raise AuthorityStoreError(message)
    return row


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


def _positive_seconds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityStoreError("lease_ttl_seconds must be positive")
    return value


__all__ = ["SQLitePerRunAuthorityStore"]
