"""Persistent single-machine managed-local daemon.

The daemon owns admission, process identity, and the production composition that
connects persisted run plans to the Stage 29 orchestrator and local assignment
saga. Clients provide only a queue identity and run URI.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from threading import Event, RLock, Thread
import time
from typing import TYPE_CHECKING, Iterator
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import QueueConflictError, QueueServiceError, QueueStorageError

if TYPE_CHECKING:
    from .local_daemon_execution import (
        LocalDaemonExecution,
        LocalDaemonExecutionOutcome,
    )


_LOCAL_DAEMON_SCHEMA_VERSION = 1


class LocalDaemonAdmissionState(StrEnum):
    """Coordinator-owned state, kept separate from authority lifecycle truth."""

    PENDING_AUTHORITY = "PENDING_AUTHORITY"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class LocalDaemonRole(StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class LocalDaemonPrincipal:
    """Trusted adapter-derived principal; request bodies never select it."""

    subject: str
    role: LocalDaemonRole

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject:
            raise QueueServiceError("daemon principal subject must be non-empty")
        object.__setattr__(self, "role", LocalDaemonRole(self.role))


@dataclass(frozen=True, slots=True)
class LocalDaemonConfig:
    """Protected configuration for one local coordinator and agent."""

    coordinator_root: Path
    agent_root: Path
    run_store_root: Path
    machine_id: str = "machine-A"
    cpu_capacity: int = 1
    poll_interval_seconds: float = 0.05

    def __post_init__(self) -> None:
        coordinator = Path(self.coordinator_root)
        agent = Path(self.agent_root)
        run_store = Path(self.run_store_root)
        if coordinator == agent:
            raise QueueServiceError(
                "coordinator and local-agent roots must be distinct"
            )
        if not isinstance(self.machine_id, str) or not self.machine_id:
            raise QueueServiceError("machine_id must be non-empty")
        if (
            isinstance(self.cpu_capacity, bool)
            or not isinstance(self.cpu_capacity, int)
            or self.cpu_capacity < 1
        ):
            raise QueueServiceError("cpu_capacity must be a positive integer")
        if (
            isinstance(self.poll_interval_seconds, bool)
            or not isinstance(self.poll_interval_seconds, (int, float))
            or self.poll_interval_seconds <= 0
        ):
            raise QueueServiceError("poll_interval_seconds must be positive")
        object.__setattr__(self, "coordinator_root", coordinator)
        object.__setattr__(self, "agent_root", agent)
        object.__setattr__(self, "run_store_root", run_store)
        object.__setattr__(
            self, "poll_interval_seconds", float(self.poll_interval_seconds)
        )

    @property
    def endpoint(self) -> Path:
        return self.coordinator_root / "daemon.sock"

    @property
    def control_database(self) -> Path:
        return self.coordinator_root / "control.sqlite"

    @property
    def execution_database(self) -> Path:
        return self.coordinator_root / "execution.sqlite"

    @property
    def agent_journal(self) -> Path:
        return self.agent_root / "journal.sqlite"


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmissionRequest:
    """The complete public submission shape."""

    queue_item_id: str
    run_uri: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.queue_item_id, "queue_item_id"),
            (self.run_uri, "run_uri"),
        ):
            if not isinstance(value, str) or not value:
                raise QueueServiceError(f"{name} must be a non-empty string")

    def to_dict(self) -> dict[str, PlainData]:
        return {"queue_item_id": self.queue_item_id, "run_uri": self.run_uri}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmissionRequest":
        _exact_fields(data, {"queue_item_id", "run_uri"}, "admission request")
        return cls(
            queue_item_id=_required_string(data, "queue_item_id"),
            run_uri=_required_string(data, "run_uri"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmission:
    admission_id: str
    queue_item_id: str
    coordinator_id: str
    run_uri: str
    intent_digest: str
    execution_owner: str
    state: LocalDaemonAdmissionState
    accepted_at: str
    authority_operation_id: str
    cancellation_operation_id: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admission_id": self.admission_id,
            "queue_item_id": self.queue_item_id,
            "coordinator_id": self.coordinator_id,
            "run_uri": self.run_uri,
            "intent_digest": self.intent_digest,
            "execution_owner": self.execution_owner,
            "state": self.state.value,
            "accepted_at": self.accepted_at,
            "authority_operation_id": self.authority_operation_id,
            "cancellation_operation_id": self.cancellation_operation_id,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmission":
        return cls(
            admission_id=_required_string(data, "admission_id"),
            queue_item_id=_required_string(data, "queue_item_id"),
            coordinator_id=_required_string(data, "coordinator_id"),
            run_uri=_required_string(data, "run_uri"),
            intent_digest=_required_string(data, "intent_digest"),
            execution_owner=_required_string(data, "execution_owner"),
            state=LocalDaemonAdmissionState(_required_string(data, "state")),
            accepted_at=_required_string(data, "accepted_at"),
            authority_operation_id=_required_string(data, "authority_operation_id"),
            cancellation_operation_id=_optional_string(
                data, "cancellation_operation_id"
            ),
            blocked_reason=_optional_string(data, "blocked_reason"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonStatus:
    coordinator_id: str
    coordinator_epoch: str
    as_of: str
    accepted_time: str
    service_health: str
    service_diagnostic: str | None
    admissions: tuple[LocalDaemonAdmission, ...]
    runs: tuple[Mapping[str, PlainData], ...] = ()

    @property
    def scheduling_ready(self) -> bool:
        return self.service_health == "healthy" and any(
            admission.state
            in {
                LocalDaemonAdmissionState.ACTIVE,
                LocalDaemonAdmissionState.WAITING,
            }
            for admission in self.admissions
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "as_of": self.as_of,
            "accepted_time": self.accepted_time,
            "service_health": self.service_health,
            "service_diagnostic": self.service_diagnostic,
            "scheduling_ready": self.scheduling_ready,
            "admissions": [item.to_dict() for item in self.admissions],
            "runs": [
                thaw_plain_data(item, path="local_daemon_status.runs")
                for item in self.runs
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonStatus":
        admissions = data.get("admissions")
        if not isinstance(admissions, list) or any(
            not isinstance(item, Mapping) for item in admissions
        ):
            raise QueueServiceError("admissions must be a list of records")
        runs = data.get("runs", [])
        if not isinstance(runs, list) or any(
            not isinstance(item, Mapping) for item in runs
        ):
            raise QueueServiceError("runs must be a list of owner views")
        return cls(
            coordinator_id=_required_string(data, "coordinator_id"),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            as_of=_required_string(data, "as_of"),
            accepted_time=_required_string(data, "accepted_time"),
            service_health=_required_string(data, "service_health"),
            service_diagnostic=_optional_string(data, "service_diagnostic"),
            admissions=tuple(
                LocalDaemonAdmission.from_dict(item) for item in admissions
            ),
            runs=tuple(
                freeze_plain_data(item, path="local_daemon_status.runs")
                for item in runs
            ),
        )


class LocalDaemon:
    """One locked persistent production composition."""

    def __init__(
        self,
        config: LocalDaemonConfig,
        *,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.config = config
        self._clock = clock
        self._coordinator_lock: object | None = None
        self._agent_lock: object | None = None
        self._coordinator_id: str | None = None
        self._epoch: str | None = None
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._assignment_workers: ThreadPoolExecutor | None = None
        self._execution: LocalDaemonExecution | None = None
        self._assignment_futures: dict[str, Future[LocalDaemonExecutionOutcome]] = {}
        self._cycle_lock = RLock()
        self._service_error: str | None = None

    @classmethod
    def initialize(cls, config: LocalDaemonConfig) -> None:
        """Create fresh owner-private roots; existing/legacy roots are rejected."""

        if config.coordinator_root.exists() or config.agent_root.exists():
            raise QueueServiceError(
                "local daemon requires fresh roots; migration and compatibility "
                "with existing managed-local state are unsupported"
            )
        _initialize_root(config.coordinator_root, role="coordinator")
        try:
            _initialize_root(config.agent_root, role="local-agent")
        except Exception:
            raise

    def start(self) -> LocalDaemonStatus:
        if self._coordinator_lock is not None:
            raise QueueServiceError("local daemon is already started")
        _validate_distinct_roots(self.config)
        coordinator_lock = _acquire_lock(self.config.coordinator_root)
        try:
            agent_lock = _acquire_lock(self.config.agent_root)
        except Exception:
            coordinator_lock.close()
            raise
        try:
            coordinator_id = _open_root(
                self.config.coordinator_root, role="coordinator"
            )
            _open_root(self.config.agent_root, role="local-agent")
            epoch = f"coordinator-epoch-{uuid4()}"
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO coordinator_epochs (epoch, started_at) VALUES (?, ?)",
                    (epoch, self._accepted_time(conn)),
                )
                conn.commit()
        except Exception:
            agent_lock.close()
            coordinator_lock.close()
            raise
        self._coordinator_lock = coordinator_lock
        self._agent_lock = agent_lock
        self._coordinator_id = coordinator_id
        self._epoch = epoch
        self._service_error = None
        self._stop.clear()
        self._wake.set()
        self._assignment_workers = ThreadPoolExecutor(
            max_workers=self.config.cpu_capacity,
            thread_name_prefix="loom-local-assignment",
        )
        from .local_daemon_execution import LocalDaemonExecution

        self._execution = LocalDaemonExecution(
            config=self.config,
            coordinator_id=coordinator_id,
            coordinator_epoch=epoch,
            cancellation_operation=self._cancellation_operation_id,
            admission_activated=self._activate_admission,
        )
        self._thread = Thread(
            target=self._serve,
            name="loom-local-daemon-runtime",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join()
        assignment_workers = self._assignment_workers
        self._assignment_workers = None
        if assignment_workers is not None:
            assignment_workers.shutdown(wait=True)
        self._assignment_futures.clear()
        self._execution = None
        for lock in (self._agent_lock, self._coordinator_lock):
            if lock is not None:
                lock.close()  # type: ignore[union-attr]
        self._coordinator_lock = None
        self._agent_lock = None
        self._coordinator_id = None
        self._epoch = None

    def client_view(self, principal: LocalDaemonPrincipal) -> "LocalDaemonClientView":
        return LocalDaemonClientView(self, principal)

    def operator_view(
        self, principal: LocalDaemonPrincipal
    ) -> "LocalDaemonOperatorView":
        return LocalDaemonOperatorView(self, principal)

    def status(self) -> LocalDaemonStatus:
        coordinator_id = self._require_started()
        with self._connection() as conn:
            admissions = tuple(
                _admission_from_row(row)
                for row in conn.execute(
                    "SELECT * FROM managed_admissions "
                    "ORDER BY accepted_at, admission_id"
                )
            )
            accepted_time = self._accepted_time(conn)
        from .local_daemon_execution import build_local_daemon_owner_views

        views = build_local_daemon_owner_views(
            self.config,
            admissions,
            clock=self._clock,
        )
        unavailable = any(
            any(
                isinstance(axis, Mapping) and axis.get("availability") == "unavailable"
                for axis in view.values()
            )
            for view in views
        )
        as_of = self._clock()
        parse_timestamp(as_of)
        return LocalDaemonStatus(
            coordinator_id=coordinator_id,
            coordinator_epoch=self._epoch or "",
            as_of=as_of,
            accepted_time=accepted_time,
            service_health=(
                "healthy"
                if self._service_error is None and not unavailable
                else "degraded"
            ),
            service_diagnostic=(
                self._service_error
                or ("owner_status_unavailable" if unavailable else None)
            ),
            admissions=admissions,
            runs=views,
        )

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        """Drive each admission through authority, orchestration, and execution."""

        self._require_started()
        with self._cycle_lock:
            execution = self._execution
            assignment_workers = self._assignment_workers
            if execution is None or assignment_workers is None:
                raise QueueServiceError("local daemon assignment supervisor is absent")
            self._harvest_assignment_futures()
            with self._connection() as conn:
                admissions = tuple(
                    _admission_from_row(row)
                    for row in conn.execute(
                        "SELECT * FROM managed_admissions "
                        "WHERE state NOT IN (?, ?, ?, ?) "
                        "ORDER BY accepted_at, admission_id",
                        (
                            LocalDaemonAdmissionState.SUCCEEDED.value,
                            LocalDaemonAdmissionState.FAILED.value,
                            LocalDaemonAdmissionState.CANCELLED.value,
                            LocalDaemonAdmissionState.BLOCKED.value,
                        ),
                    )
                )
            for admission in admissions:
                if admission.admission_id in self._assignment_futures:
                    continue
                future = assignment_workers.submit(execution.advance, admission)
                future.add_done_callback(lambda _future: self._wake.set())
                self._assignment_futures[admission.admission_id] = future
            self._harvest_assignment_futures()
            return self.status().admissions

    def _harvest_assignment_futures(self) -> None:
        for admission_id, future in tuple(self._assignment_futures.items()):
            if not future.done():
                continue
            del self._assignment_futures[admission_id]
            try:
                outcome = future.result()
            except QueueConflictError:
                self._set_state(
                    admission_id,
                    LocalDaemonAdmissionState.BLOCKED,
                    reason="authority_or_intent_conflict",
                )
            except Exception:  # outages stay replayable and visible
                self._service_error = "reconciliation_unavailable"
            else:
                self._service_error = None
                self._set_state(
                    admission_id,
                    outcome.state,
                    reason=outcome.reason,
                )

    def _serve(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.reconcile_once()
            except Exception:  # keep the durable owner alive and diagnosable
                self._service_error = "reconciliation_unavailable"
            self._wake.wait(self.config.poll_interval_seconds)

    def _submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        coordinator_id = self._require_started()
        from .local_daemon_execution import load_managed_local_intent

        intent = load_managed_local_intent(self.config, request.run_uri)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM managed_admissions "
                "WHERE coordinator_id = ? AND run_uri = ?",
                (coordinator_id, request.run_uri),
            ).fetchone()
            if row is not None:
                existing = _admission_from_row(row)
                if (
                    existing.intent_digest == intent.digest
                    and existing.queue_item_id == request.queue_item_id
                ):
                    conn.commit()
                    return existing
                raise QueueConflictError("managed run admission intent conflicts")
            other = conn.execute(
                "SELECT run_uri FROM managed_admissions WHERE queue_item_id = ?",
                (request.queue_item_id,),
            ).fetchone()
            if other is not None:
                raise QueueConflictError(
                    "queue item identity already admits another run"
                )
            admission_id = f"admission-{uuid4()}"
            operation_id = f"authority-bind-{uuid4()}"
            accepted_at = self._accepted_time(conn)
            conn.execute(
                """
                INSERT INTO managed_admissions (
                    admission_id, queue_item_id, coordinator_id, run_uri,
                    intent_digest, execution_owner, state, accepted_at,
                    authority_operation_id, cancellation_operation_id,
                    blocked_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    admission_id,
                    request.queue_item_id,
                    coordinator_id,
                    request.run_uri,
                    intent.digest,
                    "managed-stage",
                    LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                    accepted_at,
                    operation_id,
                ),
            )
            conn.commit()
        self._wake.set()
        return self._admission(admission_id)

    def _cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        self._require_started()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
            if row is None:
                raise QueueServiceError("managed admission was not found")
            admission = _admission_from_row(row)
            if admission.state in {
                LocalDaemonAdmissionState.SUCCEEDED,
                LocalDaemonAdmissionState.FAILED,
                LocalDaemonAdmissionState.CANCELLED,
            }:
                conn.commit()
                return admission
            operation_id = admission.cancellation_operation_id or (
                f"authority-cancel-{uuid4()}"
            )
            conn.execute(
                "UPDATE managed_admissions SET state = ?, "
                "cancellation_operation_id = ?, blocked_reason = NULL "
                "WHERE admission_id = ?",
                (
                    LocalDaemonAdmissionState.CANCELLATION_REQUESTED.value,
                    operation_id,
                    admission.admission_id,
                ),
            )
            conn.commit()
        self._wake.set()
        return self._admission(admission.admission_id)

    def _wait(
        self, queue_item_id: str, *, timeout_seconds: float | None
    ) -> LocalDaemonAdmission:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise QueueServiceError("timeout_seconds must be non-negative")
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
            LocalDaemonAdmissionState.BLOCKED,
        }
        while True:
            admission = self._admission_for_queue_item(queue_item_id)
            if admission.state in terminal:
                return admission
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "managed local admission did not reach terminal state"
                )
            self._wake.set()
            time.sleep(min(self.config.poll_interval_seconds, 0.05))

    def _cancellation_operation_id(self, admission_id: str) -> str | None:
        return self._admission(admission_id).cancellation_operation_id

    def _activate_admission(self, admission_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE managed_admissions SET state = ?, blocked_reason = NULL "
                "WHERE admission_id = ? AND cancellation_operation_id IS NULL "
                "AND state IN (?, ?, ?)",
                (
                    LocalDaemonAdmissionState.ACTIVE.value,
                    admission_id,
                    LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                    LocalDaemonAdmissionState.WAITING.value,
                    LocalDaemonAdmissionState.ACTIVE.value,
                ),
            )
            conn.commit()

    def _admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
        if row is None:
            raise QueueServiceError("managed admission was not found")
        return _admission_from_row(row)

    def _admission(self, admission_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        if row is None:
            raise QueueServiceError("managed admission was not found")
        return _admission_from_row(row)

    def _set_state(
        self,
        admission_id: str,
        state: LocalDaemonAdmissionState,
        *,
        reason: str | None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE managed_admissions SET state = ?, blocked_reason = ? "
                "WHERE admission_id = ?",
                (state.value, reason, admission_id),
            )
            conn.commit()

    def _require_started(self) -> str:
        if self._coordinator_lock is None or self._coordinator_id is None:
            raise QueueServiceError("local daemon is not started")
        return self._coordinator_id

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.config.control_database, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _accepted_time(self, conn: sqlite3.Connection) -> str:
        now = self._clock()
        parse_timestamp(now)
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'accepted_time'"
        ).fetchone()
        previous = None if row is None else str(row["value"])
        if previous is not None and parse_timestamp(now) < parse_timestamp(previous):
            raise QueueServiceError(
                "coordinator accepted-time regressed; scheduling is degraded"
            )
        accepted = previous if previous is not None and previous > now else now
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) "
            "VALUES ('accepted_time', ?)",
            (accepted,),
        )
        return accepted


