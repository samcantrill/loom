"""Schema-versioned live SLURM submission manifest records."""

from __future__ import annotations

import getpass
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.fingerprints import validate_digest
from loom.pipeline.stores.atomic import atomic_write_json
from loom.serialization import (
    PlainData,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError
from loom.timestamps import parse_timestamp, utc_timestamp

from .commands import SlurmCommandResult, bound_scheduler_output
from .errors import SlurmManifestError, SlurmManifestUpdateError
from .manifest import (
    SlurmMode,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    validate_logical_job_key,
)
from .options import SlurmCommandArgv, SlurmOptions

SLURM_LIVE_SUBMISSION_SCHEMA_VERSION = 2

_LIVE_REQUIRED_FIELDS = frozenset(
    {
        "run_uri",
        "mode",
        "dry_run",
        "planning_id",
        "submission_id",
        "created_at",
        "updated_at",
        "plan_relative_path",
        "manifest_relative_path",
        "options",
        "jobs",
        "dependencies",
        "submission_status",
        "submitted_jobs",
        "failed_submissions",
        "status_snapshots",
        "cancellation_attempts",
    }
)
_LIVE_OPTIONAL_FIELDS = frozenset(
    {
        "generated_command_argv",
        "resources",
        "submitted_at",
        "completed_at",
        "submit_host",
        "submit_user",
        "queue_item_id",
        "scheduler_operations",
    }
)
_SCHEDULER_OPERATION_FIELDS = frozenset(
    {
        "operation_id",
        "operation_digest",
        "logical_key",
        "marker",
        "script_relative_path",
        "dependency_job_ids",
        "created_at",
        "updated_at",
        "state",
        "evidence",
    }
)
_SUBMITTED_JOB_FIELDS = frozenset(
    {
        "logical_key",
        "scheduler_job_id",
        "scheduler_cluster",
        "raw_job_id_output",
        "submitted_at",
        "dependency_job_ids",
        "command_record",
        "script_relative_path",
        "stdout_relative_path",
        "stderr_relative_path",
    }
)
_FAILED_SUBMISSION_FIELDS = frozenset(
    {
        "logical_key",
        "failed_at",
        "reason",
        "dependency_job_ids",
        "command_record",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "logical_key",
        "scheduler_job_id",
        "captured_at",
        "source",
        "state",
        "exit_code",
        "details",
    }
)
_CANCELLATION_FIELDS = frozenset(
    {
        "logical_key",
        "scheduler_job_id",
        "attempted_at",
        "outcome",
        "message",
        "command_record",
    }
)


class SlurmLiveSubmissionStatus(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class SlurmSchedulerOperationState(StrEnum):
    """Durable state of one exact scheduler-call boundary."""

    INTENT = "INTENT"
    SUBMITTING = "SUBMITTING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class SlurmSchedulerOperation:
    """One persisted call identity; submitted jobs remain the handle inventory."""

    operation_id: str
    operation_digest: str
    logical_key: str
    marker: str
    script_relative_path: str
    dependency_job_ids: Sequence[str]
    created_at: str
    updated_at: str
    state: SlurmSchedulerOperationState | str
    evidence: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operation_id", _safe_text(self.operation_id, path="operation_id")
        )
        try:
            object.__setattr__(
                self, "operation_digest", validate_digest(self.operation_digest)
            )
        except Exception as exc:
            raise SlurmManifestError(
                "operation_digest must be a canonical digest"
            ) from exc
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(self.logical_key, path="logical_key"),
        )
        object.__setattr__(self, "marker", _safe_text(self.marker, path="marker"))
        object.__setattr__(
            self,
            "script_relative_path",
            _relative_path(self.script_relative_path, path="script_relative_path"),
        )
        object.__setattr__(
            self,
            "dependency_job_ids",
            tuple(
                _scheduler_job_id(job_id, path=f"dependency_job_ids[{index}]")
                for index, job_id in enumerate(
                    _sequence(self.dependency_job_ids, path="dependency_job_ids")
                )
            ),
        )
        _timestamp(self.created_at, path="created_at")
        _timestamp(self.updated_at, path="updated_at")
        object.__setattr__(self, "state", SlurmSchedulerOperationState(self.state))
        if self.evidence is not None:
            _safe_text(self.evidence, path="evidence")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "operation_digest": self.operation_digest,
            "logical_key": self.logical_key,
            "marker": self.marker,
            "script_relative_path": self.script_relative_path,
            "dependency_job_ids": list(self.dependency_job_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": SlurmSchedulerOperationState(self.state).value,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmSchedulerOperation"
    ) -> "SlurmSchedulerOperation":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _SCHEDULER_OPERATION_FIELDS, path=path)
        _require_fields(
            mapping,
            set(_SCHEDULER_OPERATION_FIELDS - {"evidence"}),
            path=path,
        )
        return cls(
            operation_id=cast(str, mapping["operation_id"]),
            operation_digest=cast(str, mapping["operation_digest"]),
            logical_key=cast(str, mapping["logical_key"]),
            marker=cast(str, mapping["marker"]),
            script_relative_path=cast(str, mapping["script_relative_path"]),
            dependency_job_ids=cast(Sequence[str], mapping["dependency_job_ids"]),
            created_at=cast(str, mapping["created_at"]),
            updated_at=cast(str, mapping["updated_at"]),
            state=cast(str, mapping["state"]),
            evidence=cast(str | None, mapping.get("evidence")),
        )


