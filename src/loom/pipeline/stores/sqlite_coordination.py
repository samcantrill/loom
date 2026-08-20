"""Local SQLite implementation of the workspace coordination contract."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from loom.serialization import PlainData
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp

from .capabilities import (
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
)
from .coordination import (
    ConcurrencyCounter,
    CoordinationFailureKind,
    CoordinationStoreError,
    CoordinationRecoveryRecord,
    ResourceLeaseRecord,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
)
from .read_models import (
    BackendRevision,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    RecoveryKind,
    RecoveryRecord,
)
from .schema_policy import (
    AUTHORITY_SCHEMA_VERSION,
    AuthoritySchemaCheck,
    AuthoritySchemaError,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
)


_COORDINATION_DIR = ".loom"
_COORDINATION_DB_NAME = "coordination.sqlite3"
_SQLITE_TIMEOUT_SECONDS = 30.0

_SUPPORTED_CROSS_RUN_CAPABILITIES = (
    BackendCapability.CROSS_RUN_COORDINATION,
    BackendCapability.GLOBAL_COUNTERS,
    BackendCapability.BACKEND_LEASE_TIME,
    BackendCapability.REVISIONED_SNAPSHOTS,
    BackendCapability.RECOVERY_SCANS,
    BackendCapability.CONSISTENT_READS,
)

_RESOURCE_COUNTER_PREFIX = "resource:"

_REQUIRED_SCHEMA_COLUMNS = {
    "metadata": frozenset({"key", "value"}),
    "revisions": frozenset({"sequence", "token", "created_at"}),
    "workspaces": frozenset(
        {"workspace_id", "root_uri", "metadata_json", "revision_sequence"}
    ),
    "sweeps": frozenset(
        {"sweep_id", "workspace_id", "metadata_json", "revision_sequence"}
    ),
    "trials": frozenset(
        {
            "sweep_id",
            "trial_id",
            "run_uri",
            "state",
            "trial_revision_json",
            "metadata_json",
            "revision_sequence",
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
            "revision_sequence",
            "reason_json",
        }
    ),
    "trial_leases": frozenset({"lease_id", "workspace_id", "sweep_id", "trial_id"}),
    "resource_leases": frozenset(
        {"lease_id", "workspace_id", "resource_key", "amount"}
    ),
    "resource_limits": frozenset(
        {"workspace_id", "resource_key", "limit_value", "revision_sequence"}
    ),
    "counters": frozenset(
        {"workspace_id", "counter_name", "value", "limit_value", "revision_sequence"}
    ),
}


class SQLiteWorkspaceCoordinationStore:
    """SQLite-backed local workspace/sweep coordination store.

    The database schema is private to this implementation. The supported
    contract is ``WorkspaceCoordinationStore`` plus the capability records
    returned by ``capabilities()``.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime | str] | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._clock = clock

    @classmethod
    def for_workspace_root(
        cls,
        workspace_root: str | Path,
        *,
        clock: Callable[[], datetime | str] | None = None,
    ) -> "SQLiteWorkspaceCoordinationStore":
        return cls(
            Path(workspace_root) / _COORDINATION_DIR / _COORDINATION_DB_NAME,
            clock=clock,
        )

    def capabilities(self) -> BackendCapabilitySet:
        records = [
            BackendCapabilityRecord(
                capability=capability,
                scope=CapabilityScope.CROSS_RUN,
                message=(
                    "local SQLite workspace coordination is safe only for "
                    "local or same-host controllers"
                )
                if capability is BackendCapability.CROSS_RUN_COORDINATION
                else None,
                detail={"safety": "local_or_same_host"}
                if capability is BackendCapability.CROSS_RUN_COORDINATION
                else {},
            )
            for capability in _SUPPORTED_CROSS_RUN_CAPABILITIES
        ]
        records.append(
            BackendCapabilityRecord(
                capability=BackendCapability.PER_RUN_COORDINATION,
                scope=CapabilityScope.PER_RUN,
                support=CapabilitySupport.UNSUPPORTED,
                message=(
                    "the SQLite workspace coordination backend does not own "
                    "per-run lifecycle state"
                ),
            )
        )
        return BackendCapabilitySet(
            backend_name="sqlite-workspace-coordination",
            records=tuple(records),
        )

    def check_schema(self) -> AuthoritySchemaCheck:
        if not self._database_path.exists():
            return AuthoritySchemaCheck(
                current_version=AUTHORITY_SCHEMA_VERSION,
                found_version=None,
                failure=AuthoritySchemaFailure(
                    kind=AuthoritySchemaFailureKind.MISSING,
                    message="SQLite coordination schema metadata is missing",
                    current_version=AUTHORITY_SCHEMA_VERSION,
                ),
            )
        with self._connection(initialize=False) as conn:
            return _check_schema_connection(conn)

    def create_workspace(self, identity: WorkspaceIdentity) -> BackendRevision:
        with self._transaction(initialize=True) as conn:
            if _workspace_row(conn, identity.workspace_id) is not None:
                raise ValueError(f"workspace already exists: {identity.workspace_id}")
            revision = self._insert_revision(conn)
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id,
                    root_uri,
                    metadata_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    identity.workspace_id,
                    identity.root_uri,
                    _json_dumps(identity.metadata),
                    revision.sequence,
                ),
            )
            return revision

    def create_sweep(self, identity: SweepIdentity) -> BackendRevision:
        with self._transaction(initialize=True) as conn:
            _require_workspace(conn, identity.workspace_id)
            if _sweep_row(conn, identity.sweep_id) is not None:
                raise ValueError(f"sweep already exists: {identity.sweep_id}")
            revision = self._insert_revision(conn)
            conn.execute(
                """
                INSERT INTO sweeps (
                    sweep_id,
                    workspace_id,
                    metadata_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    identity.sweep_id,
                    identity.workspace_id,
                    _json_dumps(identity.metadata),
                    revision.sequence,
                ),
            )
            return revision

    def record_trial(self, trial: TrialReference) -> BackendRevision:
        with self._transaction(initialize=True) as conn:
            _require_sweep(conn, trial.sweep_id)
            revision = self._insert_revision(conn)
            conn.execute(
                """
                INSERT INTO trials (
                    sweep_id,
                    trial_id,
                    run_uri,
                    state,
                    trial_revision_json,
                    metadata_json,
                    revision_sequence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sweep_id, trial_id) DO UPDATE SET
                    run_uri = excluded.run_uri,
                    state = excluded.state,
                    trial_revision_json = excluded.trial_revision_json,
                    metadata_json = excluded.metadata_json,
                    revision_sequence = excluded.revision_sequence
                """,
                (
                    trial.sweep_id,
                    trial.trial_id,
                    trial.run_uri,
                    trial.state.value,
                    _json_dumps(trial.revision.to_dict()),
                    _json_dumps(trial.metadata),
                    revision.sequence,
                ),
            )
            return revision

    def list_trials(self, sweep_id: str) -> tuple[TrialReference, ...]:
        with self._connection(initialize=False) as conn:
            _raise_for_schema(conn)
            _require_sweep(conn, sweep_id)
            return tuple(
                _trial_from_row(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM trials
                    WHERE sweep_id = ?
                    ORDER BY trial_id
                    """,
                    (sweep_id,),
                )
            )

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> TrialLeaseRecord:
        with self._transaction(initialize=True) as conn:
            sweep = _require_sweep(conn, sweep_id)
            _require_trial(conn, sweep_id, trial_id)
            now = self._now()
            if _active_trial_lease_row(conn, sweep_id, trial_id, now) is not None:
                raise ValueError("trial already has an active lease")
            lease = self._insert_lease(
                conn,
                kind=LeaseKind.TRIAL,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                now=now,
            )
            record = TrialLeaseRecord(
                workspace_id=cast(str, sweep["workspace_id"]),
                sweep_id=sweep_id,
                trial_id=trial_id,
                lease=lease,
            )
            conn.execute(
                """
                INSERT INTO trial_leases (
                    lease_id,
                    workspace_id,
                    sweep_id,
                    trial_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    record.workspace_id,
                    record.sweep_id,
                    record.trial_id,
                ),
            )
            return record

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
    ) -> ResourceLeaseRecord:
        amount = _positive_int(amount, "amount")
        resource_key = _non_empty_string(resource_key, "resource_key")
        with self._transaction(initialize=True) as conn:
            _require_workspace(conn, workspace_id)
            now = self._now()
            limit = _resource_limit(conn, workspace_id, resource_key)
            active_amount = _active_resource_amount(
                conn, workspace_id, resource_key, now
            )
            if limit is not None and active_amount + amount > limit:
                raise CoordinationStoreError(
                    "resource limit exceeded", kind=CoordinationFailureKind.CAPACITY
                )
            lease = self._insert_lease(
                conn,
                kind=LeaseKind.RESOURCE,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                now=now,
            )
            record = ResourceLeaseRecord(
                workspace_id=workspace_id,
                resource_key=resource_key,
                lease=lease,
                amount=amount,
            )
            conn.execute(
                """
                INSERT INTO resource_leases (
                    lease_id,
                    workspace_id,
                    resource_key,
                    amount
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    record.workspace_id,
                    record.resource_key,
                    record.amount,
                ),
            )
            return record

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        with self._transaction(initialize=False) as conn:
            now = self._now()
            lease = self._require_mutable_lease(
                conn, lease_id, owner_id, fencing_token, now
            )
            revision = self._insert_revision(conn, now=now)
            renewed = LeaseRecord(
                lease_id=lease.lease_id,
                kind=lease.kind,
                owner_id=lease.owner_id,
                fencing_token=lease.fencing_token,
                acquired_at=lease.acquired_at,
                renewed_at=now,
                expires_at=_add_seconds(
                    now, _positive_int(lease_ttl_seconds, "lease_ttl_seconds")
                ),
                revision=revision,
                state=lease.state,
                reason=lease.reason,
            )
            self._update_lease(conn, renewed)
            return renewed

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
        return self._finish_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            state=LeaseState.FAILED,
            reason=reason,
        )

    def set_resource_limit(
        self, workspace_id: str, resource_key: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        resource_key = _non_empty_string(resource_key, "resource_key")
        if limit is not None:
            limit = _positive_int(limit, "limit")
        with self._transaction(initialize=True) as conn:
            _require_workspace(conn, workspace_id)
            now = self._now()
            active_amount = _active_resource_amount(
                conn, workspace_id, resource_key, now
            )
            if limit is not None and active_amount > limit:
                raise ValueError("resource limit is below active lease usage")
            revision = self._insert_revision(conn, now=now)
            if limit is None:
                conn.execute(
                    """
                    DELETE FROM resource_limits
                    WHERE workspace_id = ? AND resource_key = ?
                    """,
                    (workspace_id, resource_key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO resource_limits (
                        workspace_id,
                        resource_key,
                        limit_value,
                        revision_sequence
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(workspace_id, resource_key) DO UPDATE SET
                        limit_value = excluded.limit_value,
                        revision_sequence = excluded.revision_sequence
                    """,
                    (workspace_id, resource_key, limit, revision.sequence),
                )
            return ConcurrencyCounter(
                counter_name=_resource_counter_name(resource_key),
                value=active_amount,
                limit=limit,
                revision=revision,
            )

    def read_resource_limit(
        self, workspace_id: str, resource_key: str
    ) -> ConcurrencyCounter | None:
        resource_key = _non_empty_string(resource_key, "resource_key")
        with self._connection(initialize=False) as conn:
            _raise_for_schema(conn)
            _require_workspace(conn, workspace_id)
            row = _resource_limit_row(conn, workspace_id, resource_key)
            if row is None:
                return None
            now = self._now()
            return ConcurrencyCounter(
                counter_name=_resource_counter_name(resource_key),
                value=_active_resource_amount(conn, workspace_id, resource_key, now),
                limit=cast(int | None, row["limit_value"]),
                revision=_revision_for(conn, cast(int, row["revision_sequence"])),
            )

    def set_counter_limit(
        self, workspace_id: str, counter_name: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        counter_name = _non_empty_string(counter_name, "counter_name")
        if limit is not None:
            limit = _positive_int(limit, "limit")
        with self._transaction(initialize=True) as conn:
            _require_workspace(conn, workspace_id)
            current = _counter_row(conn, workspace_id, counter_name)
            value = 0 if current is None else cast(int, current["value"])
            if limit is not None and value > limit:
                raise ValueError("counter limit is below current value")
            revision = self._insert_revision(conn)
            self._upsert_counter(
                conn,
                workspace_id=workspace_id,
                counter_name=counter_name,
                value=value,
                limit=limit,
                revision=revision,
            )
            return ConcurrencyCounter(
                counter_name=counter_name,
                value=value,
                limit=limit,
                revision=revision,
            )

    def increment_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        limit: int | None = None,
    ) -> ConcurrencyCounter:
        return self._change_counter(
            workspace_id,
            counter_name,
            amount=_positive_int(amount, "amount"),
            limit=limit,
        )

    def decrement_counter(
        self, workspace_id: str, counter_name: str, *, amount: int = 1
    ) -> ConcurrencyCounter:
        return self._change_counter(
            workspace_id,
            counter_name,
            amount=-_positive_int(amount, "amount"),
            limit=None,
        )

    def read_counter(
        self, workspace_id: str, counter_name: str
    ) -> ConcurrencyCounter | None:
        with self._connection(initialize=False) as conn:
            _raise_for_schema(conn)
            _require_workspace(conn, workspace_id)
            row = _counter_row(conn, workspace_id, counter_name)
            if row is None:
                return None
            return _counter_from_row(row, conn=conn)

    def scan_recovery(
        self, workspace_id: str
    ) -> tuple[CoordinationRecoveryRecord, ...]:
        with self._connection(initialize=False) as conn:
            _raise_for_schema(conn)
            _require_workspace(conn, workspace_id)
            now = self._now()
            records: list[CoordinationRecoveryRecord] = []
            for row in conn.execute(
                """
                SELECT leases.*, trial_leases.workspace_id, trial_leases.sweep_id,
                    trial_leases.trial_id
                FROM leases
                JOIN trial_leases ON trial_leases.lease_id = leases.lease_id
                WHERE trial_leases.workspace_id = ? AND leases.state = ?
                ORDER BY leases.lease_id
                """,
                (workspace_id, LeaseState.ACTIVE.value),
            ):
                lease = _lease_from_row(row, conn=conn)
                if not _timestamp_expired(lease.expires_at, now):
                    continue
                records.append(
                    CoordinationRecoveryRecord(
                        workspace_id=workspace_id,
                        sweep_id=cast(str, row["sweep_id"]),
                        trial_id=cast(str, row["trial_id"]),
                        recovery=_expired_lease_recovery(lease, now),
                    )
                )
            for row in conn.execute(
                """
                SELECT leases.*, resource_leases.workspace_id,
                    resource_leases.resource_key, resource_leases.amount
                FROM leases
                JOIN resource_leases ON resource_leases.lease_id = leases.lease_id
                WHERE resource_leases.workspace_id = ? AND leases.state = ?
                ORDER BY leases.lease_id
                """,
                (workspace_id, LeaseState.ACTIVE.value),
            ):
                lease = _lease_from_row(row, conn=conn)
                if not _timestamp_expired(lease.expires_at, now):
                    continue
                records.append(
                    CoordinationRecoveryRecord(
                        workspace_id=workspace_id,
                        resource_key=cast(str, row["resource_key"]),
                        amount=cast(int, row["amount"]),
                        recovery=_expired_lease_recovery(lease, now),
                    )
                )
            return tuple(records)

    @contextmanager
    def _connection(self, *, initialize: bool) -> Iterator[sqlite3.Connection]:
        should_initialize = initialize and not self._database_path.exists()
        if should_initialize:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
        if not initialize and not self._database_path.exists():
            raise AuthoritySchemaError("SQLite coordination database is missing")
        conn = sqlite3.connect(
            self._database_path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if should_initialize:
            _initialize_schema(conn)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self, *, initialize: bool) -> Iterator[sqlite3.Connection]:
        with self._connection(initialize=initialize) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _migrate_schema(conn)
                _raise_for_schema(conn)
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _insert_revision(
        self, conn: sqlite3.Connection, *, now: str | None = None
    ) -> BackendRevision:
        created_at = now or self._now()
        token = uuid.uuid4().hex
        cursor = conn.execute(
            "INSERT INTO revisions (token, created_at) VALUES (?, ?)",
            (token, created_at),
        )
        return BackendRevision(
            sequence=cast(int, cursor.lastrowid),
            token=token,
            created_at=created_at,
        )

    def _insert_lease(
        self,
        conn: sqlite3.Connection,
        *,
        kind: LeaseKind,
        owner_id: str,
        lease_ttl_seconds: int,
        now: str,
    ) -> LeaseRecord:
        lease_ttl_seconds = _positive_int(lease_ttl_seconds, "lease_ttl_seconds")
        revision = self._insert_revision(conn, now=now)
        lease_id = f"workspace-lease-{revision.sequence}"
        lease = LeaseRecord(
            lease_id=lease_id,
            kind=kind,
            owner_id=owner_id,
            fencing_token=uuid.uuid4().hex,
            acquired_at=now,
            renewed_at=now,
            expires_at=_add_seconds(now, lease_ttl_seconds),
            revision=revision,
        )
        conn.execute(
            """
            INSERT INTO leases (
                lease_id,
                kind,
                owner_id,
                fencing_token,
                acquired_at,
                renewed_at,
                expires_at,
                state,
                revision_sequence,
                reason_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lease.lease_id,
                lease.kind.value,
                lease.owner_id,
                lease.fencing_token,
                lease.acquired_at,
                lease.renewed_at,
                lease.expires_at,
                lease.state.value,
                lease.revision.sequence,
                _json_dumps_or_none(lease.reason),
            ),
        )
        return lease

    def _update_lease(self, conn: sqlite3.Connection, lease: LeaseRecord) -> None:
        conn.execute(
            """
            UPDATE leases
            SET renewed_at = ?,
                expires_at = ?,
                state = ?,
                revision_sequence = ?,
                reason_json = ?
            WHERE lease_id = ?
            """,
            (
                lease.renewed_at,
                lease.expires_at,
                lease.state.value,
                lease.revision.sequence,
                _json_dumps_or_none(lease.reason),
                lease.lease_id,
            ),
        )

    def _require_mutable_lease(
        self,
        conn: sqlite3.Connection,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        now: str,
    ) -> LeaseRecord:
        row = conn.execute(
            "SELECT * FROM leases WHERE lease_id = ?",
            (lease_id,),
        ).fetchone()
        if row is None:
            raise CoordinationStoreError(
                f"unknown lease: {lease_id}",
                kind=CoordinationFailureKind.OWNERSHIP_LOST,
            )
        lease = _lease_from_row(row, conn=conn)
        if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
            raise CoordinationStoreError(
                "stale or foreign lease token",
                kind=CoordinationFailureKind.OWNERSHIP_LOST,
            )
        if lease.state is not LeaseState.ACTIVE:
            raise CoordinationStoreError(
                "lease is not active", kind=CoordinationFailureKind.OWNERSHIP_LOST
            )
        if _timestamp_expired(lease.expires_at, now):
            raise CoordinationStoreError(
                "lease has expired", kind=CoordinationFailureKind.OWNERSHIP_LOST
            )
        return lease

    def _finish_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        state: LeaseState,
        reason: LifecycleReason | None,
    ) -> LeaseRecord:
        with self._transaction(initialize=False) as conn:
            now = self._now()
            lease = self._require_mutable_lease(
                conn, lease_id, owner_id, fencing_token, now
            )
            revision = self._insert_revision(conn, now=now)
            finished = LeaseRecord(
                lease_id=lease.lease_id,
                kind=lease.kind,
                owner_id=lease.owner_id,
                fencing_token=lease.fencing_token,
                acquired_at=lease.acquired_at,
                renewed_at=lease.renewed_at,
                expires_at=lease.expires_at,
                revision=revision,
                state=state,
                reason=reason,
            )
            self._update_lease(conn, finished)
            return finished

    def _change_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int,
        limit: int | None,
    ) -> ConcurrencyCounter:
        counter_name = _non_empty_string(counter_name, "counter_name")
        if limit is not None:
            limit = _positive_int(limit, "limit")
        with self._transaction(initialize=True) as conn:
            _require_workspace(conn, workspace_id)
            current = _counter_row(conn, workspace_id, counter_name)
            value = 0 if current is None else cast(int, current["value"])
            current_limit = (
                None if current is None else cast(int | None, current["limit_value"])
            )
            next_limit = limit if limit is not None else current_limit
            next_value = value + amount
            if next_value < 0:
                raise ValueError("counter value cannot become negative")
            if next_limit is not None and next_value > next_limit:
                raise ValueError("counter limit exceeded")
            revision = self._insert_revision(conn)
            self._upsert_counter(
                conn,
                workspace_id=workspace_id,
                counter_name=counter_name,
                value=next_value,
                limit=next_limit,
                revision=revision,
            )
            return ConcurrencyCounter(
                counter_name=counter_name,
                value=next_value,
                limit=next_limit,
                revision=revision,
            )

    def _upsert_counter(
        self,
        conn: sqlite3.Connection,
        *,
        workspace_id: str,
        counter_name: str,
        value: int,
        limit: int | None,
        revision: BackendRevision,
    ) -> None:
        conn.execute(
            """
            INSERT INTO counters (
                workspace_id,
                counter_name,
                value,
                limit_value,
                revision_sequence
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, counter_name) DO UPDATE SET
                value = excluded.value,
                limit_value = excluded.limit_value,
                revision_sequence = excluded.revision_sequence
            """,
            (workspace_id, counter_name, value, limit, revision.sequence),
        )

    def _now(self) -> str:
        if self._clock is None:
            return utc_timestamp(utc_now())
        value = self._clock()
        if isinstance(value, datetime):
            return utc_timestamp(value)
        return utc_timestamp(parse_timestamp(value))


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
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            root_uri TEXT,
            metadata_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sweeps (
            sweep_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS trials (
            sweep_id TEXT NOT NULL,
            trial_id TEXT NOT NULL,
            run_uri TEXT,
            state TEXT NOT NULL,
            trial_revision_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY(sweep_id, trial_id),
            FOREIGN KEY(sweep_id) REFERENCES sweeps(sweep_id)
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
            revision_sequence INTEGER NOT NULL,
            reason_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS trial_leases (
            lease_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            sweep_id TEXT NOT NULL,
            trial_id TEXT NOT NULL,
            FOREIGN KEY(lease_id) REFERENCES leases(lease_id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
            FOREIGN KEY(sweep_id, trial_id) REFERENCES trials(sweep_id, trial_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS resource_leases (
            lease_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            resource_key TEXT NOT NULL,
            amount INTEGER NOT NULL,
            FOREIGN KEY(lease_id) REFERENCES leases(lease_id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS resource_limits (
            workspace_id TEXT NOT NULL,
            resource_key TEXT NOT NULL,
            limit_value INTEGER,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY(workspace_id, resource_key),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS counters (
            workspace_id TEXT NOT NULL,
            counter_name TEXT NOT NULL,
            value INTEGER NOT NULL,
            limit_value INTEGER,
            revision_sequence INTEGER NOT NULL,
            PRIMARY KEY(workspace_id, counter_name),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_trial_leases_trial
            ON trial_leases(sweep_id, trial_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_resource_leases_resource
            ON resource_leases(workspace_id, resource_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_coordination_leases_state
            ON leases(kind, state, expires_at)
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
        return _missing_schema_check()
    if row is None:
        return _missing_schema_check()
    raw_version = row["value"]
    try:
        version = int(cast(str, raw_version))
    except (TypeError, ValueError):
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message="SQLite coordination schema version is invalid",
                current_version=AUTHORITY_SCHEMA_VERSION,
            ),
        )
    if version <= 0:
        return AuthoritySchemaCheck(
            current_version=AUTHORITY_SCHEMA_VERSION,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message="SQLite coordination schema version is invalid",
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
                    f"unsupported older SQLite coordination schema {version}; "
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
                    f"unsupported newer SQLite coordination schema {version}; "
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


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Atomically advance one known-complete v1 coordination database."""

    try:
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return
    if row is None:
        return
    try:
        version = int(cast(str, row["value"]))
    except (TypeError, ValueError):
        return
    if version != 1:
        return
    if _schema_shape_failure(conn) is not None:
        raise AuthoritySchemaError(
            "SQLite coordination v1 schema is incomplete or invalid"
        )
    conn.execute(
        "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
        (str(AUTHORITY_SCHEMA_VERSION),),
    )


def _missing_schema_check() -> AuthoritySchemaCheck:
    return AuthoritySchemaCheck(
        current_version=AUTHORITY_SCHEMA_VERSION,
        found_version=None,
        failure=AuthoritySchemaFailure(
            kind=AuthoritySchemaFailureKind.MISSING,
            message="SQLite coordination schema metadata is missing",
            current_version=AUTHORITY_SCHEMA_VERSION,
        ),
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
        message="SQLite coordination schema is incomplete or invalid",
        current_version=AUTHORITY_SCHEMA_VERSION,
    )


def _raise_for_schema(conn: sqlite3.Connection) -> None:
    check = _check_schema_connection(conn)
    if check.failure is not None:
        raise AuthoritySchemaError(check.failure.message)


def _workspace_row(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            "SELECT * FROM workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone(),
    )


def _require_workspace(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row:
    row = _workspace_row(conn, workspace_id)
    if row is None:
        raise ValueError(f"unknown workspace: {workspace_id}")
    return row


def _sweep_row(conn: sqlite3.Connection, sweep_id: str) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            "SELECT * FROM sweeps WHERE sweep_id = ?",
            (sweep_id,),
        ).fetchone(),
    )


def _require_sweep(conn: sqlite3.Connection, sweep_id: str) -> sqlite3.Row:
    row = _sweep_row(conn, sweep_id)
    if row is None:
        raise ValueError(f"unknown sweep: {sweep_id}")
    return row


def _require_trial(
    conn: sqlite3.Connection, sweep_id: str, trial_id: str
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT *
        FROM trials
        WHERE sweep_id = ? AND trial_id = ?
        """,
        (sweep_id, trial_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown trial: {trial_id}")
    return cast(sqlite3.Row, row)


def _trial_from_row(row: sqlite3.Row) -> TrialReference:
    return TrialReference(
        trial_id=cast(str, row["trial_id"]),
        sweep_id=cast(str, row["sweep_id"]),
        run_uri=cast(str | None, row["run_uri"]),
        state=TrialState(cast(str, row["state"])),
        revision=BackendRevision.from_dict(
            _json_loads(cast(str, row["trial_revision_json"]))
        ),
        metadata=_json_mapping(cast(str, row["metadata_json"])),
    )


def _lease_from_row(row: sqlite3.Row, *, conn: sqlite3.Connection) -> LeaseRecord:
    return LeaseRecord(
        lease_id=cast(str, row["lease_id"]),
        kind=LeaseKind(cast(str, row["kind"])),
        owner_id=cast(str, row["owner_id"]),
        fencing_token=cast(str, row["fencing_token"]),
        acquired_at=cast(str, row["acquired_at"]),
        renewed_at=cast(str, row["renewed_at"]),
        expires_at=cast(str, row["expires_at"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
        state=LeaseState(cast(str, row["state"])),
        reason=_reason_from_json(cast(str | None, row["reason_json"])),
    )


def _active_trial_lease_row(
    conn: sqlite3.Connection, sweep_id: str, trial_id: str, now: str
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT leases.*
        FROM leases
        JOIN trial_leases ON trial_leases.lease_id = leases.lease_id
        WHERE trial_leases.sweep_id = ?
            AND trial_leases.trial_id = ?
            AND leases.state = ?
        ORDER BY leases.acquired_at DESC
        """,
        (sweep_id, trial_id, LeaseState.ACTIVE.value),
    ).fetchall()
    for row in rows:
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            return cast(sqlite3.Row, row)
    return None


def _active_resource_amount(
    conn: sqlite3.Connection, workspace_id: str, resource_key: str, now: str
) -> int:
    total = 0
    for row in conn.execute(
        """
        SELECT leases.expires_at, resource_leases.amount
        FROM leases
        JOIN resource_leases ON resource_leases.lease_id = leases.lease_id
        WHERE resource_leases.workspace_id = ?
            AND resource_leases.resource_key = ?
            AND leases.state = ?
        """,
        (workspace_id, resource_key, LeaseState.ACTIVE.value),
    ):
        if not _timestamp_expired(cast(str, row["expires_at"]), now):
            total += cast(int, row["amount"])
    return total


def _resource_limit(
    conn: sqlite3.Connection, workspace_id: str, resource_key: str
) -> int | None:
    row = _resource_limit_row(conn, workspace_id, resource_key)
    if row is None:
        return None
    return cast(int | None, row["limit_value"])


def _resource_limit_row(
    conn: sqlite3.Connection, workspace_id: str, resource_key: str
) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT limit_value, revision_sequence
            FROM resource_limits
            WHERE workspace_id = ? AND resource_key = ?
            """,
            (workspace_id, resource_key),
        ).fetchone(),
    )


def _counter_row(
    conn: sqlite3.Connection, workspace_id: str, counter_name: str
) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT *
            FROM counters
            WHERE workspace_id = ? AND counter_name = ?
            """,
            (workspace_id, counter_name),
        ).fetchone(),
    )


def _counter_from_row(
    row: sqlite3.Row, *, conn: sqlite3.Connection
) -> ConcurrencyCounter:
    return ConcurrencyCounter(
        counter_name=cast(str, row["counter_name"]),
        value=cast(int, row["value"]),
        limit=cast(int | None, row["limit_value"]),
        revision=_revision_for(conn, cast(int, row["revision_sequence"])),
    )


def _revision_for(conn: sqlite3.Connection, sequence: int) -> BackendRevision:
    row = conn.execute(
        """
        SELECT sequence, token, created_at
        FROM revisions
        WHERE sequence = ?
        """,
        (sequence,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown revision: {sequence}")
    return BackendRevision(
        sequence=cast(int, row["sequence"]),
        token=cast(str, row["token"]),
        created_at=cast(str, row["created_at"]),
    )


def _expired_lease_recovery(lease: LeaseRecord, now: str) -> RecoveryRecord:
    return RecoveryRecord(
        recovery_id=f"expired-{lease.lease_id}",
        kind=RecoveryKind.EXPIRED_LEASE,
        reason=LifecycleReason(code="lease_expired"),
        detected_at=now,
        revision=lease.revision,
    )


def _resource_counter_name(resource_key: str) -> str:
    return f"{_RESOURCE_COUNTER_PREFIX}{resource_key}"


def _timestamp_expired(expires_at: str, now: str) -> bool:
    return parse_timestamp(expires_at) <= parse_timestamp(now)


def _add_seconds(timestamp: str, seconds: int) -> str:
    return utc_timestamp(parse_timestamp(timestamp) + timedelta(seconds=seconds))


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_dumps_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, LifecycleReason):
        value = value.to_dict()
    return _json_dumps(value)


def _json_loads(data: str) -> object:
    return json.loads(data)


def _json_mapping(data: str) -> Mapping[str, PlainData]:
    value = _json_loads(data)
    if not isinstance(value, Mapping):
        raise ValueError("stored JSON value must be a mapping")
    return cast(Mapping[str, PlainData], value)


def _reason_from_json(data: str | None) -> LifecycleReason | None:
    if data is None:
        return None
    return LifecycleReason.from_dict(_json_loads(data))


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


__all__ = ["SQLiteWorkspaceCoordinationStore"]
