"""Explicit ready-stage SLURM submission with conservative recovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3

from loom.pipeline.runtime.placement import ExecutionRouteKind, ResolvedStagePlacement
from loom.serialization import stable_json_dumps

from .commands import SlurmCommandRunner, parse_sbatch_parsable_output
from .errors import SlurmPlanningError, SlurmResourceMappingError
from .resources import SlurmSbatchDirective, map_slurm_resources


class ReadyStageState(StrEnum):
    INTENT = "intent"
    SUBMITTING = "submitting"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SlurmReadyStageProfile:
    profile_id: str
    fingerprint: str
    partition: str
    max_outstanding: int
    bootstrap_argv: tuple[str, ...]
    runner: SlurmCommandRunner
    available: bool = True

    def __post_init__(self) -> None:
        for value in (self.profile_id, self.fingerprint, self.partition):
            _safe(value)
        if self.max_outstanding < 1 or not self.bootstrap_argv:
            raise SlurmPlanningError("ready-stage SLURM profile is invalid")

    def preflight(self) -> str | None:
        if not self.available:
            return "slurm_profile_unavailable"
        try:
            for command in ("sbatch", "squeue", "sacct", "scancel"):
                self.runner.require(command)
            self.runner.discover_operation("loom-op-v1:preflight")
        except Exception:
            return "slurm_profile_operation_discovery_unavailable"
        return None


@dataclass(frozen=True, slots=True)
class SlurmReadyStageRequest:
    operation_id: str
    stage_work_id: str
    run_uri: str
    attempt_id: str
    profile_id: str
    placement_fingerprint: str
    directives: tuple[SlurmSbatchDirective, ...]
    script: str
    digest: str


def map_ready_stage(
    *,
    placement: ResolvedStagePlacement,
    profile: SlurmReadyStageProfile,
    operation_id: str,
    stage_work_id: str,
    run_uri: str,
    attempt_id: str,
) -> SlurmReadyStageRequest:
    if placement.route.kind is not ExecutionRouteKind.SLURM:
        raise SlurmPlanningError("stage is not explicitly routed to SLURM")
    if (
        placement.route.profile_name != profile.profile_id
        or placement.route.profile_fingerprint != profile.fingerprint
    ):
        raise SlurmPlanningError("slurm_profile_changed")
    if profile.preflight() is not None:
        raise SlurmPlanningError("slurm_profile_operation_discovery_unavailable")
    if placement.hard_constraints or placement.target is not None:
        raise SlurmResourceMappingError("slurm_hard_requirement_unmappable")
    resources = map_slurm_resources(placement.resource_request)
    marker = _marker(operation_id)
    directives = (
        SlurmSbatchDirective("partition", profile.partition, "profile"),
        SlurmSbatchDirective("comment", marker, "operation"),
        *resources,
    )
    argv = " ".join(_quote(item) for item in profile.bootstrap_argv)
    script = f"#!/usr/bin/env bash\n#SBATCH --comment={marker}\nset -euo pipefail\nexec {argv} --operation-id {_quote(operation_id)} --request-digest {_quote(placement.fingerprint)}\n"
    value = {
        "operation_id": operation_id,
        "stage_work_id": stage_work_id,
        "run_uri": run_uri,
        "attempt_id": attempt_id,
        "profile_id": profile.profile_id,
        "placement_fingerprint": placement.fingerprint,
        "directives": [item.to_dict() for item in directives],
        "script": script,
    }
    return SlurmReadyStageRequest(
        operation_id,
        stage_work_id,
        run_uri,
        attempt_id,
        profile.profile_id,
        placement.fingerprint,
        directives,
        script,
        _digest(stable_json_dumps(value)),
    )


@dataclass(frozen=True, slots=True)
class SlurmReadyStageSubmission:
    request: SlurmReadyStageRequest
    state: ReadyStageState
    job_id: str | None = None
    evidence: str | None = None
    start_consumed: bool = False


class SQLiteReadyStageSubmissions:
    """The at-most-one ``sbatch`` owner; lifecycle truth stays outside this store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def submit(
        self,
        request: SlurmReadyStageRequest,
        profile: SlurmReadyStageProfile,
        script_path: str | Path,
    ) -> SlurmReadyStageSubmission:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ready_stage_submissions (operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, value_json TEXT NOT NULL)"
            )
            row = conn.execute(
                "SELECT value_json FROM ready_stage_submissions WHERE operation_id=?",
                (request.operation_id,),
            ).fetchone()
            if row:
                return _load(row[0])
            value = SlurmReadyStageSubmission(request, ReadyStageState.SUBMITTING)
            conn.execute(
                "INSERT INTO ready_stage_submissions VALUES (?, ?, ?)",
                (request.operation_id, value.state.value, _dump(value)),
            )
            conn.commit()
        try:
            result = profile.runner.sbatch(
                script_path, comment=_marker(request.operation_id)
            )
            if not result.ok:
                return self._set(
                    request.operation_id,
                    ReadyStageState.REJECTED,
                    evidence="slurm_submit_rejected",
                )
            parsed = parse_sbatch_parsable_output(result.stdout)
            return self._set(
                request.operation_id, ReadyStageState.ACCEPTED, job_id=parsed.job_id
            )
        except Exception:
            return self._set(
                request.operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_submit_unknown",
            )

    def reconcile(
        self, operation_id: str, profile: SlurmReadyStageProfile
    ) -> SlurmReadyStageSubmission:
        current = self.read(operation_id)
        if current.state is not ReadyStageState.SUBMITTING:
            return current
        try:
            result = profile.runner.discover_operation(_marker(operation_id))
            matches = [
                line.split("|", 1)[0]
                for line in result.stdout.splitlines()
                if line.endswith("|" + _marker(operation_id))
                and line.split("|", 1)[0].isdigit()
            ]
        except Exception:
            return self._set(
                operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_discovery_unknown",
            )
        if len(matches) == 1:
            return self._set(operation_id, ReadyStageState.ACCEPTED, job_id=matches[0])
        if len(matches) > 1:
            return self._set(
                operation_id,
                ReadyStageState.CONFLICT,
                evidence="slurm_operation_multiple_matches",
            )
        return self._set(
            operation_id, ReadyStageState.UNKNOWN, evidence="slurm_operation_not_found"
        )

    def read(self, operation_id: str) -> SlurmReadyStageSubmission:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT value_json FROM ready_stage_submissions WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        if not row:
            raise SlurmPlanningError("SLURM submission is not durable")
        return _load(row[0])

    def consume_start(self, operation_id: str) -> bool:
        current = self.read(operation_id)
        if current.start_consumed:
            return False
        self._write(replace(current, start_consumed=True))
        return True

    def _set(
        self,
        operation_id: str,
        state: ReadyStageState,
        *,
        job_id: str | None = None,
        evidence: str | None = None,
    ) -> SlurmReadyStageSubmission:
        current = self.read(operation_id)
        value = replace(current, state=state, job_id=job_id, evidence=evidence)
        self._write(value)
        return value

    def _write(self, value: SlurmReadyStageSubmission) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE ready_stage_submissions SET state=?, value_json=? WHERE operation_id=?",
                (value.state.value, _dump(value), value.request.operation_id),
            )


