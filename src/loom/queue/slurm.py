"""Delegated SLURM dispatch adapter for queue controllers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loom.pipeline.executors.slurm.commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
    command_result_from_exception,
    parse_sbatch_parsable_output,
)
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
        authority_run_exists: Callable[[str], bool] | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.command_runner = command_runner or SubprocessSlurmCommandRunner()
        self._authority_run_exists = authority_run_exists
        self._clock = clock

    def dispatch(self, item: QueueItem) -> QueueDispatchResult:
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
    "SlurmDelegatedLaunch",
    "SlurmQueueDispatchAdapter",
]
