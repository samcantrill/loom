"""Agent-owned scheduler calls and acknowledged coordinator projections.

The assignment is the capacity reservation. This journal adds no resource count;
its outbox binds one protected profile and one external operation to that owner.
"""

from __future__ import annotations

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import monotonic
from typing import cast

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.executors.slurm.commands import SlurmCommandResult, ready_stage_command_policy
from loom.pipeline.executors.slurm.errors import SlurmCommandOutputLimitError
from loom.pipeline.executors.slurm.history import operation_job_name, partition_accounting_output
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    SlurmReadyStageRequest,
    SlurmReadyStageSubmission,
    SlurmContainmentReceipt,
    resolve_slurm_containment,
)
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from ._slurm_result_transport import SharedSlurmResult
from ._slurm_admission import submit_interval
from ._slurm_observation import SlurmObservationPolicy, parse_slurm_observation_policy
from .errors import QueueConflictError, QueueServiceError
from .slurm_ready_stage import SlurmStageAssignment


class SlurmSubmissionProjection:
    """Read acknowledged agent evidence; never invoke a scheduler command."""

    def __init__(
        self, path: Path, *, _allow_initialize: bool = False,
        sqlite_policy: SQLitePolicy | None = None, schema_version: int = 3,
    ) -> None:
        if type(schema_version) is not int or schema_version not in {3, 4}:
            raise QueueServiceError("SLURM submission projection schema selection is unsupported")
        self.path = path
        self._sqlite_policy = sqlite_policy
        self.schema_version = schema_version
        if _allow_initialize:
            path.parent.mkdir(parents=True, exist_ok=True)
            with (sqlite3.connect(path) if sqlite_policy is None else initialize_database(path, policy=sqlite_policy, isolation_level="")) as conn:
                if conn.execute("PRAGMA user_version").fetchone()[0] not in {0, schema_version}:
                    raise QueueServiceError("SLURM projection requires a stopped-owner schema migration")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS ready_stage_submissions (operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, value_json TEXT NOT NULL)"
                )
                conn.execute(f"PRAGMA user_version = {schema_version}")

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise QueueServiceError("SLURM submission projection is missing")
        return (
            sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True)
            if self._sqlite_policy is None else
            connect_existing(self.path, policy=self._sqlite_policy, isolation_level="")
        )

    def _open_existing(self) -> None:
        with self._connect() as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(ready_stage_submissions)")
            }
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != self.schema_version or columns != {"operation_id", "state", "value_json"}:
            raise QueueServiceError("SLURM submission projection is incompatible")

    def find(self, operation_id: str) -> SlurmReadyStageSubmission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM ready_stage_submissions WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        return (
            None
            if row is None
            else SlurmReadyStageSubmission.from_dict(json.loads(str(row[0])))
        )

    def read(self, operation_id: str) -> SlurmReadyStageSubmission:
        value = self.find(operation_id)
        if value is None:
            raise QueueConflictError("SLURM submission evidence is unavailable")
        return value

    def list_nonterminal(self) -> tuple[SlurmReadyStageSubmission, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT value_json FROM ready_stage_submissions WHERE state NOT IN ('rejected', 'conflict') ORDER BY operation_id"
            ).fetchall()
        return tuple(
            SlurmReadyStageSubmission.from_dict(json.loads(str(row[0]))) for row in rows
        )

    def acknowledge(self, submission: SlurmReadyStageSubmission) -> None:
        self._open_existing()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ready_stage_submissions VALUES (?, ?, ?) "
                "ON CONFLICT(operation_id) DO UPDATE SET state=excluded.state, value_json=excluded.value_json",
                (
                    submission.request.operation_id,
                    submission.state.value,
                    _json(submission.to_dict()),
                ),
            )