def _dump(value: SlurmReadyStageSubmission) -> str:
    request = value.request
    return json.dumps(
        {
            "request": {
                "operation_id": request.operation_id,
                "stage_work_id": request.stage_work_id,
                "run_uri": request.run_uri,
                "attempt_id": request.attempt_id,
                "profile_id": request.profile_id,
                "placement_fingerprint": request.placement_fingerprint,
                "directives": [item.to_dict() for item in request.directives],
                "script": request.script,
                "digest": request.digest,
            },
            "state": value.state.value,
            "job_id": value.job_id,
            "evidence": value.evidence,
            "start_consumed": value.start_consumed,
        },
        sort_keys=True,
    )


def _load(raw: str) -> SlurmReadyStageSubmission:
    value = json.loads(raw)
    request = value["request"]
    directives = tuple(
        SlurmSbatchDirective.from_dict(item) for item in request["directives"]
    )
    return SlurmReadyStageSubmission(
        SlurmReadyStageRequest(
            request["operation_id"],
            request["stage_work_id"],
            request["run_uri"],
            request["attempt_id"],
            request["profile_id"],
            request["placement_fingerprint"],
            directives,
            request["script"],
            request["digest"],
        ),
        ReadyStageState(value["state"]),
        value.get("job_id"),
        value.get("evidence"),
        value.get("start_consumed", False),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _safe(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(c.isspace() or ord(c) < 33 for c in value)
    ):
        raise SlurmPlanningError("SLURM identity is invalid")


def _marker(operation_id: str) -> str:
    _safe(operation_id)
    return "loom-op-v1:" + operation_id


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