@dataclass(frozen=True, slots=True)
class LocalDaemonClientView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        _require_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._submit(request)

    def status(self) -> LocalDaemonStatus:
        _require_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.status()

    def wait(
        self, queue_item_id: str, *, timeout_seconds: float | None = None
    ) -> LocalDaemonAdmission:
        _require_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._wait(queue_item_id, timeout_seconds=timeout_seconds)

    def cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        _require_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._cancel(queue_item_id)


@dataclass(frozen=True, slots=True)
class LocalDaemonOperatorView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def status(self) -> LocalDaemonStatus:
        _require_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.status()

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        _require_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.reconcile_once()


def _require_role(principal: LocalDaemonPrincipal, role: LocalDaemonRole) -> None:
    if principal.role is not role:
        raise QueueServiceError("daemon principal is not authorized for this operation")


def _initialize_root(path: Path, *, role: str) -> None:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    database = path / "control.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE root_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('role', ?)", (role,)
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('stable_id', ?)",
            (f"{role}-{uuid4()}",),
        )
        conn.execute(f"PRAGMA user_version = {_LOCAL_DAEMON_SCHEMA_VERSION}")
        if role == "coordinator":
            conn.execute(
                "CREATE TABLE daemon_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE coordinator_epochs "
                "(epoch TEXT PRIMARY KEY, started_at TEXT NOT NULL)"
            )
            conn.execute(
                """
                CREATE TABLE managed_admissions (
                    admission_id TEXT PRIMARY KEY,
                    queue_item_id TEXT NOT NULL UNIQUE,
                    coordinator_id TEXT NOT NULL,
                    run_uri TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    execution_owner TEXT NOT NULL,
                    state TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    authority_operation_id TEXT NOT NULL,
                    cancellation_operation_id TEXT,
                    blocked_reason TEXT,
                    UNIQUE(coordinator_id, run_uri)
                )
                """
            )
        conn.commit()
    database.chmod(0o600)