@dataclass(frozen=True, slots=True)
class SlurmSubmittedJob:
    """One scheduler-accepted SLURM job."""

    logical_key: str
    scheduler_job_id: str
    raw_job_id_output: str
    submitted_at: str
    command_record: SlurmCommandResult | Mapping[str, object]
    dependency_job_ids: Sequence[str] = ()
    scheduler_cluster: str | None = None
    script_relative_path: str | None = None
    stdout_relative_path: str | None = None
    stderr_relative_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(
                self.logical_key, path="SlurmSubmittedJob.logical_key"
            ),
        )
        object.__setattr__(
            self,
            "scheduler_job_id",
            _scheduler_job_id(self.scheduler_job_id, path="scheduler_job_id"),
        )
        object.__setattr__(
            self,
            "raw_job_id_output",
            bound_scheduler_output(
                self.raw_job_id_output, field="SlurmSubmittedJob.raw_job_id_output"
            ),
        )
        _timestamp(self.submitted_at, path="SlurmSubmittedJob.submitted_at")
        object.__setattr__(
            self,
            "command_record",
            self.command_record
            if isinstance(self.command_record, SlurmCommandResult)
            else SlurmCommandResult.from_dict(self.command_record),
        )
        object.__setattr__(
            self,
            "dependency_job_ids",
            tuple(
                _scheduler_job_id(
                    job_id, path=f"SlurmSubmittedJob.dependency_job_ids[{index}]"
                )
                for index, job_id in enumerate(
                    _sequence(
                        self.dependency_job_ids,
                        path="SlurmSubmittedJob.dependency_job_ids",
                    )
                )
            ),
        )
        if self.scheduler_cluster is not None:
            _safe_text(
                self.scheduler_cluster, path="SlurmSubmittedJob.scheduler_cluster"
            )
        for field_name in (
            "script_relative_path",
            "stdout_relative_path",
            "stderr_relative_path",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_relative_path(
                    getattr(self, field_name),
                    path=f"SlurmSubmittedJob.{field_name}",
                ),
            )

    def to_dict(self) -> dict[str, PlainData]:
        command = cast(SlurmCommandResult, self.command_record)
        return {
            "logical_key": self.logical_key,
            "scheduler_job_id": self.scheduler_job_id,
            "scheduler_cluster": self.scheduler_cluster,
            "raw_job_id_output": self.raw_job_id_output,
            "submitted_at": self.submitted_at,
            "dependency_job_ids": list(self.dependency_job_ids),
            "command_record": command.to_dict(),
            "script_relative_path": self.script_relative_path,
            "stdout_relative_path": self.stdout_relative_path,
            "stderr_relative_path": self.stderr_relative_path,
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmSubmittedJob"
    ) -> "SlurmSubmittedJob":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _SUBMITTED_JOB_FIELDS, path=path)
        _require_fields(
            mapping,
            {
                "logical_key",
                "scheduler_job_id",
                "raw_job_id_output",
                "submitted_at",
                "dependency_job_ids",
                "command_record",
            },
            path=path,
        )
        return cls(
            logical_key=cast(str, mapping["logical_key"]),
            scheduler_job_id=cast(str, mapping["scheduler_job_id"]),
            scheduler_cluster=cast(str | None, mapping.get("scheduler_cluster")),
            raw_job_id_output=cast(str, mapping["raw_job_id_output"]),
            submitted_at=cast(str, mapping["submitted_at"]),
            dependency_job_ids=tuple(
                cast(
                    Sequence[str],
                    _sequence(
                        mapping["dependency_job_ids"],
                        path=f"{path}.dependency_job_ids",
                    ),
                )
            ),
            command_record=SlurmCommandResult.from_dict(mapping["command_record"]),
            script_relative_path=cast(str | None, mapping.get("script_relative_path")),
            stdout_relative_path=cast(str | None, mapping.get("stdout_relative_path")),
            stderr_relative_path=cast(str | None, mapping.get("stderr_relative_path")),
        )


