"""Agent-owned scheduler calls and acknowledged coordinator projections.

The assignment is the capacity reservation. This journal adds no resource count;
its outbox binds one protected profile and one external operation to that owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import monotonic
from typing import cast

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    SlurmReadyStageRequest,
    SlurmReadyStageSubmission,
    resolve_slurm_containment,
)
from loom.serialization import PlainData

from .errors import QueueConflictError, QueueServiceError
from .slurm_ready_stage import SlurmStageAssignment


class SlurmSubmissionProjection:
    """Read acknowledged agent evidence; never invoke a scheduler command."""

    def __init__(self, path: Path, *, _allow_initialize: bool = False) -> None:
        self.path = path
        if _allow_initialize:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS ready_stage_submissions (operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, value_json TEXT NOT NULL)"
                )
                conn.execute("PRAGMA user_version = 3")

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise QueueServiceError("SLURM submission projection is missing")
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True)

    def _open_existing(self) -> None:
        with self._connect() as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(ready_stage_submissions)")
            }
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != 3 or columns != {"operation_id", "state", "value_json"}:
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

    def __init__(self, root: Path, profiles: Sequence[SlurmReadyStageProfile]) -> None:
        self.root = root
        self.path = root / "slurm.sqlite"
        self.journal = SQLiteReadyStageSubmissions(self.path, _allow_initialize=False)
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

    @staticmethod
    def initialize(root: Path) -> None:
        path = root / "slurm.sqlite"
        if path.exists():
            raise QueueConflictError(
                "agent SLURM initialization requires a fresh journal"
            )
        SQLiteReadyStageSubmissions(path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE agent_slurm_operations (operation_id TEXT PRIMARY KEY, "
                "assignment_json TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "evidence_json TEXT, acknowledged INTEGER NOT NULL, released INTEGER NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True)

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
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_slurm_operations SET acknowledged=1, released=? WHERE operation_id=? AND sequence=?",
                (int(provider_released), assignment.operation_id, sequence),
            )
        return response

    def replay_pending(
        self, acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]]
    ) -> None:
        """Replay even a final receipt whose assignment has already been released."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT evidence_json FROM agent_slurm_operations WHERE acknowledged=0 AND evidence_json IS NOT NULL"
                ).fetchall()
            for row in rows:
                pending = json.loads(str(row[0]))
                self._publish(
                    SlurmStageAssignment.from_dict(pending["assignment"]),
                    SlurmReadyStageSubmission.from_dict(pending["submission"]),
                    acknowledge,
                    release=pending["release"],
                    recovery_evidence=pending.get("recovery_evidence"),
                    provider_released=pending.get("provider_released", False),
                )

    def step(
        self,
        task: Mapping[str, PlainData],
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
    ) -> None:
        """Drive one bounded observation cycle, replaying before any new effect."""
        with self._lock:
            self._step(task, acknowledge)

    def _step(
        self,
        task: Mapping[str, PlainData],
        acknowledge: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
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
            released = conn.execute(
                "SELECT released FROM agent_slurm_operations WHERE operation_id=?",
                (request.operation_id,),
            ).fetchone()
        if released is not None and released[0]:
            return
        current = self.journal.find(request.operation_id)
        now = monotonic()
        urgent_cancel = (
            current is not None
            and current.job_id is not None
            and not current.cancel_requested
            and task.get("cancel_requested") is True
        )
        if (
            current is not None
            and current.state is not ReadyStageState.INTENT
            and now < self._next_poll.get(request.operation_id, 0)
            and not urgent_cancel
            and task.get("recovery_request") is None
            and task.get("release_requested") is not True
        ):
            return
        self._next_poll[request.operation_id] = now + profile.poll_interval_seconds
        script = self.root / "slurm-scripts" / f"{assignment.assignment_id}.sh"
        if current is None:
            atomic_write_bytes(script, request.script.encode("utf-8"))
            script.chmod(0o600)
        current = self.journal.prepare(request, profile, script)
        if current.state is ReadyStageState.INTENT:
            reply = self._publish(assignment, current, acknowledge)
            if reply.get("cancel_requested") is True:
                current = self.journal.suppress_before_submit(request.operation_id)
            else:
                current = self.journal.submit(
                    request,
                    profile,
                    script,
                    before_runner=lambda value: (
                        self._publish(assignment, value, acknowledge).get(
                            "cancel_requested"
                        )
                        is not True
                    ),
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
            else:
                current = self.journal.reconcile(request.operation_id, profile)
        reply = self._publish(assignment, current, acknowledge)
        if current.job_id is not None:
            if reply.get("cancel_requested") is True:
                current = self.journal.request_cancel(request.operation_id, profile)
            current = self.journal.observe(request.operation_id, profile)
            self._publish(assignment, current, acknowledge)
        recovery_request = task.get("recovery_request")
        if isinstance(recovery_request, Mapping):
            receipt = resolve_slurm_containment(profile, recovery_request)
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
            receipt = resolve_slurm_containment(profile, proof)
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