def _open_root(path: Path, *, role: str) -> str:
    _validate_private_directory(path)
    database = path / "control.sqlite"
    if not database.is_file():
        raise QueueServiceError(f"{role} root is missing control state")
    mode = stat.S_IMODE(database.stat().st_mode)
    if mode & 0o077:
        raise QueueStorageError(f"{role} root must be owner-permissioned")
    with sqlite3.connect(database) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != _LOCAL_DAEMON_SCHEMA_VERSION:
            raise QueueStorageError(
                f"{role} daemon schema is unsupported; fresh roots are required"
            )
        values = {
            str(row[0]): str(row[1])
            for row in conn.execute("SELECT key, value FROM root_metadata")
        }
    if values.get("role") != role or not values.get("stable_id"):
        raise QueueStorageError(f"{role} root identity is invalid")
    return values["stable_id"]


def _validate_private_directory(path: Path) -> None:
    if not path.is_dir():
        raise QueueServiceError(f"local daemon root is missing: {path}")
    details = path.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise QueueStorageError("local daemon root must be owner-permissioned")


def _validate_distinct_roots(config: LocalDaemonConfig) -> None:
    if not config.coordinator_root.exists() or not config.agent_root.exists():
        raise QueueServiceError("local daemon initialized roots are missing")
    if (
        config.coordinator_root.resolve() == config.agent_root.resolve()
        or config.coordinator_root.stat().st_ino == config.agent_root.stat().st_ino
    ):
        raise QueueServiceError("coordinator and local-agent roots must not alias")