@dataclass(frozen=True, slots=True)
class SlurmFailedSubmission:
    """One planned job that failed before scheduler acceptance."""

    logical_key: str
    failed_at: str
    reason: str
    dependency_job_ids: Sequence[str] = ()
    command_record: SlurmCommandResult | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(
                self.logical_key, path="SlurmFailedSubmission.logical_key"
            ),
        )
        _timestamp(self.failed_at, path="SlurmFailedSubmission.failed_at")
        object.__setattr__(
            self,
            "reason",
            bound_scheduler_output(self.reason, field="SlurmFailedSubmission.reason"),
        )
        object.__setattr__(
            self,
            "dependency_job_ids",
            tuple(
                _scheduler_job_id(
                    job_id, path=f"SlurmFailedSubmission.dependency_job_ids[{index}]"
                )
                for index, job_id in enumerate(
                    _sequence(
                        self.dependency_job_ids,
                        path="SlurmFailedSubmission.dependency_job_ids",
                    )
                )
            ),
        )
        if self.command_record is not None and not isinstance(
            self.command_record, SlurmCommandResult
        ):
            object.__setattr__(
                self,
                "command_record",
                SlurmCommandResult.from_dict(self.command_record),
            )

    def to_dict(self) -> dict[str, PlainData]:
        command = cast(SlurmCommandResult | None, self.command_record)
        return {
            "logical_key": self.logical_key,
            "failed_at": self.failed_at,
            "reason": self.reason,
            "dependency_job_ids": list(self.dependency_job_ids),
            "command_record": None if command is None else command.to_dict(),
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmFailedSubmission"
    ) -> "SlurmFailedSubmission":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _FAILED_SUBMISSION_FIELDS, path=path)
        _require_fields(mapping, {"logical_key", "failed_at", "reason"}, path=path)
        raw_command = mapping.get("command_record")
        return cls(
            logical_key=cast(str, mapping["logical_key"]),
            failed_at=cast(str, mapping["failed_at"]),
            reason=cast(str, mapping["reason"]),
            dependency_job_ids=tuple(
                cast(
                    Sequence[str],
                    _sequence(
                        mapping.get("dependency_job_ids", ()),
                        path=f"{path}.dependency_job_ids",
                    ),
                )
            ),
            command_record=None
            if raw_command is None
            else SlurmCommandResult.from_dict(raw_command),
        )


@dataclass(frozen=True, slots=True)
class SlurmSchedulerStatusSnapshot:
    """Persisted scheduler status fact for one submitted job."""

    logical_key: str
    scheduler_job_id: str
    captured_at: str
    source: str
    state: str
    exit_code: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(
                self.logical_key, path="SlurmSchedulerStatusSnapshot.logical_key"
            ),
        )
        object.__setattr__(
            self,
            "scheduler_job_id",
            _scheduler_job_id(
                self.scheduler_job_id,
                path="SlurmSchedulerStatusSnapshot.scheduler_job_id",
            ),
        )
        _timestamp(self.captured_at, path="SlurmSchedulerStatusSnapshot.captured_at")
        object.__setattr__(
            self,
            "source",
            _safe_text(self.source, path="SlurmSchedulerStatusSnapshot.source"),
        )
        object.__setattr__(
            self,
            "state",
            _safe_text(self.state, path="SlurmSchedulerStatusSnapshot.state"),
        )
        if self.exit_code is not None:
            _safe_text(
                self.exit_code,
                path="SlurmSchedulerStatusSnapshot.exit_code",
            )
        object.__setattr__(
            self,
            "details",
            MappingProxyType(
                _plain_mapping(
                    self.details, path="SlurmSchedulerStatusSnapshot.details"
                )
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "logical_key": self.logical_key,
            "scheduler_job_id": self.scheduler_job_id,
            "captured_at": self.captured_at,
            "source": self.source,
            "state": self.state,
            "exit_code": self.exit_code,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmSchedulerStatusSnapshot"
    ) -> "SlurmSchedulerStatusSnapshot":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _SNAPSHOT_FIELDS, path=path)
        _require_fields(
            mapping,
            {"logical_key", "scheduler_job_id", "captured_at", "source", "state"},
            path=path,
        )
        return cls(
            logical_key=cast(str, mapping["logical_key"]),
            scheduler_job_id=cast(str, mapping["scheduler_job_id"]),
            captured_at=cast(str, mapping["captured_at"]),
            source=cast(str, mapping["source"]),
            state=cast(str, mapping["state"]),
            exit_code=cast(str | None, mapping.get("exit_code")),
            details=_plain_mapping(mapping.get("details", {}), path=f"{path}.details"),
        )


