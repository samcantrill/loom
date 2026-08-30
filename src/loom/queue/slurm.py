"""Delegated SLURM dispatch adapter for queue controllers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import cast

from loom.fingerprints import hash_mapping, validate_digest
from loom.pipeline.executors.slurm.commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
    command_result_from_exception,
    parse_sbatch_parsable_output,
)
from loom.pipeline.executors.slurm.live import (
    SlurmLiveSubmissionManifest,
    SlurmSchedulerOperation,
    SlurmSchedulerOperationState,
    SlurmSchedulerStatusSnapshot,
    SlurmSubmittedJob,
    read_slurm_live_manifest,
    write_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.manifest import (
    SlurmMode,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
)
from loom.pipeline.executors.slurm.paths import resolve_slurm_generated_artifact_path
from loom.pipeline.executors.slurm.artifacts import SlurmDryRunPlanningResult
from loom.pipeline.executors.slurm.submission import (
    SlurmLiveSubmissionResult,
    submit_afterok_slurm,
    submit_single_job_slurm,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores.run_store import LegacyRunStore, LocalRunStorePaths
from loom.pipeline.executors.slurm.errors import SlurmJobIdParseError
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .controller import (
    QueueDispatchCancellation,
    QueueDispatchDisposition,
    QueueDispatchInspection,
    QueueDispatchNonStartCause,
    QueueDispatchResult,
    QueuePreStartCleanupStatus,
)
from .errors import QueueServiceError
from .models import QueueItem, QueueItemStatus

SLURM_QUEUE_ADAPTER_NAME = "slurm"
SLURM_PREPARED_RUN_LAUNCH_TAG = "loom.slurm-prepared-run.v1"

_SLURM_SUCCESS_STATES = frozenset({"COMPLETED"})
_SLURM_CANCELLED_STATES = frozenset({"CANCELLED"})
_SLURM_FAILURE_STATES = frozenset(
    {
        "BOOT_FAIL",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
        "TIMEOUT",
    }
)
_SLURM_ACTIVE_STATES = frozenset(
    {
        "COMPLETING",
        "CONFIGURING",
        "PENDING",
        "RESIZING",
        "RUNNING",
        "STAGE_OUT",
        "STOPPED",
        "SUBMITTED",
        "SUSPENDED",
    }
)


@dataclass(frozen=True, slots=True)
class SlurmDelegatedLaunch:
    """Trusted delegated SLURM launch data from a queue launch contract."""

    script_path: str
    dependency_job_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "script_path": self.script_path,
            "dependency_job_ids": list(self.dependency_job_ids),
        }


@dataclass(frozen=True, slots=True)
class SlurmPreparedRunLaunch:
    """Closed queue reference to one already-written whole-run SLURM plan."""

    run_uri: str
    mode: SlurmMode | str
    planning_id: str
    manifest_relative_path: str
    submission_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise QueueServiceError("prepared SLURM launch requires a run_uri")
        object.__setattr__(self, "mode", SlurmMode(self.mode))
        for field_name in ("planning_id", "manifest_relative_path"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise QueueServiceError(
                    f"prepared SLURM launch requires non-empty {field_name}"
                )
        try:
            object.__setattr__(
                self, "submission_digest", validate_digest(self.submission_digest)
            )
        except Exception as exc:
            raise QueueServiceError(
                "prepared SLURM submission_digest is invalid"
            ) from exc

    def to_snapshot(self) -> dict[str, PlainData]:
        return {
            "kind": SLURM_PREPARED_RUN_LAUNCH_TAG,
            "run_uri": self.run_uri,
            "mode": SlurmMode(self.mode).value,
            "planning_id": self.planning_id,
            "manifest_relative_path": self.manifest_relative_path,
            "submission_digest": self.submission_digest,
        }

    @classmethod
    def from_snapshot(cls, value: object) -> "SlurmPreparedRunLaunch":
        if not isinstance(value, Mapping):
            raise QueueServiceError("prepared SLURM launch snapshot must be a mapping")
        expected = {
            "kind",
            "run_uri",
            "mode",
            "planning_id",
            "manifest_relative_path",
            "submission_digest",
        }
        if set(value) != expected or value.get("kind") != SLURM_PREPARED_RUN_LAUNCH_TAG:
            raise QueueServiceError(
                "prepared SLURM launch snapshot fields are unsupported"
            )
        return cls(
            run_uri=cast(str, value["run_uri"]),
            mode=cast(str, value["mode"]),
            planning_id=cast(str, value["planning_id"]),
            manifest_relative_path=cast(str, value["manifest_relative_path"]),
            submission_digest=cast(str, value["submission_digest"]),
        )


def prepared_slurm_launch(
    planning_result: object,
) -> SlurmPreparedRunLaunch:
    """Build the queue-owned reference for an existing dry-run submission."""

    submission = getattr(planning_result, "submission", None)
    if not isinstance(submission, SlurmPlannedSubmission):
        raise QueueServiceError(
            "prepared SLURM launch requires a dry-run planning result"
        )
    return SlurmPreparedRunLaunch(
        run_uri=submission.run_uri,
        mode=cast(SlurmMode, submission.mode),
        planning_id=submission.planning_id,
        manifest_relative_path=cast(str, submission.manifest_relative_path),
        submission_digest=hash_mapping(submission.to_dict()),
    )


@dataclass(frozen=True, slots=True)
class _SchedulerFact:
    scheduler_job_id: str
    source: str
    state: str
    exit_code: str | None = None
    reason: str | None = None
    raw_line: str | None = None

    @property
    def normalized_state(self) -> str:
        state = self.state.strip().upper().split()[0].replace(" ", "_")
        return state.split("+", 1)[0] if "+" in state else state

    @property
    def is_terminal(self) -> bool:
        state = self.normalized_state
        return (
            state in _SLURM_SUCCESS_STATES
            or state in _SLURM_CANCELLED_STATES
            or state in _SLURM_FAILURE_STATES
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "scheduler_job_id": self.scheduler_job_id,
            "source": self.source,
            "state": self.state,
            "normalized_state": self.normalized_state,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "raw_line": self.raw_line,
        }


@dataclass(frozen=True, slots=True)
class _CommandRead:
    source: str
    result: SlurmCommandResult
    facts: Mapping[str, _SchedulerFact]

    @property
    def succeeded(self) -> bool:
        return self.result.ok

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "source": self.source,
            "succeeded": self.succeeded,
            "command": self.result.to_dict(),
            "facts": [fact.to_dict() for fact in self.facts.values()],
        }


@dataclass(frozen=True, slots=True)
class _StatusRead:
    sacct: _CommandRead
    squeue: _CommandRead
    selected_fact: _SchedulerFact | None

    @property
    def succeeded(self) -> bool:
        return self.sacct.succeeded or self.squeue.succeeded

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "succeeded": self.succeeded,
            "selected_fact": None
            if self.selected_fact is None
            else self.selected_fact.to_dict(),
            "sacct": self.sacct.to_dict(),
            "squeue": self.squeue.to_dict(),
        }


class SlurmQueueDispatchAdapter:
    """Submit delegated queue items to SLURM without holding Loom leases."""

    adapter_name = SLURM_QUEUE_ADAPTER_NAME

    def __init__(
        self,
        *,
        command_runner: SlurmCommandRunner | None = None,
        run_store: LegacyRunStore | None = None,
        authority_run_exists: Callable[[str], bool] | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.command_runner = command_runner or SubprocessSlurmCommandRunner()
        self._run_store = run_store
        self._authority_run_exists = authority_run_exists
        self._clock = clock

    def dispatch(self, item: QueueItem) -> QueueDispatchResult:
        if _is_prepared_launch(item):
            return self._dispatch_prepared_run(item)
        launch = _launch_snapshot(item)
        try:
            sbatch = self.command_runner.sbatch(
                launch.script_path,
                dependency_job_ids=launch.dependency_job_ids,
            )
        except Exception as exc:  # noqa: BLE001
            result = command_result_from_exception(
                command="sbatch",
                argv=_sbatch_argv(launch),
                exc=exc,
                started_at=self._clock(),
            )
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.START_UNCERTAIN,
                reason_code="slurm.sbatch_exception",
                evidence=_plain_mapping(
                    {
                        "adapter": SLURM_QUEUE_ADAPTER_NAME,
                        "run_uri": item.run_uri,
                        "launch": launch.to_dict(),
                        "sbatch": result.to_dict(),
                        "external_handle": None,
                        "delegated_handoff": _handoff_evidence(
                            durable=False,
                            external_handle_persisted=False,
                            status_read_succeeded=False,
                        ),
                        "loom_resource_leases_held": False,
                    },
                    path="slurm_submission_failure_evidence",
                ),
            )
        if not sbatch.ok:
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                reason_code="slurm.sbatch_rejected",
                evidence=_plain_mapping(
                    {
                        "adapter": SLURM_QUEUE_ADAPTER_NAME,
                        "run_uri": item.run_uri,
                        "launch": launch.to_dict(),
                        "sbatch": sbatch.to_dict(),
                        "external_handle": None,
                        "delegated_handoff": _handoff_evidence(
                            durable=False,
                            external_handle_persisted=False,
                            status_read_succeeded=False,
                        ),
                        "loom_resource_leases_held": False,
                    },
                    path="slurm_submission_failure_evidence",
                ),
                non_start_cause=QueueDispatchNonStartCause.INTERNAL,
                cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
            )
        try:
            parsed = parse_sbatch_parsable_output(sbatch.stdout)
        except SlurmJobIdParseError as exc:
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.START_UNCERTAIN,
                reason_code="slurm.sbatch_unusable_job_id",
                evidence=_plain_mapping(
                    {
                        "adapter": SLURM_QUEUE_ADAPTER_NAME,
                        "run_uri": item.run_uri,
                        "launch": launch.to_dict(),
                        "sbatch": sbatch.to_dict(),
                        "parse_error": str(exc),
                        "external_handle": None,
                        "delegated_handoff": _handoff_evidence(
                            durable=False,
                            external_handle_persisted=False,
                            status_read_succeeded=False,
                        ),
                        "loom_resource_leases_held": False,
                    },
                    path="slurm_submission_parse_failure_evidence",
                ),
            )

        first_status_read = _run_squeue(
            self.command_runner,
            job_ids=(parsed.job_id,),
            clock=self._clock,
        )
        handoff_durable = first_status_read.succeeded
        verification = _delegated_launch_verification_report(
            item,
            launch=launch,
            scheduler_job_id=parsed.job_id,
            status_read_succeeded=first_status_read.succeeded,
        )
        handle_id = (
            f"slurm:{item.queue_item_id}:{item.dispatch_attempt}:{parsed.job_id}"
        )
        return QueueDispatchResult(
            disposition=QueueDispatchDisposition.STARTED,
            handle_id=handle_id,
            status=QueueItemStatus.DISPATCHED,
            reason_code="slurm.job_submitted",
            evidence=_plain_mapping(
                {
                    "adapter": SLURM_QUEUE_ADAPTER_NAME,
                    "run_uri": item.run_uri,
                    "scheduler_job_id": parsed.job_id,
                    "slurm_cluster": parsed.cluster,
                    "external_handle": {
                        "kind": "slurm_job",
                        "job_id": parsed.job_id,
                        "cluster": parsed.cluster,
                    },
                    "launch": launch.to_dict(),
                    "sbatch": sbatch.to_dict(),
                    "first_status_read": first_status_read.to_dict(),
                    "delegated_handoff": _handoff_evidence(
                        durable=handoff_durable,
                        external_handle_persisted=True,
                        status_read_succeeded=first_status_read.succeeded,
                    ),
                    "delegated_launch_verification": verification,
                    "loom_resource_leases_held": False,
                    "dispatched_at": self._clock(),
                },
                path="slurm_dispatch_evidence",
            ),
        )

    def inspect(self, item: QueueItem) -> QueueDispatchInspection:
        if _is_prepared_launch(item):
            return self._inspect_prepared_run(item)
        job_id = _scheduler_job_id(item)
        status_read = _read_scheduler_status(
            self.command_runner,
            job_ids=(job_id,),
            clock=self._clock,
        )
        diagnostics = self._authority_diagnostics(item)
        persisted_handoff = _persisted_handoff_durable(item)
        handoff_complete = status_read.succeeded or persisted_handoff
        evidence = _plain_mapping(
            {
                "adapter": SLURM_QUEUE_ADAPTER_NAME,
                "run_uri": item.run_uri,
                "scheduler_job_id": job_id,
                "external_handle": {
                    "kind": "slurm_job",
                    "job_id": job_id,
                    "cluster": _slurm_cluster(item),
                },
                "status_read": status_read.to_dict(),
                "delegated_handoff": _handoff_evidence(
                    durable=handoff_complete,
                    external_handle_persisted=True,
                    status_read_succeeded=status_read.succeeded,
                    persisted_status_read_succeeded=persisted_handoff,
                ),
                "authority_run": diagnostics,
                "loom_resource_leases_held": False,
            },
            path="slurm_inspection_evidence",
        )
        fact = status_read.selected_fact
        if fact is not None and fact.is_terminal:
            status = _terminal_status(fact)
            return QueueDispatchInspection(
                status=status,
                reason=_terminal_reason(fact),
                evidence=evidence,
                terminal=True,
            )
        reason = _active_reason(fact, status_read)
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason=reason,
            evidence=evidence,
            terminal=False,
            handoff_complete=handoff_complete,
        )

    def cancel(
        self,
        item: QueueItem,
        *,
        requested_by: str,
        reason: str,
    ) -> QueueDispatchCancellation:
        if _is_prepared_launch(item):
            return self._cancel_prepared_run(
                item, requested_by=requested_by, reason=reason
            )
        job_id = _scheduler_job_id(item)
        try:
            result = self.command_runner.scancel(job_ids=(job_id,))
        except Exception as exc:  # noqa: BLE001
            result = command_result_from_exception(
                command="scancel",
                argv=("scancel", job_id),
                exc=exc,
                started_at=self._clock(),
            )
        outcome = "requested" if result.ok else "unknown"
        cancellation_reason = reason
        if outcome == "unknown":
            cancellation_reason = "SLURM cancellation outcome unknown"
        return QueueDispatchCancellation(
            reason=cancellation_reason,
            evidence=_plain_mapping(
                {
                    "adapter": SLURM_QUEUE_ADAPTER_NAME,
                    "run_uri": item.run_uri,
                    "scheduler_job_id": job_id,
                    "external_handle": {
                        "kind": "slurm_job",
                        "job_id": job_id,
                        "cluster": _slurm_cluster(item),
                    },
                    "requested_by": requested_by,
                    "requested_reason": reason,
                    "cancellation_outcome": outcome,
                    "reported_success": result.ok,
                    "scancel": result.to_dict(),
                    "loom_resource_leases_held": False,
                },
                path="slurm_cancellation_evidence",
            ),
        )

    def recover_claim(self, item: QueueItem) -> QueueDispatchResult | None:
        """Recover only a proven durable prepared-run handoff after queue loss."""

        if not _is_prepared_launch(item):
            return None
        launch, record = self._prepared_record(item)
        if record is None or record.state in {
            SubmittedOperationState.SUBMITTING,
            SubmittedOperationState.UNKNOWN,
        }:
            return self._dispatch_prepared_run(item)
        if record.state not in {
            SubmittedOperationState.SUBMITTED,
            SubmittedOperationState.PARTIAL,
            SubmittedOperationState.CANCELLING,
            SubmittedOperationState.CANCELLED,
            SubmittedOperationState.COMPLETED,
            SubmittedOperationState.FAILED,
        }:
            return None
        return self._prepared_started_result(item, launch, record, recovered=True)

    def _dispatch_prepared_run(self, item: QueueItem) -> QueueDispatchResult:
        launch = _prepared_launch(item)
        if launch.run_uri != item.run_uri:
            return _invalid_prepared_launch("slurm.prepared_run_uri_mismatch")
        if not _prepared_shared_workspace_proven(item):
            return _invalid_prepared_launch(
                "slurm.prepared_shared_workspace_unproven"
            )
        try:
            planning = self._load_prepared_planning(launch)
            self._validate_prepared_paths(planning)
            existing = self._latest_submission(item.run_uri)
            self._submit_prepared(
                launch, planning, queue_item_id=item.queue_item_id
            )
            record = self._latest_submission(item.run_uri)
            if record is None:
                raise QueueServiceError(
                    "prepared SLURM submission did not retain an operation"
                )
            return self._prepared_started_result(
                item,
                launch,
                record,
                recovered=existing is not None,
            )
        except QueueServiceError:
            raise
        except Exception as exc:  # scheduler failures become queue facts, never a retry
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                reason_code="slurm.prepared_submission_rejected",
                evidence={
                    "adapter": SLURM_QUEUE_ADAPTER_NAME,
                    "run_uri": item.run_uri,
                    "error_type": type(exc).__name__,
                },
                non_start_cause=QueueDispatchNonStartCause.INTERNAL,
                cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
            )

    def _inspect_prepared_run(self, item: QueueItem) -> QueueDispatchInspection:
        launch, record = self._prepared_record(item)
        evidence = _prepared_evidence(item, launch, record)
        run_status = self._run_status(item.run_uri)
        terminal = _authority_terminal_status(run_status)
        if terminal is not None:
            return QueueDispatchInspection(
                status=terminal,
                reason="Loom run authority reached terminal state",
                evidence=evidence,
                terminal=True,
            )
        if record is None:
            return QueueDispatchInspection(
                status=QueueItemStatus.UNKNOWN,
                reason="no retained SLURM submission operation is available",
                evidence=evidence,
                terminal=True,
            )
        if record.state is SubmittedOperationState.FAILED:
            return QueueDispatchInspection(
                status=QueueItemStatus.FAILED,
                reason="SLURM submission failed before a Loom terminal result",
                evidence=evidence,
                terminal=True,
            )
        if record.state is SubmittedOperationState.CANCELLED:
            return QueueDispatchInspection(
                status=QueueItemStatus.CANCELLED,
                reason="SLURM submission was cancelled",
                evidence=evidence,
                terminal=True,
            )
        if record.state in {
            SubmittedOperationState.SUBMITTING,
            SubmittedOperationState.UNKNOWN,
        }:
            planning = self._load_prepared_planning(launch)
            self._submit_prepared(launch, planning, queue_item_id=item.queue_item_id)
            record = self._latest_submission(item.run_uri)
            if record is None:
                raise QueueServiceError(
                    "prepared SLURM reconciliation lost its submitted operation"
                )
            evidence = _prepared_evidence(item, launch, record)
        manifest_path = self._prepared_manifest_path(item.run_uri, record)
        manifest = self._prepared_manifest(item.run_uri, record)
        operations = cast(
            tuple[SlurmSchedulerOperation, ...], manifest.scheduler_operations
        )
        if any(
            operation.state is SlurmSchedulerOperationState.CONFLICT
            for operation in operations
        ):
            return QueueDispatchInspection(
                status=QueueItemStatus.UNKNOWN,
                reason="multiple scheduler jobs match one persisted operation marker",
                evidence=evidence,
                terminal=True,
            )
        if manifest.failed_submissions:
            return QueueDispatchInspection(
                status=QueueItemStatus.FAILED,
                reason="SLURM rejected part of the prepared submission",
                evidence=evidence,
                terminal=True,
            )
        job_ids = tuple(
            job.scheduler_job_id
            for job in cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
        )
        if not job_ids:
            if record.state in {
                SubmittedOperationState.SUBMITTING,
                SubmittedOperationState.UNKNOWN,
            }:
                return QueueDispatchInspection(
                    status=QueueItemStatus.DISPATCHED,
                    reason="SLURM operation discovery remains unresolved",
                    evidence=evidence,
                    terminal=False,
                    handoff_complete=True,
                )
            return QueueDispatchInspection(
                status=QueueItemStatus.UNKNOWN,
                reason="retained SLURM operation has no scheduler job handles",
                evidence=evidence,
                terminal=True,
            )
        status_read = _read_scheduler_status(
            self.command_runner, job_ids=job_ids, clock=self._clock
        )
        current_facts = _selected_scheduler_facts(
            status_read=status_read, job_ids=job_ids
        )
        if current_facts:
            manifest = self._persist_current_scheduler_facts(
                manifest_path=manifest_path,
                manifest=manifest,
                current_facts=current_facts,
            )
        effective_facts, retained_used = _effective_scheduler_facts(
            manifest=manifest,
            job_ids=job_ids,
            current_facts=current_facts,
        )
        evidence = {
            **evidence,
            "current_scheduler_facts_persisted": len(current_facts),
            "retained_scheduler_snapshots_used": retained_used,
        }
        if any(
            fact.normalized_state in _SLURM_FAILURE_STATES
            for fact in effective_facts
        ):
            return QueueDispatchInspection(
                status=QueueItemStatus.FAILED,
                reason="SLURM scheduler reported terminal failure",
                evidence={**evidence, "scheduler_status": status_read.to_dict()},
                terminal=True,
            )
        if any(
            fact.normalized_state in _SLURM_CANCELLED_STATES
            for fact in effective_facts
        ):
            return QueueDispatchInspection(
                status=QueueItemStatus.CANCELLED,
                reason="SLURM scheduler reported cancellation",
                evidence={**evidence, "scheduler_status": status_read.to_dict()},
                terminal=True,
            )
        if len(effective_facts) == len(job_ids) and all(
            fact.normalized_state in _SLURM_SUCCESS_STATES
            for fact in effective_facts
        ):
            return QueueDispatchInspection(
                status=QueueItemStatus.DISPATCHED,
                reason="SLURM completed; waiting for Loom run authority result",
                evidence={**evidence, "scheduler_status": status_read.to_dict()},
                terminal=False,
                handoff_complete=True,
            )
        if not effective_facts:
            return QueueDispatchInspection(
                status=QueueItemStatus.UNKNOWN,
                reason="no current or retained SLURM scheduler fact is available",
                evidence={**evidence, "scheduler_status": status_read.to_dict()},
                terminal=True,
            )
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason="SLURM work remains active or is settling",
            evidence={**evidence, "scheduler_status": status_read.to_dict()},
            terminal=False,
            handoff_complete=True,
        )

    def _cancel_prepared_run(
        self, item: QueueItem, *, requested_by: str, reason: str
    ) -> QueueDispatchCancellation:
        launch, record = self._prepared_record(item)
        job_ids = (
            ()
            if record is None
            else self._prepared_job_ids(item.run_uri, launch, record)
        )
        if not job_ids:
            return QueueDispatchCancellation(
                reason="SLURM cancellation outcome unknown",
                evidence={
                    **_prepared_evidence(item, launch, record),
                    "cancellation_outcome": "unknown",
                },
            )
        try:
            result = self.command_runner.scancel(job_ids=job_ids)
        except Exception as exc:  # noqa: BLE001
            result = command_result_from_exception(
                command="scancel",
                argv=("scancel", *job_ids),
                exc=exc,
                started_at=self._clock(),
            )
        return QueueDispatchCancellation(
            reason=reason if result.ok else "SLURM cancellation outcome unknown",
            evidence={
                **_prepared_evidence(item, launch, record),
                "requested_by": requested_by,
                "requested_reason": reason,
                "cancellation_outcome": "requested" if result.ok else "unknown",
                "reported_success": result.ok,
                "scancel": result.to_dict(),
                "loom_resource_leases_held": False,
            },
        )

    def _load_prepared_planning(
        self, launch: SlurmPreparedRunLaunch
    ) -> SlurmDryRunPlanningResult:
        store = self._require_run_store()
        paths = cast(LocalRunStorePaths, store)
        manifest = resolve_slurm_generated_artifact_path(
            paths, launch.run_uri, launch.manifest_relative_path
        )
        try:
            raw = json.loads(manifest.local_path.read_text(encoding="utf-8"))
            try:
                submission = SlurmPlannedSubmission.from_dict(raw)
            except Exception:
                live = read_slurm_live_manifest(raw)
                submission = SlurmPlannedSubmission(
                    run_uri=live.run_uri,
                    mode=live.mode,
                    planning_id=live.planning_id,
                    created_at=live.created_at,
                    plan_relative_path=live.plan_relative_path,
                    manifest_relative_path=live.manifest_relative_path,
                    options=live.options,
                    jobs=live.jobs,
                    dependencies=live.dependencies,
                    generated_command_argv=live.generated_command_argv,
                    resources=live.resources,
                )
        except (OSError, ValueError, TypeError) as exc:
            raise QueueServiceError("prepared SLURM manifest is unreadable") from exc
        if (
            submission.run_uri != launch.run_uri
            or submission.planning_id != launch.planning_id
            or SlurmMode(submission.mode) is not SlurmMode(launch.mode)
            or hash_mapping(submission.to_dict()) != launch.submission_digest
        ):
            raise QueueServiceError(
                "prepared SLURM manifest does not match queue launch"
            )
        return SlurmDryRunPlanningResult(
            submission=submission,
            manifest_artifact=manifest,
            plan_artifact=resolve_slurm_generated_artifact_path(
                paths, launch.run_uri, submission.plan_relative_path
            ),
            script_artifacts={
                job.logical_key: resolve_slurm_generated_artifact_path(
                    paths, launch.run_uri, cast(str, job.script_relative_path)
                )
                for job in cast(tuple[SlurmPlannedJob, ...], submission.jobs)
            },
        )

    def _validate_prepared_paths(self, planning: SlurmDryRunPlanningResult) -> None:
        if not all(item.local_path.is_file() for item in planning.generated_artifacts):
            raise QueueServiceError(
                "prepared SLURM artifacts are not compute-visible files"
            )

    def _submit_prepared(
        self,
        launch: SlurmPreparedRunLaunch,
        planning: SlurmDryRunPlanningResult,
        *,
        queue_item_id: str,
    ) -> SlurmLiveSubmissionResult:
        store = self._require_run_store()
        if SlurmMode(launch.mode) is SlurmMode.SINGLE_JOB:
            return submit_single_job_slurm(
                run_store=store,
                run_uri=launch.run_uri,
                planning_result=planning,
                command_runner=self.command_runner,
                queue_item_id=queue_item_id,
            )
        return submit_afterok_slurm(
            run_store=store,
            run_uri=launch.run_uri,
            planning_result=planning,
            command_runner=self.command_runner,
            queue_item_id=queue_item_id,
        )

    def _prepared_started_result(
        self,
        item: QueueItem,
        launch: SlurmPreparedRunLaunch,
        record: SubmittedOperationRecord,
        *,
        recovered: bool = False,
    ) -> QueueDispatchResult:
        scheduler_job_ids = self._prepared_job_ids(item.run_uri, launch, record)
        scheduler_handle_persisted = bool(scheduler_job_ids)
        unresolved = record.state in {
            SubmittedOperationState.SUBMITTING,
            SubmittedOperationState.UNKNOWN,
        }
        return QueueDispatchResult(
            disposition=QueueDispatchDisposition.STARTED,
            handle_id=f"slurm-prepared:{item.queue_item_id}:{item.dispatch_attempt}:{record.submission_id}",
            status=QueueItemStatus.DISPATCHED,
            reason_code=(
                "slurm.prepared_submission_pending_reconciliation"
                if unresolved
                else (
                    "slurm.prepared_submission_recovered"
                    if recovered
                    else "slurm.prepared_submission_accepted"
                )
            ),
            evidence={
                **_prepared_evidence(item, launch, record),
                "scheduler_operation_persisted": True,
                "delegated_handoff": _handoff_evidence(
                    durable=True,
                    external_handle_persisted=scheduler_handle_persisted,
                    status_read_succeeded=False,
                ),
                "loom_resource_leases_held": False,
            },
        )

    def _prepared_record(
        self, item: QueueItem
    ) -> tuple[SlurmPreparedRunLaunch, SubmittedOperationRecord | None]:
        launch = _prepared_launch(item)
        record = self._latest_submission(item.run_uri)
        if record is not None:
            queue = record.backend_metadata.get("queue")
            if (
                record.run_uri != launch.run_uri
                or record.mode != SlurmMode(launch.mode).value
                or record.manifest_relative_path != launch.manifest_relative_path
                or not isinstance(queue, Mapping)
                or queue.get("queue_item_id") != item.queue_item_id
            ):
                raise QueueServiceError(
                    "retained SLURM operation does not agree with prepared queue launch"
                )
        return launch, record

    def _prepared_manifest(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> SlurmLiveSubmissionManifest:
        path = self._prepared_manifest_path(run_uri, record)
        try:
            return read_slurm_live_manifest(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError) as exc:
            raise QueueServiceError("retained SLURM manifest is unreadable") from exc

    def _prepared_manifest_path(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> Path:
        store = self._require_run_store()
        return resolve_slurm_generated_artifact_path(
            cast(LocalRunStorePaths, store), run_uri, record.manifest_relative_path
        ).local_path

    def _persist_current_scheduler_facts(
        self,
        *,
        manifest_path: Path,
        manifest: SlurmLiveSubmissionManifest,
        current_facts: Sequence[_SchedulerFact],
    ) -> SlurmLiveSubmissionManifest:
        logical_keys = {
            job.scheduler_job_id: job.logical_key
            for job in cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
        }
        captured_at = self._clock()
        snapshots = tuple(
            SlurmSchedulerStatusSnapshot(
                logical_key=logical_keys[fact.scheduler_job_id],
                scheduler_job_id=fact.scheduler_job_id,
                captured_at=captured_at,
                source=fact.source,
                state=fact.state,
                exit_code=fact.exit_code,
            )
            for fact in current_facts
        )
        updated = replace(
            manifest,
            updated_at=captured_at,
            status_snapshots=tuple(manifest.status_snapshots) + snapshots,
        )
        try:
            write_slurm_live_manifest(manifest_path, updated)
        except Exception as exc:  # noqa: BLE001
            raise QueueServiceError(
                "failed to persist current SLURM scheduler facts"
            ) from exc
        return updated

    def _latest_submission(self, run_uri: str) -> SubmittedOperationRecord | None:
        store = self._require_run_store()
        latest = getattr(store, "latest_submitted_operation", None)
        value = latest(run_uri) if callable(latest) else None
        return value if isinstance(value, SubmittedOperationRecord) else None

    def _prepared_job_ids(
        self,
        run_uri: str,
        launch: SlurmPreparedRunLaunch,
        record: SubmittedOperationRecord,
    ) -> tuple[str, ...]:
        try:
            manifest = self._prepared_manifest(run_uri, record)
        except QueueServiceError:
            return ()
        return tuple(
            cast(str, getattr(job, "scheduler_job_id"))
            for job in manifest.submitted_jobs
        )

    def _run_status(self, run_uri: str) -> object | None:
        reader = getattr(self._require_run_store(), "read_run_status", None)
        return reader(run_uri) if callable(reader) else None

    def _require_run_store(self) -> LegacyRunStore:
        if self._run_store is None:
            raise QueueServiceError("prepared SLURM dispatch requires a run store")
        return self._run_store

    def _authority_diagnostics(self, item: QueueItem) -> Mapping[str, PlainData]:
        if self._authority_run_exists is None:
            return {
                "checked": False,
                "missing_authority_run": None,
                "diagnostics": [],
            }
        try:
            exists = bool(self._authority_run_exists(item.run_uri))
        except Exception as exc:  # noqa: BLE001
            return {
                "checked": True,
                "missing_authority_run": None,
                "diagnostics": [
                    {
                        "code": "queue.slurm.authority_run_check_error",
                        "message": "authority run visibility check failed",
                        "run_uri": item.run_uri,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                ],
            }
        if exists:
            return {
                "checked": True,
                "missing_authority_run": False,
                "diagnostics": [],
            }
        return {
            "checked": True,
            "missing_authority_run": True,
            "diagnostics": [
                {
                    "code": "queue.slurm.missing_authority_run",
                    "message": "external SLURM handle is active but no authority run is visible",
                    "run_uri": item.run_uri,
                }
            ],
        }


def _launch_snapshot(item: QueueItem) -> SlurmDelegatedLaunch:
    snapshot = item.launch_contract.snapshot
    script_path = snapshot.get("script_path")
    if not isinstance(script_path, str) or not script_path:
        raise QueueServiceError("SLURM launch snapshot requires non-empty script_path")
    dependency_job_ids = _job_id_sequence(
        snapshot.get("dependency_job_ids", ()),
        field="dependency_job_ids",
    )
    return SlurmDelegatedLaunch(
        script_path=script_path,
        dependency_job_ids=dependency_job_ids,
    )


def _is_prepared_launch(item: QueueItem) -> bool:
    return item.launch_contract.snapshot.get("kind") == SLURM_PREPARED_RUN_LAUNCH_TAG


def _prepared_launch(item: QueueItem) -> SlurmPreparedRunLaunch:
    return SlurmPreparedRunLaunch.from_snapshot(item.launch_contract.snapshot)


def _invalid_prepared_launch(reason_code: str) -> QueueDispatchResult:
    return QueueDispatchResult(
        disposition=QueueDispatchDisposition.NOT_STARTED,
        reason_code=reason_code,
        evidence={"adapter": SLURM_QUEUE_ADAPTER_NAME},
        non_start_cause=QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED,
        cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
    )


def _prepared_evidence(
    item: QueueItem,
    launch: SlurmPreparedRunLaunch,
    record: SubmittedOperationRecord | None,
) -> dict[str, PlainData]:
    return {
        "adapter": SLURM_QUEUE_ADAPTER_NAME,
        "prepared_run": {
            "run_uri": launch.run_uri,
            "mode": SlurmMode(launch.mode).value,
            "planning_id": launch.planning_id,
            "manifest_relative_path": launch.manifest_relative_path,
            "submission_digest": launch.submission_digest,
        },
        "queue_item_id": item.queue_item_id,
        "submitted_operation": None
        if record is None
        else {
            "submission_id": record.submission_id,
            "state": record.state.value,
            "manifest_relative_path": record.manifest_relative_path,
        },
        "loom_resource_leases_held": False,
    }


def _retained_scheduler_facts(
    manifest: SlurmLiveSubmissionManifest,
) -> dict[str, _SchedulerFact]:
    """Return the newest retained fact for every accepted scheduler handle."""

    accepted = {
        job.scheduler_job_id
        for job in cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    }
    latest: dict[str, SlurmSchedulerStatusSnapshot] = {}
    for snapshot in cast(
        tuple[SlurmSchedulerStatusSnapshot, ...], manifest.status_snapshots
    ):
        if snapshot.scheduler_job_id not in accepted:
            continue
        previous = latest.get(snapshot.scheduler_job_id)
        if previous is None or snapshot.captured_at > previous.captured_at:
            latest[snapshot.scheduler_job_id] = snapshot
    return {
        scheduler_job_id: _SchedulerFact(
            scheduler_job_id=snapshot.scheduler_job_id,
            source=snapshot.source,
            state=snapshot.state,
            exit_code=snapshot.exit_code,
        )
        for scheduler_job_id, snapshot in latest.items()
    }


def _selected_scheduler_facts(
    *, status_read: _StatusRead, job_ids: Sequence[str]
) -> tuple[_SchedulerFact, ...]:
    """Select one current scheduler fact for each accepted handle."""

    return tuple(
        fact
        for job_id in job_ids
        if (
            fact := _select_fact(
                job_ids=(job_id,),
                sacct_facts=status_read.sacct.facts,
                squeue_facts=status_read.squeue.facts,
            )
        )
        is not None
    )


def _effective_scheduler_facts(
    *,
    manifest: SlurmLiveSubmissionManifest,
    job_ids: Sequence[str],
    current_facts: Sequence[_SchedulerFact],
) -> tuple[tuple[_SchedulerFact, ...], bool]:
    """Keep current facts authoritative, using retained facts only per gap."""

    current_by_job_id = {
        fact.scheduler_job_id: fact for fact in current_facts
    }
    retained_by_job_id = _retained_scheduler_facts(manifest)
    effective: list[_SchedulerFact] = []
    retained_used = False
    for job_id in job_ids:
        fact = current_by_job_id.get(job_id)
        if fact is None:
            fact = retained_by_job_id.get(job_id)
            retained_used = retained_used or fact is not None
        if fact is not None:
            effective.append(fact)
    return tuple(effective), retained_used


def _prepared_shared_workspace_proven(item: QueueItem) -> bool:
    """Require the project to attest compute visibility before first submission."""

    raw = thaw_plain_data(
        item.launch_contract.delegated_verification,
        path="delegated_verification",
    )
    if not isinstance(raw, Mapping):
        return False
    shared_workspace = raw.get("shared_workspace")
    if shared_workspace is True:
        return True
    return (
        isinstance(shared_workspace, Mapping)
        and set(shared_workspace) == {"status"}
        and shared_workspace.get("status") == "proven"
    )


def _authority_terminal_status(value: object | None) -> QueueItemStatus | None:
    status = getattr(value, "status", None)
    try:
        run_status = RunStatus(status)
    except (TypeError, ValueError):
        return None
    if run_status is RunStatus.SUCCEEDED:
        return QueueItemStatus.SUCCEEDED
    if run_status in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
        return QueueItemStatus.FAILED
    if run_status is RunStatus.CANCELLED:
        return QueueItemStatus.CANCELLED
    return None


def _job_id_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise QueueServiceError(f"{field} must be a sequence of decimal job IDs")
    ids: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.isdecimal():
            raise QueueServiceError(f"{field}[{index}] must be decimal job ID text")
        ids.append(item)
    return tuple(ids)


def _scheduler_job_id(item: QueueItem) -> str:
    evidence = _dispatch_evidence(item)
    job_id = evidence.get("scheduler_job_id")
    if isinstance(job_id, str) and job_id.isdecimal():
        return job_id
    handle = evidence.get("external_handle")
    if isinstance(handle, Mapping):
        handle_job_id = handle.get("job_id")
        if isinstance(handle_job_id, str) and handle_job_id.isdecimal():
            return handle_job_id
    raise QueueServiceError("SLURM dispatched item is missing scheduler_job_id")


def _slurm_cluster(item: QueueItem) -> str | None:
    evidence = _dispatch_evidence(item)
    cluster = evidence.get("slurm_cluster")
    if cluster is None or isinstance(cluster, str):
        return cluster
    handle = evidence.get("external_handle")
    if isinstance(handle, Mapping):
        handle_cluster = handle.get("cluster")
        if handle_cluster is None or isinstance(handle_cluster, str):
            return handle_cluster
    return None


def _persisted_handoff_durable(item: QueueItem) -> bool:
    evidence = _dispatch_evidence(item)
    handoff = evidence.get("delegated_handoff")
    if not isinstance(handoff, Mapping):
        return False
    return handoff.get("durable") is True


def _dispatch_evidence(item: QueueItem) -> Mapping[str, PlainData]:
    if item.dispatch_handle is None:
        raise QueueServiceError("SLURM item has no dispatch handle")
    evidence = thaw_plain_data(
        item.dispatch_handle.evidence, path="dispatch_handle.evidence"
    )
    if not isinstance(evidence, Mapping):
        raise QueueServiceError("SLURM dispatch evidence must be a mapping")
    return cast(Mapping[str, PlainData], evidence)


def _run_squeue(
    runner: SlurmCommandRunner,
    *,
    job_ids: Sequence[str],
    clock: Callable[[], str],
) -> _CommandRead:
    try:
        result = runner.squeue(job_ids=job_ids)
    except Exception as exc:  # noqa: BLE001
        result = command_result_from_exception(
            command="squeue",
            argv=_squeue_argv(job_ids),
            exc=exc,
            started_at=clock(),
        )
    facts = _parse_squeue_output(result) if result.ok else {}
    return _CommandRead(source="squeue", result=result, facts=facts)


def _run_sacct(
    runner: SlurmCommandRunner,
    *,
    job_ids: Sequence[str],
    clock: Callable[[], str],
) -> _CommandRead:
    try:
        result = runner.sacct(job_ids=job_ids)
    except Exception as exc:  # noqa: BLE001
        result = command_result_from_exception(
            command="sacct",
            argv=_sacct_argv(job_ids),
            exc=exc,
            started_at=clock(),
        )
    facts = _parse_sacct_output(result) if result.ok else {}
    return _CommandRead(source="sacct", result=result, facts=facts)


def _read_scheduler_status(
    runner: SlurmCommandRunner,
    *,
    job_ids: Sequence[str],
    clock: Callable[[], str],
) -> _StatusRead:
    sacct = _run_sacct(runner, job_ids=job_ids, clock=clock)
    squeue = _run_squeue(runner, job_ids=job_ids, clock=clock)
    selected_fact = _select_fact(
        job_ids=job_ids,
        sacct_facts=sacct.facts,
        squeue_facts=squeue.facts,
    )
    return _StatusRead(sacct=sacct, squeue=squeue, selected_fact=selected_fact)


def _select_fact(
    *,
    job_ids: Sequence[str],
    sacct_facts: Mapping[str, _SchedulerFact],
    squeue_facts: Mapping[str, _SchedulerFact],
) -> _SchedulerFact | None:
    for job_id in job_ids:
        sacct_fact = sacct_facts.get(job_id)
        if sacct_fact is not None and sacct_fact.is_terminal:
            return sacct_fact
        squeue_fact = squeue_facts.get(job_id)
        if squeue_fact is not None:
            return squeue_fact
        if sacct_fact is not None:
            return sacct_fact
    return None


def _parse_sacct_output(result: SlurmCommandResult) -> dict[str, _SchedulerFact]:
    facts: dict[str, _SchedulerFact] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        job_id = _root_job_id(parts[0])
        if job_id is None:
            continue
        fact = _SchedulerFact(
            scheduler_job_id=job_id,
            source="sacct",
            state=parts[1] or "UNKNOWN",
            exit_code=parts[2] if len(parts) >= 3 and parts[2] else None,
            raw_line=raw_line,
        )
        existing = facts.get(job_id)
        if existing is None or (fact.is_terminal and not existing.is_terminal):
            facts[job_id] = fact
    return facts


def _parse_squeue_output(result: SlurmCommandResult) -> dict[str, _SchedulerFact]:
    facts: dict[str, _SchedulerFact] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        job_id = _root_job_id(parts[0])
        if job_id is None:
            continue
        facts[job_id] = _SchedulerFact(
            scheduler_job_id=job_id,
            source="squeue",
            state=parts[1] or "UNKNOWN",
            reason=parts[2] if len(parts) >= 3 and parts[2] else None,
            raw_line=raw_line,
        )
    return facts


def _root_job_id(value: str) -> str | None:
    candidate = value.strip().split(".", 1)[0].split("_", 1)[0]
    return candidate if candidate.isdecimal() else None


def _terminal_status(fact: _SchedulerFact) -> QueueItemStatus:
    state = fact.normalized_state
    if state in _SLURM_SUCCESS_STATES:
        return QueueItemStatus.SUCCEEDED
    if state in _SLURM_CANCELLED_STATES:
        return QueueItemStatus.CANCELLED
    if state in _SLURM_FAILURE_STATES:
        return QueueItemStatus.FAILED
    return QueueItemStatus.UNKNOWN


def _terminal_reason(fact: _SchedulerFact) -> str:
    status = _terminal_status(fact)
    if status is QueueItemStatus.SUCCEEDED:
        return "SLURM job completed"
    if status is QueueItemStatus.CANCELLED:
        return "SLURM job cancelled"
    if status is QueueItemStatus.FAILED:
        return f"SLURM job failed with state {fact.normalized_state}"
    return "SLURM job terminal state is unknown"


def _active_reason(fact: _SchedulerFact | None, status_read: _StatusRead) -> str:
    if fact is not None:
        if fact.normalized_state in _SLURM_ACTIVE_STATES:
            return f"SLURM job active with state {fact.normalized_state}"
        return f"SLURM job status is {fact.normalized_state}"
    if status_read.succeeded:
        return "SLURM job status read succeeded but scheduler state is unavailable"
    return "SLURM job status read unavailable"


def _delegated_launch_verification_report(
    item: QueueItem,
    *,
    launch: SlurmDelegatedLaunch,
    scheduler_job_id: str | None,
    status_read_succeeded: bool,
) -> Mapping[str, PlainData]:
    raw = thaw_plain_data(
        item.launch_contract.delegated_verification,
        path="delegated_verification",
    )
    checks: list[Mapping[str, object]] = []
    if isinstance(raw, Mapping):
        for name, value in raw.items():
            if (
                name == "required_checks"
                and isinstance(value, Sequence)
                and not isinstance(value, str)
            ):
                for item_name in value:
                    if isinstance(item_name, str) and item_name:
                        checks.append(
                            _verification_check(item_name, False, "launch_contract")
                        )
                continue
            if isinstance(name, str) and name:
                checks.append(_verification_check(name, value, "launch_contract"))
    checks.extend(
        [
            _adapter_check(
                "script_path_present",
                bool(launch.script_path),
                "launch snapshot contains a script path",
            ),
            _adapter_check(
                "external_handle_persisted",
                scheduler_job_id is not None,
                "sbatch returned a scheduler job id",
            ),
            _adapter_check(
                "downstream_status_read",
                status_read_succeeded,
                "adapter read scheduler status after submit",
            ),
            _adapter_check(
                "loom_resource_leases_not_held",
                True,
                "delegated SLURM pending work does not hold Loom resource leases",
            ),
        ]
    )
    proven = [str(check["name"]) for check in checks if check["status"] == "proven"]
    unproven = [str(check["name"]) for check in checks if check["status"] == "unproven"]
    unsupported = [
        str(check["name"]) for check in checks if check["status"] == "unsupported"
    ]
    return _plain_mapping(
        {
            "schema_version": 1,
            "checks": list(checks),
            "proven": proven,
            "unproven": unproven,
            "unsupported": unsupported,
            "summary": {
                "proven_count": len(proven),
                "unproven_count": len(unproven),
                "unsupported_count": len(unsupported),
            },
        },
        path="delegated_launch_verification",
    )


def _verification_check(
    name: str,
    value: object,
    source: str,
) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        status_value = value.get("status")
        if isinstance(status_value, str) and status_value in {
            "proven",
            "unproven",
            "unsupported",
        }:
            status = cast(str, status_value)
        else:
            status = "proven" if value.get("proven") is True else "unproven"
        reason = value.get("reason")
    else:
        status = "proven" if value is True else "unproven"
        reason = None
    return {
        "name": name,
        "status": status,
        "source": source,
        "reason": reason
        if isinstance(reason, str) and reason
        else _verification_reason(name, status),
    }


def _adapter_check(
    name: str,
    proven: bool,
    reason: str,
) -> Mapping[str, object]:
    return {
        "name": name,
        "status": "proven" if proven else "unproven",
        "source": "slurm_queue_adapter",
        "reason": reason,
    }


def _verification_reason(name: str, status: str) -> str:
    if status == "proven":
        return f"{name} is recorded as proven by the launch contract"
    if status == "unsupported":
        return f"{name} is recorded as unsupported by the launch contract"
    return f"{name} is not proven by the delegated SLURM adapter"


def _handoff_evidence(
    *,
    durable: bool,
    external_handle_persisted: bool,
    status_read_succeeded: bool,
    persisted_status_read_succeeded: bool | None = None,
) -> dict[str, PlainData]:
    return {
        "durable": durable,
        "external_handle_persisted": external_handle_persisted,
        "downstream_status_read_succeeded": status_read_succeeded,
        "persisted_downstream_status_read_succeeded": persisted_status_read_succeeded,
        "authority_run_visibility_required": False,
        "loom_resource_leases_held": False,
    }


def _sbatch_argv(launch: SlurmDelegatedLaunch) -> tuple[str, ...]:
    argv = ["sbatch", "--parsable"]
    if launch.dependency_job_ids:
        argv.append("--dependency=afterok:" + ":".join(launch.dependency_job_ids))
    argv.append(launch.script_path)
    return tuple(argv)


def _squeue_argv(job_ids: Sequence[str]) -> tuple[str, ...]:
    argv = ["squeue", "--noheader", "--format", "%i|%T|%r"]
    ids = tuple(job_ids)
    if ids:
        argv.extend(("--jobs", ",".join(ids)))
    return tuple(argv)


def _sacct_argv(job_ids: Sequence[str]) -> tuple[str, ...]:
    argv = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--format",
        "JobIDRaw,State,ExitCode",
    ]
    ids = tuple(job_ids)
    if ids:
        argv.extend(("--jobs", ",".join(ids)))
    return tuple(argv)


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    thawed = thaw_plain_data(frozen, path=path)
    if not isinstance(thawed, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], thawed)


__all__ = [
    "SLURM_QUEUE_ADAPTER_NAME",
    "SLURM_PREPARED_RUN_LAUNCH_TAG",
    "SlurmDelegatedLaunch",
    "SlurmPreparedRunLaunch",
    "SlurmQueueDispatchAdapter",
    "prepared_slurm_launch",
]
