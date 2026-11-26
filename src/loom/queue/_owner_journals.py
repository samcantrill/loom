"""Read each native journal at its own revision for a bounded batch of admissions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, cast

from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageSubmission
from loom.pipeline.orchestration import StageWorkRecord
from loom.pipeline.runtime import ExecutionRouteKind
from loom.serialization import PlainData

from ._coordinator_run_progress import _profile_satisfies_requirement
from ._managed_contracts import _assignment_from_dict, _decode_decline_reason
from ._owner_store import _connect_existing_sqlite, _verify_owner_store_binding
from ._owner_views import project_owner_view
from ._remote_stage_execution import ResidentProfileDescriptor
from .errors import QueueServiceError

if TYPE_CHECKING:
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot

    from .local_daemon import LocalDaemonAdmission, LocalDaemonConfig


type _Rows = list[dict[str, PlainData]]


@dataclass(frozen=True, slots=True)
class SlurmStorageFacts:
    assignment_id: str
    provider_released: bool
    agent_evidence_accepted_at: str | None
    compute_released_at: str | None
    publication_requested_at: str | None
    publication_completed_at: str | None
    publication_cancelled_at: str | None


@dataclass(frozen=True, slots=True)
class StorageObserver:
    path: Path
    schema_version: int
    project: Callable[[Sequence[SlurmStorageFacts]], dict[str, PlainData]]


@dataclass(slots=True)
class _ExecutionRows:
    work: _Rows = field(default_factory=list)
    assignments: _Rows = field(default_factory=list)
    slurm: _Rows = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExecutionJournalRead:
    by_run: dict[str, _ExecutionRows]
    scheduling_revision: int | None
    assignment_revision: int | None
    storage: dict[str, list[SlurmStorageFacts]]
    observed_at: str


@dataclass(frozen=True, slots=True)
class AgentJournalRead:
    by_run: dict[str, _Rows]
    revision: int | None
    observed_at: str


def read_owner_journals(
    config: LocalDaemonConfig,
    run_uris: tuple[str, ...],
    *,
    coordinator_id: str,
    agent_id: str | None,
    clock: Callable[[], str],
    read_snapshot: Callable[[str], AuthoritativeRunSnapshot] | None = None,
    observe_storage: StorageObserver | None = None,
) -> Callable[[LocalDaemonAdmission, int], Mapping[str, PlainData]]:
    admission_observed_at = clock()
    execution = read_execution_journal(config, run_uris, coordinator_id, clock, storage=observe_storage)
    assignment_ids = {
        uri: tuple(cast(str, row["assignment_id"]) for row in records.assignments)
        for uri, records in execution.by_run.items()
    }
    agent = read_agent_journal(config, run_uris, assignment_ids, agent_id, clock)

    def view_for(admission: LocalDaemonAdmission, admission_revision: int) -> Mapping[str, PlainData]:
        view = project_owner_view(
            config,
            admission,
            admission_revision,
            admission_observed_at=admission_observed_at,
            execution=execution,
            agent=agent,
            clock=clock,
            read_snapshot=read_snapshot,
        )

        if observe_storage is not None:
            facts = execution.storage.get(admission.run_uri)
            view["slurm_storage"] = (
                observe_storage.project(facts)
                if facts is not None
                else {
                    "availability": "unavailable",
                    "diagnostic": "slurm_storage_unavailable",
                    "assignments": [],
                }
            )
        return view

    return view_for


def _read_isolated[T](
    run_uris: tuple[str, ...],
    read: Callable[[tuple[str, ...]], dict[str, T]],
) -> dict[str, T]:
    """Isolate an unattributed SQLite row-read failure within this owner's snapshot."""
    try:
        return read(run_uris)
    except sqlite3.Error as exc:
        # Missing schema, corrupt database, lock or I/O failure affects this store.
        # Row conversion errors can come from the driver before it yields a row.
        code = (getattr(exc, "sqlite_errorcode", None) or 0) & 255
        if code not in (0, sqlite3.SQLITE_TOOBIG, sqlite3.SQLITE_MISMATCH) or len(run_uris) <= 1:
            raise
    recovered: dict[str, T] = {}
    for uri in run_uris:
        try:
            recovered.update(read((uri,)))
        except sqlite3.Error:
            pass  # No complete observation of this owner for this run.
    return recovered