@dataclass(frozen=True, slots=True)
class SlurmCancellationAttempt:
    """Persisted cancellation attempt for one scheduler job."""

    logical_key: str
    scheduler_job_id: str
    attempted_at: str
    outcome: str
    command_record: SlurmCommandResult | Mapping[str, object]
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(
                self.logical_key, path="SlurmCancellationAttempt.logical_key"
            ),
        )
        object.__setattr__(
            self,
            "scheduler_job_id",
            _scheduler_job_id(
                self.scheduler_job_id, path="SlurmCancellationAttempt.scheduler_job_id"
            ),
        )
        _timestamp(self.attempted_at, path="SlurmCancellationAttempt.attempted_at")
        object.__setattr__(
            self,
            "outcome",
            _safe_text(self.outcome, path="SlurmCancellationAttempt.outcome"),
        )
        if self.message is not None:
            object.__setattr__(
                self,
                "message",
                bound_scheduler_output(
                    self.message, field="SlurmCancellationAttempt.message"
                ),
            )
        object.__setattr__(
            self,
            "command_record",
            self.command_record
            if isinstance(self.command_record, SlurmCommandResult)
            else SlurmCommandResult.from_dict(self.command_record),
        )

    def to_dict(self) -> dict[str, PlainData]:
        command = cast(SlurmCommandResult, self.command_record)
        return {
            "logical_key": self.logical_key,
            "scheduler_job_id": self.scheduler_job_id,
            "attempted_at": self.attempted_at,
            "outcome": self.outcome,
            "message": self.message,
            "command_record": command.to_dict(),
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmCancellationAttempt"
    ) -> "SlurmCancellationAttempt":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _CANCELLATION_FIELDS, path=path)
        _require_fields(
            mapping,
            {
                "logical_key",
                "scheduler_job_id",
                "attempted_at",
                "outcome",
                "command_record",
            },
            path=path,
        )
        return cls(
            logical_key=cast(str, mapping["logical_key"]),
            scheduler_job_id=cast(str, mapping["scheduler_job_id"]),
            attempted_at=cast(str, mapping["attempted_at"]),
            outcome=cast(str, mapping["outcome"]),
            message=cast(str | None, mapping.get("message")),
            command_record=SlurmCommandResult.from_dict(mapping["command_record"]),
        )