def _acquire_lock(root: Path):  # type: ignore[no-untyped-def]
    lock_path = root / "owner.lock"
    lock = lock_path.open("a+", encoding="utf-8")
    lock_path.chmod(0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock.close()
        raise QueueServiceError(f"local daemon role is already locked: {root}") from exc
    return lock


def _admission_from_row(row: sqlite3.Row) -> LocalDaemonAdmission:
    return LocalDaemonAdmission(
        admission_id=str(row["admission_id"]),
        queue_item_id=str(row["queue_item_id"]),
        coordinator_id=str(row["coordinator_id"]),
        run_uri=str(row["run_uri"]),
        intent_digest=str(row["intent_digest"]),
        execution_owner=str(row["execution_owner"]),
        state=LocalDaemonAdmissionState(str(row["state"])),
        accepted_at=str(row["accepted_at"]),
        authority_operation_id=str(row["authority_operation_id"]),
        cancellation_operation_id=(
            None
            if row["cancellation_operation_id"] is None
            else str(row["cancellation_operation_id"])
        ),
        blocked_reason=(
            None if row["blocked_reason"] is None else str(row["blocked_reason"])
        ),
    )


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is not None and (not isinstance(value, str) or not value):
        raise QueueServiceError(f"{field} must be null or a non-empty string")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise QueueServiceError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )


__all__ = [
    "LocalDaemon",
    "LocalDaemonAdmission",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "LocalDaemonClientView",
    "LocalDaemonConfig",
    "LocalDaemonOperatorView",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "LocalDaemonStatus",
]