def _append_rows[T](
    by_run: dict[str, T],
    rows: Iterable[sqlite3.Row],
    run_for: Callable[[sqlite3.Row], str],
    append: Callable[[T, sqlite3.Row], None],
) -> None:
    for row in rows:
        uri = run_for(row)
        if uri in by_run:
            try:
                append(by_run[uri], row)
            except Exception:
                # One malformed owner row invalidates all of this owner's axes for that run.
                del by_run[uri]


def read_execution_journal(
    config: LocalDaemonConfig,
    run_uris: tuple[str, ...],
    coordinator_id: str,
    clock: Callable[[], str],
    *,
    storage: StorageObserver | None,
) -> ExecutionJournalRead:
    database = config.execution_database
    storage_by_run: dict[str, list[SlurmStorageFacts]] = {}
    if storage is not None and storage.path != database:
        # The active service can still own an open installation when the
        # configured observation path is unavailable. Verify that exact owner.
        try:
            with closing(_connect_existing_sqlite(storage.path, sqlite_policy=config.sqlite_policy)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN")
                _verify_owner_store_binding(conn, role="coordinator", stable_id=coordinator_id)
                storage_by_run = _read_storage(conn, run_uris, storage.schema_version)
        except (OSError, sqlite3.Error):
            pass

    try:
        with closing(_connect_existing_sqlite(database, sqlite_policy=config.sqlite_policy)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            _verify_owner_store_binding(conn, role="coordinator", stable_id=coordinator_id)
            if storage is not None and storage.path == database:
                storage_by_run = _read_storage(conn, run_uris, storage.schema_version)
            revisions = dict(conn.execute("SELECT axis, revision FROM local_daemon_status_revisions"))
            scheduling, assignment = int(revisions["scheduling"]), int(revisions["assignment"])
            profiles = list(config.remote_profiles)
            resident = config.resident_worker_launch_profile
            if resident is not None:
                profiles.append(ResidentProfileDescriptor.from_dict(resident.descriptor))

            def read(uris: tuple[str, ...]) -> dict[str, _ExecutionRows]:
                return _read_execution_rows(conn, uris, profiles)

            by_run = _read_isolated(run_uris, read)
    except Exception:
        return ExecutionJournalRead({}, None, None, storage_by_run, clock())
    return ExecutionJournalRead(by_run, scheduling, assignment, storage_by_run, clock())


def _nullable_text(row: sqlite3.Row, column: str) -> str | None:
    # SQLite's TEXT affinity also permits blobs. Decode at the owner boundary
    # so the enclosing row reader can attribute a bad value to its run.
    value = row[column]
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"invalid text in journal column {column}")


def _indexed_run(row: sqlite3.Row) -> str:
    return str(row["run_uri"])


def _read_execution_rows(
    conn: sqlite3.Connection,
    uris: tuple[str, ...],
    profiles: Sequence[ResidentProfileDescriptor],
) -> dict[str, _ExecutionRows]:
    by_run = {uri: _ExecutionRows() for uri in uris}
    parameters = ",".join("?" for _ in uris)
    stage_rows = conn.execute(
        f"SELECT run_uri, record_json FROM stage_work WHERE run_uri IN ({parameters}) ORDER BY stage_work_id",
        uris,
    )

    def append_stage(records: _ExecutionRows, row: sqlite3.Row) -> None:
        record = StageWorkRecord.from_dict(json.loads(row["record_json"]))
        if record.run_uri != row["run_uri"]:
            raise QueueServiceError("stage work run identity conflicts with its index")
        incompatible = (
            record.scheduling_state.value == "ready"
            and record.placement.route.kind is ExecutionRouteKind.MANAGED_AGENT
            and not any(
                _profile_satisfies_requirement(profile, record.execution_requirement) for profile in profiles
            )
        )
        records.work.append(
            {
                "stage_work_id": record.stage_work_id,
                "stage_name": record.stage_name,
                "state": record.scheduling_state.value,
                "projection_revision": record.projection_revision,
                "diagnostic": "incompatible_profile"
                if incompatible
                else record.scheduling_diagnostics.get("code"),
            }
        )

    _append_rows(by_run, stage_rows, _indexed_run, append_stage)
    assignments = conn.execute(
        "SELECT a.assignment_id, a.run_uri, a.stage_work_id, a.identity_json, a.state, a.agent_id, "
        "a.session_id, a.offer_id, a.claim_id, a.receipt_json, e.payload_json AS decline_json "
        "FROM coordinator_assignments AS a "
        "LEFT JOIN coordinator_events AS e ON e.assignment_id = a.assignment_id "
        "AND e.event_id = a.assignment_id || ':definitive_decline' "
        f"WHERE a.run_uri IN ({parameters}) ORDER BY a.assignment_id",
        uris,
    )
    _append_rows(by_run, assignments, _indexed_run, _append_assignment)
    slurm = conn.execute(
        "SELECT a.assignment_id, a.run_uri, a.state, a.profile_id, a.operation_id, a.job_id, a.cluster, "
        "a.bootstrap_incarnation, a.input_ready, a.fence, a.process_execution_id, a.report_json, "
        "a.identity_json, s.value_json FROM slurm_stage_assignments AS a "
        "LEFT JOIN ready_stage_submissions AS s ON s.operation_id = a.operation_id "
        f"WHERE a.run_uri IN ({parameters}) ORDER BY a.assignment_id",
        uris,
    )
    _append_rows(by_run, slurm, _indexed_run, _append_slurm)
    return by_run


def _append_assignment(records: _ExecutionRows, row: sqlite3.Row) -> None:
    assignment = _assignment_from_dict(json.loads(row["identity_json"]))
    if any(
        getattr(assignment, key) != row[key]
        for key in (
            "assignment_id",
            "run_uri",
            "stage_work_id",
            "agent_id",
            "session_id",
            "offer_id",
            "claim_id",
        )
    ):
        raise QueueServiceError("coordinator assignment identity conflicts with its index")
    records.assignments.append(
        {
            "assignment_id": assignment.assignment_id,
            "target": "managed_agent",
            "state": str(row["state"]),
            "run_uri": assignment.run_uri,
            "stage_work_id": assignment.stage_work_id,
            "stage_name": assignment.stage_name,
            "attempt": assignment.attempt,
            "agent_id": assignment.agent_id,
            "session_id": assignment.session_id,
            "offer_id": assignment.offer_id,
            "claim_id": assignment.claim_id,
            "decline_reason_code": _decode_decline_reason(row["decline_json"])
            if row["decline_json"] is not None
            else None,
            "receipt_digest": hashlib.sha256(str(row["receipt_json"]).encode("utf-8")).hexdigest(),
        }
    )


def _append_slurm(records: _ExecutionRows, row: sqlite3.Row) -> None:
    report = json.loads(row["report_json"]) if row["report_json"] is not None else None
    report_status = report.get("status") if isinstance(report, Mapping) else None
    identity = json.loads(row["identity_json"])
    submission = (
        SlurmReadyStageSubmission.from_dict(json.loads(row["value_json"]))
        if row["value_json"] is not None
        else None
    )
    records.slurm.append(
        {
            "assignment_id": str(row["assignment_id"]),
            "target": "slurm",
            "agent_id": identity["agent_id"],
            "agent_root_id": identity["agent_root_id"],
            "state": str(row["state"]),
            "profile_id": str(row["profile_id"]),
            "operation_id": str(row["operation_id"]),
            "job_id": _nullable_text(row, "job_id"),
            "cluster": _nullable_text(row, "cluster"),
            "bootstrap_registered": row["bootstrap_incarnation"] is not None,
            "input_ready": bool(row["input_ready"]),
            "fence_bound": row["fence"] is not None,
            "process_execution_id": _nullable_text(row, "process_execution_id"),
            "loom_result_status": report_status if isinstance(report_status, str) else None,
            "diagnostic": _slurm_state_diagnostic(str(row["state"])),
            "submission": {
                "dispatch_state": submission.state.value if submission else "unavailable",
                "scheduler_state": submission.scheduler_state if submission else None,
                "scheduler_source": submission.scheduler_source if submission else None,
                "scheduler_observed_at": submission.scheduler_observed_at if submission else None,
                "conflicting_handles": [
                    {"job_id": job, "cluster": cluster} for job, cluster in submission.conflicting_handles
                ]
                if submission
                else [],
                "cancel_requested": submission.cancel_requested if submission else False,
            },
        }
    )


def _read_storage(
    conn: sqlite3.Connection,
    run_uris: tuple[str, ...],
    schema_version: int,
) -> dict[str, list[SlurmStorageFacts]]:
    # Storage is an independent supplemental observation, even when a stage or
    # assignment projection on the same database is corrupt.
    fields = (
        "publication_requested_at",
        "publication_completed_at",
        "publication_cancelled_at",
        "compute_released_at",
    )
    effects = ", ".join(fields if schema_version >= 5 else [f"NULL AS {name}" for name in fields])

    def read(uris: tuple[str, ...]) -> dict[str, list[SlurmStorageFacts]]:
        by_run: dict[str, list[SlurmStorageFacts]] = {uri: [] for uri in uris}
        parameters = ",".join("?" for _ in uris)
        rows = conn.execute(
            f"SELECT run_uri, assignment_id, agent_evidence_json, agent_evidence_accepted_at, {effects} "
            f"FROM slurm_stage_assignments WHERE run_uri IN ({parameters}) AND state != 'released' ORDER BY assignment_id",
            uris,
        )
        _append_rows(by_run, rows, _indexed_run, _append_storage)
        return by_run

    try:
        return _read_isolated(run_uris, read)
    except sqlite3.Error:
        return {}


def _append_storage(records: list[SlurmStorageFacts], row: sqlite3.Row) -> None:
    evidence = json.loads(row["agent_evidence_json"]) if row["agent_evidence_json"] is not None else None
    records.append(
        SlurmStorageFacts(
            assignment_id=str(row["assignment_id"]),
            provider_released=evidence is not None and evidence.get("provider_released") is True,
            agent_evidence_accepted_at=_nullable_text(row, "agent_evidence_accepted_at"),
            compute_released_at=_nullable_text(row, "compute_released_at"),
            publication_requested_at=_nullable_text(row, "publication_requested_at"),
            publication_completed_at=_nullable_text(row, "publication_completed_at"),
            publication_cancelled_at=_nullable_text(row, "publication_cancelled_at"),
        )
    )


def read_agent_journal(
    config: LocalDaemonConfig,
    run_uris: tuple[str, ...],
    ids_by_run: Mapping[str, tuple[str, ...]],
    agent_id: str | None,
    clock: Callable[[], str],
) -> AgentJournalRead:
    if config.agent_root is None or agent_id is None:
        return AgentJournalRead({}, None, clock())
    try:
        with closing(
            _connect_existing_sqlite(config.agent_journal, sqlite_policy=config.sqlite_policy)
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            _verify_owner_store_binding(conn, role="local-agent", stable_id=agent_id)
            row = conn.execute("SELECT revision FROM local_daemon_status_revision").fetchone()
            if row is None:
                raise sqlite3.DatabaseError("agent status revision is missing")
            revision = int(row[0])

            def read(uris: tuple[str, ...]) -> dict[str, _Rows]:
                by_run: dict[str, _Rows] = {uri: [] for uri in uris}
                owners = {identity: uri for uri in uris for identity in ids_by_run.get(uri, ())}
                ids = sorted(owners)
                limit = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)

                def append(records: _Rows, row: sqlite3.Row) -> None:
                    _append_agent_assignment(records, row, owners[row["assignment_id"]])

                for start in range(0, len(ids), limit):
                    chunk = ids[start : start + limit]
                    parameters = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        "SELECT assignment_id, identity_json, state, process_execution_id, grant_fence, availability_revision "
                        f"FROM assignments WHERE assignment_id IN ({parameters}) ORDER BY assignment_id",
                        chunk,
                    )
                    _append_rows(by_run, rows, lambda row: owners[row["assignment_id"]], append)
                return by_run

            by_run = _read_isolated(run_uris, read)
    except Exception:
        return AgentJournalRead({}, None, clock())
    return AgentJournalRead(by_run, revision, clock())