@dataclass(frozen=True, slots=True)
class SlurmLiveSubmissionManifest:
    """Canonical live SLURM manifest stored at the v6 ``manifest.json`` path."""

    run_uri: str
    mode: SlurmMode | str
    planning_id: str
    submission_id: str
    created_at: str
    updated_at: str
    plan_relative_path: str
    manifest_relative_path: str
    options: SlurmOptions | Mapping[str, object]
    jobs: Sequence[SlurmPlannedJob | Mapping[str, object]]
    dependencies: Sequence[SlurmPlannedDependency | Mapping[str, object]] = ()
    submission_status: SlurmLiveSubmissionStatus | str = (
        SlurmLiveSubmissionStatus.PREPARED
    )
    submitted_jobs: Sequence[SlurmSubmittedJob | Mapping[str, object]] = ()
    failed_submissions: Sequence[SlurmFailedSubmission | Mapping[str, object]] = ()
    status_snapshots: Sequence[SlurmSchedulerStatusSnapshot | Mapping[str, object]] = ()
    cancellation_attempts: Sequence[
        SlurmCancellationAttempt | Mapping[str, object]
    ] = ()
    generated_command_argv: Sequence[SlurmCommandArgv | Mapping[str, object]] = ()
    resources: Mapping[str, PlainData] = field(default_factory=dict)
    submitted_at: str | None = None
    completed_at: str | None = None
    submit_host: str | None = None
    submit_user: str | None = None
    queue_item_id: str | None = None
    scheduler_operations: Sequence[SlurmSchedulerOperation | Mapping[str, object]] = ()
    dry_run: bool = False
    schema_version: int = SLURM_LIVE_SUBMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SLURM_LIVE_SUBMISSION_SCHEMA_VERSION:
            raise SlurmManifestError(
                f"live SLURM manifest schema_version must be {SLURM_LIVE_SUBMISSION_SCHEMA_VERSION}"
            )
        if self.dry_run is not False:
            raise SlurmManifestError(
                "SlurmLiveSubmissionManifest.dry_run must be false"
            )
        object.__setattr__(self, "run_uri", _safe_text(self.run_uri, path="run_uri"))
        object.__setattr__(self, "mode", _coerce_mode(self.mode, path="mode"))
        object.__setattr__(
            self,
            "planning_id",
            _safe_text(self.planning_id, path="planning_id"),
        )
        object.__setattr__(
            self,
            "submission_id",
            _safe_text(self.submission_id, path="submission_id"),
        )
        _timestamp(self.created_at, path="created_at")
        _timestamp(self.updated_at, path="updated_at")
        object.__setattr__(
            self,
            "plan_relative_path",
            _relative_path(self.plan_relative_path, path="plan_relative_path"),
        )
        object.__setattr__(
            self,
            "manifest_relative_path",
            _relative_path(self.manifest_relative_path, path="manifest_relative_path"),
        )
        object.__setattr__(
            self,
            "options",
            self.options
            if isinstance(self.options, SlurmOptions)
            else SlurmOptions.from_dict(self.options),
        )
        object.__setattr__(
            self,
            "jobs",
            tuple(
                item
                if isinstance(item, SlurmPlannedJob)
                else SlurmPlannedJob.from_dict(item, path=f"jobs[{index}]")
                for index, item in enumerate(self.jobs)
            ),
        )
        object.__setattr__(
            self,
            "dependencies",
            tuple(
                item
                if isinstance(item, SlurmPlannedDependency)
                else SlurmPlannedDependency.from_dict(
                    item, path=f"dependencies[{index}]"
                )
                for index, item in enumerate(self.dependencies)
            ),
        )
        object.__setattr__(
            self,
            "submission_status",
            _coerce_status(self.submission_status, path="submission_status"),
        )
        object.__setattr__(
            self,
            "submitted_jobs",
            tuple(
                item
                if isinstance(item, SlurmSubmittedJob)
                else SlurmSubmittedJob.from_dict(item, path=f"submitted_jobs[{index}]")
                for index, item in enumerate(self.submitted_jobs)
            ),
        )
        object.__setattr__(
            self,
            "failed_submissions",
            tuple(
                item
                if isinstance(item, SlurmFailedSubmission)
                else SlurmFailedSubmission.from_dict(
                    item, path=f"failed_submissions[{index}]"
                )
                for index, item in enumerate(self.failed_submissions)
            ),
        )
        object.__setattr__(
            self,
            "status_snapshots",
            tuple(
                item
                if isinstance(item, SlurmSchedulerStatusSnapshot)
                else SlurmSchedulerStatusSnapshot.from_dict(
                    item, path=f"status_snapshots[{index}]"
                )
                for index, item in enumerate(self.status_snapshots)
            ),
        )
        object.__setattr__(
            self,
            "cancellation_attempts",
            tuple(
                item
                if isinstance(item, SlurmCancellationAttempt)
                else SlurmCancellationAttempt.from_dict(
                    item, path=f"cancellation_attempts[{index}]"
                )
                for index, item in enumerate(self.cancellation_attempts)
            ),
        )
        object.__setattr__(
            self,
            "generated_command_argv",
            tuple(
                item
                if isinstance(item, SlurmCommandArgv)
                else SlurmCommandArgv.from_dict(
                    item, path=f"generated_command_argv[{index}]"
                )
                for index, item in enumerate(self.generated_command_argv)
            ),
        )
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(_plain_mapping(self.resources, path="resources")),
        )
        _optional_timestamp(self.submitted_at, path="submitted_at")
        _optional_timestamp(self.completed_at, path="completed_at")
        if self.submit_host is not None:
            _safe_text(self.submit_host, path="submit_host")
        if self.submit_user is not None:
            _safe_text(self.submit_user, path="submit_user")
        if self.queue_item_id is not None:
            _safe_text(self.queue_item_id, path="queue_item_id")
        object.__setattr__(
            self,
            "scheduler_operations",
            tuple(
                item
                if isinstance(item, SlurmSchedulerOperation)
                else SlurmSchedulerOperation.from_dict(
                    item, path=f"scheduler_operations[{index}]"
                )
                for index, item in enumerate(self.scheduler_operations)
            ),
        )
        self._validate_live_consistency()

    @property
    def summary_counts(self) -> dict[str, int]:
        submitted = len(self.submitted_jobs)
        failed = len(self.failed_submissions)
        cancelled = sum(
            1
            for attempt in cast(
                tuple[SlurmCancellationAttempt, ...], self.cancellation_attempts
            )
            if attempt.outcome == "cancelled"
        )
        counts = {
            "prepared": 1
            if self.submission_status == SlurmLiveSubmissionStatus.PREPARED
            else 0,
            "submitting": 1
            if self.submission_status == SlurmLiveSubmissionStatus.SUBMITTING
            else 0,
            "submitted": submitted,
            "failed": failed,
            "cancelled": cancelled,
        }
        if self.submission_status in {
            SlurmLiveSubmissionStatus.SUBMITTING,
            SlurmLiveSubmissionStatus.SUBMITTED,
            SlurmLiveSubmissionStatus.PARTIAL,
            SlurmLiveSubmissionStatus.CANCELLING,
            SlurmLiveSubmissionStatus.UNKNOWN,
        }:
            counts["active"] = max(1, submitted)
        return counts

    def to_dict(self) -> dict[str, PlainData]:
        mode = cast(SlurmMode, self.mode)
        status = cast(SlurmLiveSubmissionStatus, self.submission_status)
        options = cast(SlurmOptions, self.options)
        jobs = cast(tuple[SlurmPlannedJob, ...], self.jobs)
        dependencies = cast(tuple[SlurmPlannedDependency, ...], self.dependencies)
        submitted_jobs = cast(tuple[SlurmSubmittedJob, ...], self.submitted_jobs)
        failed = cast(tuple[SlurmFailedSubmission, ...], self.failed_submissions)
        snapshots = cast(
            tuple[SlurmSchedulerStatusSnapshot, ...], self.status_snapshots
        )
        cancellations = cast(
            tuple[SlurmCancellationAttempt, ...], self.cancellation_attempts
        )
        generated = cast(tuple[SlurmCommandArgv, ...], self.generated_command_argv)
        result: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "mode": mode.value,
            "dry_run": False,
            "planning_id": self.planning_id,
            "submission_id": self.submission_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_relative_path": self.plan_relative_path,
            "manifest_relative_path": self.manifest_relative_path,
            "options": options.to_dict(),
            "jobs": [job.to_dict() for job in jobs],
            "dependencies": [dependency.to_dict() for dependency in dependencies],
            "generated_command_argv": [command.to_dict() for command in generated],
            "resources": thaw_plain_data(self.resources, path="resources"),
            "submission_status": status.value,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "submit_host": self.submit_host,
            "submit_user": self.submit_user,
            "submitted_jobs": [job.to_dict() for job in submitted_jobs],
            "failed_submissions": [item.to_dict() for item in failed],
            "status_snapshots": [snapshot.to_dict() for snapshot in snapshots],
            "cancellation_attempts": [attempt.to_dict() for attempt in cancellations],
        }
        operations = cast(
            tuple[SlurmSchedulerOperation, ...], self.scheduler_operations
        )
        if self.queue_item_id is not None:
            result["queue_item_id"] = self.queue_item_id
        if operations:
            result["scheduler_operations"] = [
                operation.to_dict() for operation in operations
            ]
        return result

    @classmethod
    def from_dict(cls, data: object) -> "SlurmLiveSubmissionManifest":
        try:
            mapping = load_versioned_document(
                data,
                current_version=SLURM_LIVE_SUBMISSION_SCHEMA_VERSION,
                required=_LIVE_REQUIRED_FIELDS,
                optional=_LIVE_OPTIONAL_FIELDS,
                path="SlurmLiveSubmissionManifest",
            )
        except SchemaVersionError as exc:
            raise SlurmManifestError(
                f"SlurmLiveSubmissionManifest.from_dict: {exc}"
            ) from exc
        return cls(
            schema_version=SLURM_LIVE_SUBMISSION_SCHEMA_VERSION,
            run_uri=cast(str, mapping["run_uri"]),
            mode=cast(str, mapping["mode"]),
            dry_run=cast(bool, mapping["dry_run"]),
            planning_id=cast(str, mapping["planning_id"]),
            submission_id=cast(str, mapping["submission_id"]),
            created_at=cast(str, mapping["created_at"]),
            updated_at=cast(str, mapping["updated_at"]),
            plan_relative_path=cast(str, mapping["plan_relative_path"]),
            manifest_relative_path=cast(str, mapping["manifest_relative_path"]),
            options=SlurmOptions.from_dict(mapping["options"]),
            jobs=tuple(
                SlurmPlannedJob.from_dict(item, path=f"jobs[{index}]")
                for index, item in enumerate(_sequence(mapping["jobs"], path="jobs"))
            ),
            dependencies=tuple(
                SlurmPlannedDependency.from_dict(item, path=f"dependencies[{index}]")
                for index, item in enumerate(
                    _sequence(mapping["dependencies"], path="dependencies")
                )
            ),
            generated_command_argv=tuple(
                SlurmCommandArgv.from_dict(
                    item, path=f"generated_command_argv[{index}]"
                )
                for index, item in enumerate(
                    _sequence(
                        mapping.get("generated_command_argv", ()),
                        path="generated_command_argv",
                    )
                )
            ),
            resources=_plain_mapping(mapping.get("resources", {}), path="resources"),
            submission_status=cast(str, mapping["submission_status"]),
            submitted_at=cast(str | None, mapping.get("submitted_at")),
            completed_at=cast(str | None, mapping.get("completed_at")),
            submit_host=cast(str | None, mapping.get("submit_host")),
            submit_user=cast(str | None, mapping.get("submit_user")),
            queue_item_id=cast(str | None, mapping.get("queue_item_id")),
            scheduler_operations=tuple(
                SlurmSchedulerOperation.from_dict(
                    item, path=f"scheduler_operations[{index}]"
                )
                for index, item in enumerate(
                    _sequence(
                        mapping.get("scheduler_operations", ()),
                        path="scheduler_operations",
                    )
                )
            ),
            submitted_jobs=tuple(
                SlurmSubmittedJob.from_dict(item, path=f"submitted_jobs[{index}]")
                for index, item in enumerate(
                    _sequence(mapping["submitted_jobs"], path="submitted_jobs")
                )
            ),
            failed_submissions=tuple(
                SlurmFailedSubmission.from_dict(
                    item, path=f"failed_submissions[{index}]"
                )
                for index, item in enumerate(
                    _sequence(mapping["failed_submissions"], path="failed_submissions")
                )
            ),
            status_snapshots=tuple(
                SlurmSchedulerStatusSnapshot.from_dict(
                    item, path=f"status_snapshots[{index}]"
                )
                for index, item in enumerate(
                    _sequence(mapping["status_snapshots"], path="status_snapshots")
                )
            ),
            cancellation_attempts=tuple(
                SlurmCancellationAttempt.from_dict(
                    item, path=f"cancellation_attempts[{index}]"
                )
                for index, item in enumerate(
                    _sequence(
                        mapping["cancellation_attempts"], path="cancellation_attempts"
                    )
                )
            ),
        )

    def _validate_live_consistency(self) -> None:
        jobs = cast(tuple[SlurmPlannedJob, ...], self.jobs)
        planned_by_key = {job.logical_key: job for job in jobs}
        submitted = cast(tuple[SlurmSubmittedJob, ...], self.submitted_jobs)
        submitted_by_key: dict[str, SlurmSubmittedJob] = {}
        scheduler_to_key: dict[str, str] = {}
        for job in submitted:
            if job.logical_key not in planned_by_key:
                raise SlurmManifestError(
                    f"submitted job {job.logical_key!r} has no matching planned job"
                )
            if job.logical_key in submitted_by_key:
                raise SlurmManifestError(
                    f"submitted job {job.logical_key!r} is duplicated"
                )
            if job.scheduler_job_id in scheduler_to_key:
                raise SlurmManifestError(
                    f"scheduler job ID {job.scheduler_job_id!r} is duplicated"
                )
            submitted_by_key[job.logical_key] = job
            scheduler_to_key[job.scheduler_job_id] = job.logical_key
        for job in submitted:
            planned = planned_by_key[job.logical_key]
            allowed_dependency_ids = {
                submitted_by_key[key].scheduler_job_id
                for key in planned.dependency_job_keys
                if key in submitted_by_key
            }
            missing_keys = [
                key
                for key in planned.dependency_job_keys
                if key not in submitted_by_key
            ]
            if job.dependency_job_ids and missing_keys:
                raise SlurmManifestError(
                    f"submitted job {job.logical_key!r} has scheduler dependencies before upstream jobs were submitted"
                )
            unexpected = set(job.dependency_job_ids) - allowed_dependency_ids
            if unexpected:
                raise SlurmManifestError(
                    f"submitted job {job.logical_key!r} has dependency job IDs without matching upstream submitted jobs: {sorted(unexpected)}"
                )
        for failed in cast(tuple[SlurmFailedSubmission, ...], self.failed_submissions):
            if failed.logical_key not in planned_by_key:
                raise SlurmManifestError(
                    f"failed submission {failed.logical_key!r} has no matching planned job"
                )
        operations = cast(
            tuple[SlurmSchedulerOperation, ...], self.scheduler_operations
        )
        operation_ids = [operation.operation_id for operation in operations]
        operation_keys = [operation.logical_key for operation in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise SlurmManifestError("scheduler operation IDs must be unique")
        if len(operation_keys) != len(set(operation_keys)):
            raise SlurmManifestError(
                "each planned job may have one scheduler operation"
            )
        if any(operation.logical_key not in planned_by_key for operation in operations):
            raise SlurmManifestError("scheduler operation has no matching planned job")
        if self.queue_item_id is not None:
            operations_by_key = {
                operation.logical_key: operation for operation in operations
            }
            for job in submitted:
                operation = operations_by_key.get(job.logical_key)
                if (
                    operation is None
                    or operation.state is not SlurmSchedulerOperationState.ACCEPTED
                ):
                    raise SlurmManifestError(
                        f"queued submitted job {job.logical_key!r} requires one accepted scheduler operation"
                    )
                if (
                    operation.script_relative_path != job.script_relative_path
                    or operation.dependency_job_ids != job.dependency_job_ids
                ):
                    raise SlurmManifestError(
                        f"queued submitted job {job.logical_key!r} disagrees with its scheduler operation"
                    )
            if any(
                operation.state is SlurmSchedulerOperationState.ACCEPTED
                and operation.logical_key not in submitted_by_key
                for operation in operations
            ):
                raise SlurmManifestError(
                    "accepted queued scheduler operation has no submitted job"
                )


def live_manifest_from_planned_submission(
    submission: SlurmPlannedSubmission,
    *,
    status: SlurmLiveSubmissionStatus = SlurmLiveSubmissionStatus.PREPARED,
    updated_at: str | None = None,
    submit_host: str | None = None,
    submit_user: str | None = None,
    queue_item_id: str | None = None,
) -> SlurmLiveSubmissionManifest:
    """Create a live manifest draft from a v6 planned submission."""

    now = updated_at or utc_timestamp()
    return SlurmLiveSubmissionManifest(
        run_uri=submission.run_uri,
        mode=submission.mode,
        planning_id=submission.planning_id,
        submission_id=submission.planning_id,
        created_at=submission.created_at,
        updated_at=now,
        plan_relative_path=submission.plan_relative_path,
        manifest_relative_path=cast(str, submission.manifest_relative_path),
        options=cast(SlurmOptions, submission.options),
        jobs=cast(tuple[SlurmPlannedJob, ...], submission.jobs),
        dependencies=cast(tuple[SlurmPlannedDependency, ...], submission.dependencies),
        generated_command_argv=cast(
            tuple[SlurmCommandArgv, ...], submission.generated_command_argv
        ),
        resources=cast(Mapping[str, PlainData], submission.resources),
        submission_status=status,
        submitted_at=now if status != SlurmLiveSubmissionStatus.PREPARED else None,
        submit_host=submit_host or socket.gethostname(),
        submit_user=submit_user or getpass.getuser(),
        queue_item_id=queue_item_id,
    )


def write_slurm_live_manifest(
    path: str | Path, manifest: SlurmLiveSubmissionManifest
) -> None:
    """Write a live SLURM manifest atomically."""

    if not isinstance(manifest, SlurmLiveSubmissionManifest):
        raise SlurmManifestUpdateError("manifest must be SlurmLiveSubmissionManifest")
    try:
        atomic_write_json(Path(path), manifest.to_dict())
    except OSError as exc:
        raise SlurmManifestUpdateError(
            f"failed to write SLURM live manifest: {path}"
        ) from exc


def read_slurm_live_manifest(data: object) -> SlurmLiveSubmissionManifest:
    """Parse a live SLURM manifest from decoded JSON/plain data."""

    return SlurmLiveSubmissionManifest.from_dict(data)


def _coerce_mode(value: object, *, path: str) -> SlurmMode:
    if isinstance(value, SlurmMode):
        return value
    if isinstance(value, str):
        try:
            return SlurmMode(value)
        except ValueError as exc:
            raise SlurmManifestError(f"{path} must be a valid SLURM mode") from exc
    raise SlurmManifestError(f"{path} must be a string")


def _coerce_status(value: object, *, path: str) -> SlurmLiveSubmissionStatus:
    if isinstance(value, SlurmLiveSubmissionStatus):
        return value
    if isinstance(value, str):
        try:
            return SlurmLiveSubmissionStatus(value)
        except ValueError as exc:
            raise SlurmManifestError(
                f"{path} must be a valid live submission status"
            ) from exc
    raise SlurmManifestError(f"{path} must be a string")


def _scheduler_job_id(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.isdecimal():
        raise SlurmManifestError(f"{path} must be decimal scheduler job ID text")
    return value


def _safe_text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmManifestError(f"{path} must be a non-empty string")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise SlurmManifestError(f"{path} must not contain whitespace or control chars")
    return value


def _timestamp(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise SlurmManifestError(f"{path} must be a timestamp string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise SlurmManifestError(f"{path} must be a valid timestamp: {exc}") from exc
    return value


def _optional_timestamp(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, path=path)


def _optional_relative_path(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _relative_path(value, path=path)


def _relative_path(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmManifestError(f"{path} must be a non-empty relative path")
    if value.startswith("/") or "\\" in value:
        raise SlurmManifestError(f"{path} must be relative and use '/' separators")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise SlurmManifestError(f"{path} must not contain whitespace or control chars")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SlurmManifestError(f"{path} must not contain empty, '.', or '..' parts")
    return value


def _plain_mapping(value: object, *, path: str) -> dict[str, PlainData]:
    try:
        normalized = thaw_plain_data(value, path=path)
    except PlainDataError as exc:
        raise SlurmManifestError(
            f"{path} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise SlurmManifestError(f"{path} must be a mapping")
    frozen = freeze_plain_data(normalized, path=path)
    if not isinstance(frozen, Mapping):
        raise SlurmManifestError(f"{path} must be a mapping")
    return dict(cast(Mapping[str, PlainData], frozen))


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SlurmManifestError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SlurmManifestError(f"{path} must use string keys")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, path: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SlurmManifestError(f"{path} must be a sequence")
    return cast(Sequence[object], value)


def _reject_unknown(
    mapping: Mapping[str, object], allowed: frozenset[str], *, path: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SlurmManifestError(f"{path} contains unknown field(s): {fields}")


def _require_fields(
    mapping: Mapping[str, object], fields: set[str], *, path: str
) -> None:
    missing = fields - set(mapping)
    if missing:
        names = ", ".join(sorted(missing))
        raise SlurmManifestError(f"{path} missing required field(s): {names}")


__all__ = [
    "SLURM_LIVE_SUBMISSION_SCHEMA_VERSION",
    "SlurmCancellationAttempt",
    "SlurmFailedSubmission",
    "SlurmLiveSubmissionManifest",
    "SlurmLiveSubmissionStatus",
    "SlurmSchedulerOperation",
    "SlurmSchedulerOperationState",
    "SlurmSchedulerStatusSnapshot",
    "SlurmSubmittedJob",
    "live_manifest_from_planned_submission",
    "read_slurm_live_manifest",
    "write_slurm_live_manifest",
]