class AgentSlurmJobs:
    """Open-only exact-agent submission owner with a durable replayable outbox."""

    def __init__(
        self, root: Path, profiles: Sequence[SlurmReadyStageProfile], *,
        sqlite_policy: SQLitePolicy | None = None, durable_files: str = "best_effort",
        submit_interval_seconds: float | None = None,
        observation_policy: SlurmObservationPolicy | None = None,
    ) -> None:
        self.submit_interval_seconds = submit_interval(submit_interval_seconds)
        self.observation_policy = parse_slurm_observation_policy(observation_policy)
        if self.observation_policy is not None:
            for profile in profiles:
                self.observation_policy.require_profile(profile)
        self._last_submit: float | None = None
        self.root = root
        self._sqlite_policy = sqlite_policy
        self._durable_files = durable_files
        self.path = root / "slurm.sqlite"
        self.journal = SQLiteReadyStageSubmissions(self.path, _allow_initialize=False, sqlite_policy=sqlite_policy)
        self.journal._open_existing()
        with self._connect() as conn:
            if {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(agent_slurm_operations)")
            } != {
                "operation_id",
                "assignment_json",
                "sequence",
                "evidence_json",
                "acknowledged",
                "released",
            }:
                raise QueueServiceError(
                    "agent SLURM journal is unavailable or incompatible"
                )
        self.profiles = {
            (p.profile_id, p.configuration_fingerprint): p for p in profiles
        }
        self._lock = RLock()
        self._next_poll: dict[str, float] = {}
        self._retry_at: dict[tuple[str, str], float] = {}
        self._retry_failures: dict[tuple[str, str], int] = {}
        self._batch_order: dict[str, int] = {}
        self._batch_sequence = 0
        self._replay_after: str | None = None
        self._batch_limits: dict[tuple[str, str], int] = {}
        self._reconciliation_binding: tuple[str, str] | None = None
        self._reconciled_operations: dict[str, tuple[object, object, bool]] = {}

    def begin_reconciliation(self, binding: tuple[str, str]) -> None:
        """Scope transient task confirmation to one authenticated session epoch."""
        with self._lock:
            if binding != self._reconciliation_binding:
                self._reconciliation_binding = binding
                self._reconciled_operations.clear()

    def has_unreconciled_work(self, binding: tuple[str, str]) -> bool:
        """Known live jobs may resume; uncertain effects must first reconcile.

        This is an admission check, not a release/retirement proof. The current
        coordinator must have redelivered each exact retained task, and the
        local submission and outbox must agree under the configured profile.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT operation_id, assignment_json, evidence_json, released, acknowledged "
                    "FROM agent_slurm_operations WHERE released=0 OR acknowledged=0"
                ).fetchall()
            for operation_id, encoded, evidence, released, acknowledged in rows:
                if not acknowledged:
                    return True
                if released:
                    continue
                if binding != self._reconciliation_binding or operation_id not in self._reconciled_operations:
                    return True
                assignment = SlurmStageAssignment.from_dict(json.loads(encoded))
                profile = self.profiles.get((assignment.profile_id, assignment.profile_configuration_fingerprint))
                submission = self.journal.find(operation_id)
                if (
                    profile is None or profile.descriptor != assignment.profile_descriptor
                    or submission is None or submission.request.digest != assignment.request_digest
                    or submission.state not in {ReadyStageState.INTENT, ReadyStageState.ACCEPTED}
                    or submission.state is ReadyStageState.ACCEPTED and submission.job_id is None
                ):
                    return True
                # A current coordinator may already be waiting for this known
                # job's containment proof. That does not make its ownership
                # uncertain or consume any additional local agent capacity.
                # Keep its reservation and release protocol, but allow other
                # work while the exact acknowledged handle awaits containment.
                if self._reconciled_operations[operation_id][:2] != (submission.job_id, submission.cluster):
                    return True
                if evidence is None:
                    return True
                retained = json.loads(evidence)
                if (
                    retained.get("release") is not None
                    or SlurmReadyStageSubmission.from_dict(retained["submission"]) != submission
                ):
                    return True
            return False

    def _retry_due(self, kind: str, operation_id: str) -> bool:
        return self.observation_policy is None or monotonic() >= self._retry_at.get((kind, operation_id), 0)

    def _retry_completed(
        self, kind: str, operation_id: str, profile: SlurmReadyStageProfile, *, failed: bool,
    ) -> None:
        policy = self.observation_policy
        if policy is None:
            return
        key = kind, operation_id
        failures = min(self._retry_failures.get(key, 0) + 1, 33) if failed else 0
        self._retry_failures[key] = failures
        self._retry_at[key] = monotonic() + policy.delay(profile.poll_interval_seconds, failures)

    def _observation_completed(
        self, value: SlurmReadyStageSubmission, profile: SlurmReadyStageProfile,
    ) -> None:
        self._retry_completed(
            "observation", value.request.operation_id, profile,
            failed=value.scheduler_source == "unavailable" and value.evidence != "slurm_history_not_found",
        )

    def _containment(
        self, profile: SlurmReadyStageProfile, operation_id: str, request: Mapping[str, PlainData],
    ) -> SlurmContainmentReceipt:
        if not self._retry_due("containment", operation_id):
            return SlurmContainmentReceipt("UNKNOWN")
        receipt = resolve_slurm_containment(profile, request)
        self._retry_completed("containment", operation_id, profile, failed=not receipt.contained)
        return receipt

    @staticmethod
    def _deliver_result(
        task: Mapping[str, PlainData], reply: Mapping[str, PlainData],
        transport: SharedSlurmResult,
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
    ) -> None:
        identity = task.get("result_identity")
        if (
            isinstance(identity, Mapping)
            and identity.get("fence") is not None
            and reply.get("cancel_requested") is not True
        ):
            if task.get("release_requested") is True:
                # The authority retains the result; replay its exact commit even
                # when shared cleanup was interrupted after removing some files.
                transport.finish_delivery(cast(Mapping[str, PlainData], identity), acknowledge)
            else:
                transport.deliver(cast(Mapping[str, PlainData], identity), acknowledge)

    @staticmethod
    def initialize(root: Path, *, sqlite_policy: SQLitePolicy | None = None) -> None:
        path = root / "slurm.sqlite"
        if path.exists():
            raise QueueConflictError(
                "agent SLURM initialization requires a fresh journal"
            )
        SQLiteReadyStageSubmissions(path, sqlite_policy=sqlite_policy)
        with (sqlite3.connect(path) if sqlite_policy is None else connect_existing(path, policy=sqlite_policy, isolation_level="")) as conn:
            conn.execute(
                "CREATE TABLE agent_slurm_operations (operation_id TEXT PRIMARY KEY, "
                "assignment_json TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "evidence_json TEXT, acknowledged INTEGER NOT NULL, released INTEGER NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return (
            sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True)
            if self._sqlite_policy is None else
            connect_existing(self.path, policy=self._sqlite_policy, isolation_level="")
        )

    def offered_profiles(self) -> tuple[tuple[str, str], ...]:
        """Qualify submission commands at the submit host, without a GPU debit."""
        return tuple(
            key for key, profile in self.profiles.items() if profile.preflight() is None
        )

    def has_retained_work(self) -> bool:
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM agent_slurm_operations WHERE released=0 OR acknowledged=0 LIMIT 1"
                ).fetchone()
                is not None
            )

    def has_started_or_unacknowledged_work(self) -> bool:
        """Unsubmitted, acknowledged intents may resume under unchanged bindings.

        They remain retained work for reload and retirement. Missing journals,
        uncertain calls and unacknowledged effects cannot use this exception.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT operation_id, released, acknowledged FROM agent_slurm_operations "
                    "WHERE released=0 OR acknowledged=0"
                ).fetchall()
            for operation_id, released, acknowledged in rows:
                if not acknowledged:
                    return True
                if not released and self.journal.read(operation_id).state is not ReadyStageState.INTENT:
                    return True
            return False

    def _publish(
        self,
        assignment: SlurmStageAssignment,
        submission: SlurmReadyStageSubmission,
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
        *,
        release: Mapping[str, PlainData] | None = None,
        recovery_evidence: Mapping[str, PlainData] | None = None,
        provider_released: bool = False,
    ) -> Mapping[str, PlainData]:
        evidence: dict[str, PlainData] = {
            "schema_version": 1,
            "provider_released": provider_released,
            "assignment": assignment.to_dict(),
            "submission": submission.to_dict(),
            "release": None if release is None else dict(release),
            "recovery_evidence": None
            if recovery_evidence is None
            else dict(recovery_evidence),
        }
        encoded = _json(evidence)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT sequence, evidence_json, acknowledged FROM agent_slurm_operations WHERE operation_id=?",
                (assignment.operation_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError("agent SLURM operation is not durable")
            if not row[2] and row[1] is not None and str(row[1]) != encoded:
                raise QueueConflictError(
                    "agent SLURM outbox must replay before advancing"
                )
            sequence = int(row[0]) + (str(row[1]) != encoded)
            conn.execute(
                "UPDATE agent_slurm_operations SET sequence=?, evidence_json=?, acknowledged=0 WHERE operation_id=?",
                (sequence, encoded, assignment.operation_id),
            )
        response = acknowledge({**evidence, "sequence": sequence})
        if response.get("sequence") != sequence:
            raise QueueConflictError("agent SLURM acknowledgement conflicts")
        if provider_released:
            profile = self.profiles[
                (assignment.profile_id, assignment.profile_configuration_fingerprint)
            ]
            transport = SharedSlurmResult(
                profile.result_storage, assignment.assignment_id
            )
            if transport.path.exists() and (
                response.get("cancel_requested") is True
                or not (transport.path / "manifest.json").exists()
            ):
                transport.cleanup()
        # Preserve the pending outbox until acknowledged transport retirement
        # finishes, so a cleanup interruption can replay even a released task.
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_slurm_operations SET acknowledged=1, released=? WHERE operation_id=? AND sequence=?",
                (int(provider_released), assignment.operation_id, sequence),
            )
        if provider_released:
            self._reconciled_operations.pop(assignment.operation_id, None)
            self._next_poll.pop(assignment.operation_id, None)
            self._batch_order.pop(assignment.operation_id, None)
            for kind in ("observation", "cancel", "containment"):
                self._retry_at.pop((kind, assignment.operation_id), None)
                self._retry_failures.pop((kind, assignment.operation_id), None)
        return response

    def replay_pending(
        self, acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]]
    ) -> None:
        """Replay a bounded page, including final receipts for released assignments.

        Advance the transient scan before transport: a failing acknowledgement
        stays durable but cannot hide all later receipts on every iteration.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT operation_id, evidence_json FROM agent_slurm_operations "
                    "WHERE acknowledged=0 AND evidence_json IS NOT NULL "
                    "AND (? IS NULL OR operation_id > ?) ORDER BY operation_id LIMIT 32",
                    (self._replay_after, self._replay_after),
                ).fetchall()
            for row in rows:
                self._replay_after = str(row[0])
                pending = json.loads(str(row[1]))
                self._publish(
                    SlurmStageAssignment.from_dict(pending["assignment"]),
                    SlurmReadyStageSubmission.from_dict(pending["submission"]),
                    acknowledge,
                    release=pending["release"],
                    recovery_evidence=pending.get("recovery_evidence"),
                    provider_released=pending.get("provider_released", False),
                )
            if len(rows) < 32:
                self._replay_after = None

    def _before_submit(
        self, assignment: SlurmStageAssignment, value: SlurmReadyStageSubmission,
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
    ) -> bool:
        if self._publish(assignment, value, acknowledge).get("cancel_requested") is True:
            return False
        # Timestamp the actual call boundary, after its durable acknowledgement.
        # A failed acknowledgement never consumes a pacing interval.
        self._last_submit = monotonic()
        return True

    def step(
        self,
        task: Mapping[str, PlainData],
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
        *,
        allow_submission: bool = True,
    ) -> None:
        """Drive one bounded observation cycle, replaying before any new effect."""
        with self._lock:
            self._step(task, acknowledge, allow_submission=allow_submission)

    def step_cycle(
        self, tasks: Sequence[Mapping[str, PlainData]],
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
        *, allow_submission: bool = True,
    ) -> None:
        """Deliver this page's results before bounded, fair accounting batches.

        The shared budget covers ordinary accounting queries. Submission,
        cancellation, helper calls, transport and filesystem IO are separate.
        """
        policy = self.observation_policy
        if policy is None or policy.max_jobs_per_query is None:
            for task in tasks:
                self.step(task, acknowledge, allow_submission=allow_submission)
            return
        with self._lock:
            for task in tasks:
                self._step(task, acknowledge, allow_submission=False, _defer_observation=True, _delivery_only=True)
            for task in tasks:
                self._step(task, acknowledge, allow_submission=allow_submission, _defer_observation=True)
            self._observe_batches(tasks, acknowledge, policy)

    def _observe_batches(self, tasks, acknowledge, policy: SlurmObservationPolicy) -> None:
        assert policy.max_jobs_per_query is not None
        assert policy.max_queries_per_cycle is not None and policy.cycle_budget_seconds is not None
        due = {}
        for task in tasks:
            assignment = SlurmStageAssignment.from_dict(task["assignment"])
            operation = assignment.operation_id
            with self._connect() as conn:
                released = conn.execute(
                    "SELECT released FROM agent_slurm_operations WHERE operation_id=?", (operation,),
                ).fetchone()
            if released is None or released[0] or not self._retry_due("observation", operation):
                continue
            current = self.journal.read(operation)
            if current.state in {ReadyStageState.ACCEPTED, ReadyStageState.SUBMITTING, ReadyStageState.UNKNOWN}:
                key = assignment.profile_id, assignment.profile_configuration_fingerprint
                due[operation] = (task, assignment, current, key)
        remaining = sorted(due.values(), key=lambda item: self._batch_order.get(item[1].operation_id, 0))
        deadline = monotonic() + policy.cycle_budget_seconds
        calls = 0
        while remaining and calls < policy.max_queries_per_cycle:
            time_left = deadline - monotonic()
            if time_left <= 0:
                break
            key = remaining[0][3]
            profile = self.profiles[key]
            history = profile.accounting_history
            command_policy = ready_stage_command_policy(profile.runner)
            assert history is not None and command_policy is not None
            limit = min(policy.max_jobs_per_query, self._batch_limits.get(key, policy.max_jobs_per_query))
            batch = [item for item in remaining if item[3] == key][:limit]
            operations = {item[1].operation_id for item in batch}
            remaining = [item for item in remaining if item[1].operation_id not in operations]
            names = [operation_job_name(item[1].operation_id) for item in batch]
            observed_at = utc_timestamp()
            result: SlurmCommandResult | Exception
            partitioned: dict[str, str] = {}
            try:
                windows = [history.window(item[2].created_at, observed_at) for item in batch]
                time_left = deadline - monotonic()
                if time_left <= 0:
                    break
                calls += 1
                result = getattr(profile.runner, "discover_named_operations")(
                    job_names=names, user_id=history.user_id, cluster=profile.cluster,
                    started_after=min(window[0] for window in windows),
                    ended_before=max(window[1] for window in windows),
                    timeout_seconds=min(command_policy.observation_timeout_seconds, time_left),
                )
                if "...[truncated]" in result.stderr:
                    raise SlurmCommandOutputLimitError("accounting batch stderr is truncated")
                # Do not treat any captured prefix as a complete response.
                partitioned = partition_accounting_output(result.stdout, names)
            except Exception as exc:
                result = exc
                if isinstance(exc, SlurmCommandOutputLimitError):
                    self._batch_limits[key] = max(1, len(batch) // 2)
            for task, assignment, _current, _key in batch:
                operation = assignment.operation_id
                self._batch_sequence += 1
                self._batch_order[operation] = self._batch_sequence
                filtered = (
                    replace(result, stdout=partitioned[operation_job_name(operation)])
                    if isinstance(result, SlurmCommandResult) else result
                )
                current = self.journal._apply_accounting_observation(
                    operation, profile, filtered, observed_at=observed_at,
                )
                self._retry_completed(
                    "observation", operation, profile,
                    failed=current.evidence not in {"slurm_history_observed", "slurm_history_not_found"},
                )
                reply = self._publish(assignment, current, acknowledge)
                self._deliver_result(
                    task, reply, SharedSlurmResult(profile.result_storage, assignment.assignment_id), acknowledge,
                )

    def _step(
        self,
        task: Mapping[str, PlainData],
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
        *,
        allow_submission: bool,
        _defer_observation: bool = False,
        _delivery_only: bool = False,
    ) -> None:
        if task.get("schema_version") != 1:
            raise QueueServiceError("agent SLURM task version is unsupported")
        assignment = SlurmStageAssignment.from_dict(task.get("assignment"))
        request = SlurmReadyStageRequest.from_dict(task.get("request"))
        if (
            request.operation_id != assignment.operation_id
            or request.digest != assignment.request_digest
        ):
            raise QueueConflictError("agent SLURM request identity conflicts")
        profile = self.profiles.get(
            (assignment.profile_id, assignment.profile_configuration_fingerprint)
        )
        if profile is None or profile.descriptor != assignment.profile_descriptor:
            raise QueueConflictError("agent SLURM protected profile is unavailable")
        encoded_assignment = _json(assignment.to_dict())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT assignment_json, sequence, evidence_json, acknowledged FROM agent_slurm_operations WHERE operation_id=?",
                (assignment.operation_id,),
            ).fetchone()
            if row is None:
                if task.get("expected_sequence") != 0:
                    raise QueueConflictError(
                        "expected agent SLURM operation is missing; recovery unresolved"
                    )
                conn.execute(
                    "INSERT INTO agent_slurm_operations VALUES (?, ?, 0, NULL, 1, 0)",
                    (assignment.operation_id, encoded_assignment),
                )
            elif str(row[0]) != encoded_assignment:
                raise QueueConflictError("agent SLURM assignment replay conflicts")
        if self._reconciliation_binding is not None:
            self._reconciled_operations[assignment.operation_id] = (
                task.get("job_id"), task.get("cluster"), task.get("release_requested") is True,
            )
        if row is not None and row[2] is not None and not row[3]:
            pending = json.loads(str(row[2]))
            self._publish(
                assignment,
                SlurmReadyStageSubmission.from_dict(pending["submission"]),
                acknowledge,
                release=pending["release"],
                recovery_evidence=pending.get("recovery_evidence"),
                provider_released=pending.get("provider_released", False),
            )
        with self._connect() as conn:
            retained = conn.execute(
                "SELECT released, evidence_json, acknowledged FROM agent_slurm_operations WHERE operation_id=?",
                (request.operation_id,),
            ).fetchone()
        if retained is not None and retained[0]:
            self._reconciled_operations.pop(assignment.operation_id, None)
            return
        if self.observation_policy is not None and retained is not None and retained[1] is not None and retained[2]:
            last = json.loads(str(retained[1]))
            if last["release"] is not None:
                # A positive release acknowledgement already crossed the durable
                # outbox. Finish the exact revoke/release without another query.
                completed = SlurmReadyStageSubmission.from_dict(last["submission"])
                if completed.capability is None:
                    raise QueueConflictError("agent SLURM capability is unavailable")
                profile.job_private_file_provider.revoke(completed.capability)
                self._publish(
                    assignment, completed, acknowledge,
                    release=last["release"], provider_released=True,
                )
                return
        current = self.journal.find(request.operation_id)
        transport = SharedSlurmResult(profile.result_storage, assignment.assignment_id)
        if current is None and task.get("cancel_requested") is not True:
            transport.reserve(assignment.to_dict())
        now = monotonic()
        urgent_cancel = (
            current is not None
            and current.job_id is not None
            and not current.cancel_requested
            and task.get("cancel_requested") is True
        )
        if (
            self.observation_policy is None
            and current is not None
            and current.state is not ReadyStageState.INTENT
            and now < self._next_poll.get(request.operation_id, 0)
            and not urgent_cancel
            and task.get("recovery_request") is None
            and task.get("release_requested") is not True
        ):
            return
        if self.observation_policy is None:
            self._next_poll[request.operation_id] = now + profile.poll_interval_seconds
        observation_due = not _defer_observation and self._retry_due("observation", request.operation_id)
        observed = False
        script = self.root / "slurm-scripts" / f"{assignment.assignment_id}.sh"
        if current is None:
            atomic_write_bytes(script, request.script.encode("utf-8"), durability=self._durable_files)
            script.chmod(0o600)
        current = self.journal.prepare(request, profile, script)
        if current.state is ReadyStageState.INTENT:
            reply = self._publish(assignment, current, acknowledge)
            if reply.get("cancel_requested") is True:
                current = self.journal.suppress_before_submit(request.operation_id)
            elif not allow_submission:
                return
            elif (
                self.submit_interval_seconds is not None
                and self._last_submit is not None
                and monotonic() < self._last_submit + self.submit_interval_seconds
            ):
                return
            else:
                current = self.journal.submit(
                    request,
                    profile,
                    script,
                    before_runner=lambda value: self._before_submit(assignment, value, acknowledge),
                )
        elif current.state in {ReadyStageState.SUBMITTING, ReadyStageState.UNKNOWN}:
            job = task.get("job_id")
            if isinstance(job, str):
                current = self.journal.associate_handle(
                    request.operation_id,
                    profile,
                    job_id=job,
                    cluster=cast(str | None, task.get("cluster")),
                )
            elif observation_due:
                current = self.journal.reconcile(request.operation_id, profile)
                self._retry_completed(
                    "observation", request.operation_id, profile,
                    failed=current.evidence not in {
                        "slurm_operation_reconciled", "slurm_operation_not_found", "slurm_history_not_found",
                    },
                )
                observed = self.observation_policy is not None
        reply = self._publish(assignment, current, acknowledge)
        if self.observation_policy is not None:
            self._deliver_result(task, reply, transport, acknowledge)
        if _delivery_only:
            return
        if current.job_id is not None:
            published = current
            if reply.get("cancel_requested") is True and (
                self.observation_policy is None
                or not current.cancel_requested and self._retry_due("cancel", request.operation_id)
            ):
                current = self.journal.request_cancel(
                    request.operation_id, profile,
                    _after_observation=(
                        None if self.observation_policy is None
                        else lambda value: self._observation_completed(value, profile)
                    ),
                )
                self._retry_completed("cancel", request.operation_id, profile, failed=not current.cancel_requested)
                if self.observation_policy is not None and profile.accounting_history is not None:
                    observed = True  # Cancellation performs its own fresh identity observation.
            if self.observation_policy is None or observation_due and not observed:
                current = self.journal.observe(request.operation_id, profile)
                self._observation_completed(current, profile)
            if self.observation_policy is None or current != published:
                updated = self._publish(assignment, current, acknowledge)
                if self.observation_policy is not None:
                    reply = updated
        if self.observation_policy is None:
            self._deliver_result(task, reply, transport, acknowledge)
        recovery_request = task.get("recovery_request")
        if isinstance(recovery_request, Mapping):
            receipt = self._containment(profile, request.operation_id, recovery_request)
            if receipt.contained:
                assert profile.containment_helper is not None
                self._publish(
                    assignment,
                    current,
                    acknowledge,
                    recovery_evidence={
                        "kind": "slurm_helper",
                        "state": "CONTAINED",
                        "helper_descriptor": profile.containment_helper.descriptor,
                        "evidence_id": receipt.evidence_id,
                        "evidence_revision": receipt.evidence_revision,
                        "echo": dict(recovery_request),
                    },
                )
            return
        release: Mapping[str, PlainData] | None = None
        if current.state is ReadyStageState.REJECTED:
            release = {"kind": "definite_rejection"}
        elif current.job_id is not None and (
            task.get("release_requested") is True
            or reply.get("cancel_requested") is True
        ):
            proof = {
                **cast(Mapping[str, PlainData], task["containment_request"]),
                "job_id": current.job_id,
                "cluster_id": current.cluster,
            }
            receipt = self._containment(profile, request.operation_id, proof)
            if receipt.contained:
                release = {
                    "kind": "slurm_helper",
                    "state": receipt.state,
                    "evidence_id": receipt.evidence_id,
                    "evidence_revision": receipt.evidence_revision,
                    "echo": None if receipt.echo is None else dict(receipt.echo),
                }
        if release is not None:
            if current.capability is None:
                raise QueueConflictError("agent SLURM capability is unavailable")
            self._publish(assignment, current, acknowledge, release=release)
            profile.job_private_file_provider.revoke(current.capability)
            self._publish(
                assignment,
                current,
                acknowledge,
                release=release,
                provider_released=True,
            )


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