def _append_agent_assignment(records: _Rows, row: sqlite3.Row, run_uri: str) -> None:
    assignment = _assignment_from_dict(json.loads(row["identity_json"]))
    if assignment.assignment_id != row["assignment_id"] or assignment.run_uri != run_uri:
        raise QueueServiceError("agent assignment identity conflicts with its index")
    records.append(
        {
            "assignment_id": assignment.assignment_id,
            "state": str(row["state"]),
            "process_execution_id": _nullable_text(row, "process_execution_id"),
            "execution_fence": _nullable_text(row, "grant_fence"),
            "availability_revision": _nullable_text(row, "availability_revision"),
        }
    )


def _slurm_state_diagnostic(state: str) -> str | None:
    return {
        "reserved": "slurm_awaiting_authority_bind",
        "bound": "slurm_awaiting_submission",
        "submitting": "slurm_submission_unknown",
        "unknown": "slurm_submission_unknown",
        "conflict": "slurm_submission_conflict",
        "rejected": "slurm_submission_rejected",
        "accepted": "slurm_bootstrap_awaiting_registration",
        "granted": "slurm_bootstrap_awaiting_start",
        "running": "slurm_loom_result_awaiting_commit",
        "terminal": "slurm_result_committed",
        "logical_released": "slurm_release_awaiting_acknowledgement",
        "released": "slurm_released",
    }.get(state)
