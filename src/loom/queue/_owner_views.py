"""Project one admission from separately observed journal and authority facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from loom.diagnostics.diagnostic_failure import project_diagnostic_failure
from loom.pipeline.execution.models import ExecutionFailure, StageWorkerResult
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.specs import parse_pipeline_config
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.configuration import read_configuration_json

from .errors import QueueServiceError
from .local_daemon import LocalDaemonAdmission, LocalDaemonAdmissionState, LocalDaemonConfig

if TYPE_CHECKING:
    from ._owner_journals import AgentJournalRead, ExecutionJournalRead


def _run_result_owner_view(
    config: LocalDaemonConfig,
    admission: LocalDaemonAdmission,
    *,
    snapshot: AuthoritativeRunSnapshot | None,
    authority_failure: Exception | None = None,
    clock: Callable[[], str],
) -> Mapping[str, PlainData]:
    """Project persisted failures and launch controls as one fail-closed view."""

    observed_at = clock()
    try:
        if snapshot is None:
            if authority_failure is None:
                raise QueueServiceError("failed-stage authority is unavailable")
            raise QueueServiceError("failed-stage authority is unavailable") from authority_failure
        store = LocalRunStore(config.run_store_root)
        store.open_run(admission.run_uri)
        raw_plan = store.read_plan(admission.run_uri)
        if raw_plan is None:
            raise QueueServiceError("run-store plan is unavailable")
        plan = ExecutionPlan.from_dict(raw_plan)
        if plan.run_uri != admission.run_uri:
            raise QueueServiceError("run-store plan does not match admission")
        resolved_snapshot = store.read_config_snapshot(admission.run_uri, "resolved")
        if resolved_snapshot is None:
            raise QueueServiceError("run-store resolved pipeline is unavailable")
        resolved = read_configuration_json(resolved_snapshot, path="config/resolved.json")
        if not isinstance(resolved, Mapping) or "pipeline" not in resolved:
            raise QueueServiceError("run-store resolved pipeline is invalid")
        pipeline = parse_pipeline_config(resolved["pipeline"])
        if set(plan.stage_order) != set(pipeline.stage_names):
            raise QueueServiceError("run-store plan and pipeline disagree")

        failures: list[PlainData] = []
        controls: list[PlainData] = []
        failed_stage_count = 0
        stages = {stage.stage_name: stage for stage in snapshot.stages}
        for stage_name in plan.stage_order:
            stage = stages.get(stage_name)
            if (
                stage is not None
                and stage.status in {StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.CANCELLED}
                and stage.attempts
            ):
                attempt = stage.attempts[-1].attempt
                result_payload = store.read_stage_worker_result(
                    admission.run_uri, stage_name, attempt=attempt
                )
                if result_payload is not None:
                    result = StageWorkerResult.from_dict(result_payload)
                    if (
                        result.run_uri != admission.run_uri
                        or result.stage_name != stage_name
                        or result.attempt != attempt
                    ):
                        raise QueueServiceError("persisted stage result conflicts with identity")
                    evidence = result.executor_metadata.get("resource_controls")
                    if evidence is not None:
                        controls.append(
                            {
                                "stage_name": stage_name,
                                "attempt": attempt,
                                "controls": evidence,
                            }
                        )
            if stage is None or stage.status is not StageStatus.FAILED:
                continue
            failed_stage_count += 1
            if not stage.attempts:
                raise QueueServiceError("failed stage has no authoritative attempt")
            persisted = store.read_stage_failure(admission.run_uri, stage_name)
            if persisted is None:
                raise QueueServiceError("failed stage has no persisted failure")
            failure = ExecutionFailure.from_dict(persisted)
            if (
                failure.run_uri != admission.run_uri
                or failure.stage_name != stage_name
                or failure.attempt != stage.attempts[-1].attempt
            ):
                raise QueueServiceError("persisted stage failure conflicts with status")
            failures.append(failure.to_dict())
        if admission.state is LocalDaemonAdmissionState.FAILED and failed_stage_count == 0:
            raise QueueServiceError("failed admission has no persisted failure")
    except Exception as exc:
        return {
            "owner": "run-store",
            "availability": "unavailable",
            "state": "unavailable",
            "observed_at": observed_at,
            "freshness": "unavailable",
            "diagnostic": "run_store_unavailable",
            "diagnostic_failure": project_diagnostic_failure(exc),
            "failures": [],
        }
    return {
        "owner": "run-store",
        "availability": "available",
        "state": "populated" if failures or controls else "empty",
        "observed_at": observed_at,
        "freshness": "current",
        "diagnostic": None,
        "diagnostic_failure": None,
        "failures": failures,
        **({"resource_controls": controls} if controls else {}),
    }


def _journal_axis(
    owner: str,
    field: str,
    rows: list[dict[str, PlainData]] | None,
    revision: int | None,
    observed_at: str,
    diagnostic: str,
) -> dict[str, PlainData]:
    return {
        "owner": owner,
        "availability": "unavailable" if rows is None else "available",
        "state": "unavailable" if rows is None else "populated" if rows else "empty",
        "revision": revision,
        "observed_at": observed_at,
        "freshness": "unavailable" if rows is None else "current",
        "diagnostic": diagnostic if rows is None else None,
        field: [] if rows is None else cast(list[PlainData], rows),
    }


def project_owner_view(
    config: LocalDaemonConfig,
    admission: LocalDaemonAdmission,
    admission_revision: int,
    *,
    admission_observed_at: str,
    execution: ExecutionJournalRead,
    agent: AgentJournalRead,
    clock: Callable[[], str],
    read_snapshot: Callable[[str], AuthoritativeRunSnapshot] | None,
) -> dict[str, PlainData]:
    rows = execution.by_run.get(admission.run_uri)
    stage_work = None if rows is None else rows.work
    assignments = None if rows is None else rows.assignments
    slurm = None if rows is None else rows.slurm
    scheduling_revision = None if rows is None else execution.scheduling_revision
    assignment_revision = None if rows is None else execution.assignment_revision
    journal = agent.by_run.get(admission.run_uri)
    agent_revision = None if journal is None else agent.revision
    authority_view: dict[str, PlainData]
    authority_observed_at = clock()
    snapshot: AuthoritativeRunSnapshot | None = None
    authority_failure: Exception | None = None
    cancellation_receipt: dict[str, PlainData] | None = None
    try:
        factory = config.coordinator_authority_factory
        if factory is None:
            raise QueueServiceError("coordinator authority factory is unavailable")
        snapshot = (
            read_snapshot(admission.run_uri)
            if read_snapshot is not None
            else factory(admission.run_uri).open_run(admission.run_uri)
        )
        if admission.cancellation_operation_id is not None:
            receipt = factory(admission.run_uri).read_cancellation_epoch_receipt(
                admission.run_uri, admission.cancellation_operation_id
            )
            cancellation_receipt = None if receipt is None else receipt.to_dict()
    except Exception as exc:
        authority_failure = exc
        authority_view = {
            "owner": "per-run-authority",
            "availability": "unavailable",
            "state": "unavailable",
            "diagnostic": "authority_unavailable",
            "observed_at": authority_observed_at,
            "freshness": "unavailable",
        }
    else:
        authority_view = {
            "owner": "per-run-authority",
            "availability": "available",
            "state": snapshot.status.value,
            "observed_at": authority_observed_at,
            "revision": snapshot.revision.to_dict(),
            "stages": {stage.stage_name: stage.status.value for stage in snapshot.stages},
            "artifacts": {
                f"{stage.stage_name}.{fact.artifact_name}": fact.artifact.to_dict()
                for stage in snapshot.stages
                for fact in stage.artifact_facts
            },
            "stage_reasons": {
                stage.stage_name: stage.reason.to_dict()
                for stage in snapshot.stages
                if stage.reason is not None
            },
            "attempts": [
                {
                    "stage_name": stage.stage_name,
                    "attempt": attempt.attempt,
                    "attempt_id": attempt.attempt_id,
                    "state": attempt.status.value,
                    "revision": attempt.revision.to_dict(),
                }
                for stage in snapshot.stages
                for attempt in stage.attempts
            ],
            "freshness": "current",
        }
    run_result_view = _run_result_owner_view(
        config,
        admission,
        snapshot=snapshot,
        authority_failure=authority_failure,
        clock=clock,
    )
    healthy = rows is not None and journal is not None and authority_view["availability"] == "available"
    view = ensure_plain_data(
        {
            "queue_item_id": admission.queue_item_id,
            "run_uri": admission.run_uri,
            "admission": {
                "owner": "coordinator",
                "availability": "available",
                "state": admission.state.value,
                "accepted_at": admission.accepted_at,
                "intent_digest": admission.intent_digest,
                "authority_operation_id": admission.authority_operation_id,
                "revision": admission_revision,
                "observed_at": admission_observed_at,
                "freshness": "current",
            },
            "authority": authority_view,
            "run_result": run_result_view,
            "scheduling": _journal_axis(
                "coordinator-stage-work",
                "work",
                stage_work,
                scheduling_revision,
                execution.observed_at,
                "execution_store_unavailable",
            ),
            "assignment": _journal_axis(
                "coordinator-assignments",
                "assignments",
                assignments,
                assignment_revision,
                execution.observed_at,
                "execution_store_unavailable",
            ),
            "slurm": _journal_axis(
                "coordinator-slurm",
                "assignments",
                slurm,
                assignment_revision,
                execution.observed_at,
                "execution_store_unavailable",
            ),
            "execution": _journal_axis(
                "local-agent",
                "journal",
                journal,
                agent_revision,
                agent.observed_at,
                "agent_journal_unavailable",
            ),
            "cancellation": {
                "owner": "coordinator-and-per-run-authority",
                "availability": authority_view["availability"],
                "state": (
                    "requested_degraded"
                    if authority_view["availability"] == "unavailable"
                    and admission.cancellation_operation_id is not None
                    else "terminal"
                    if admission.state is LocalDaemonAdmissionState.CANCELLED
                    else "terminal_prevailed"
                    if admission.cancellation_operation_id is not None
                    and admission.state
                    in {
                        LocalDaemonAdmissionState.SUCCEEDED,
                        LocalDaemonAdmissionState.FAILED,
                    }
                    else "settling"
                    if admission.state is LocalDaemonAdmissionState.CANCELLING
                    else "effective"
                    if cancellation_receipt is not None
                    else "requested"
                    if admission.cancellation_operation_id is not None
                    else "not_requested"
                ),
                "requested": admission.cancellation_operation_id is not None,
                "operation_id": admission.cancellation_operation_id,
                "principal": admission.cancellation_principal_id,
                "effective": cancellation_receipt is not None,
                "settling": admission.state is LocalDaemonAdmissionState.CANCELLING,
                "terminal": admission.state
                in {
                    LocalDaemonAdmissionState.CANCELLED,
                    LocalDaemonAdmissionState.SUCCEEDED,
                    LocalDaemonAdmissionState.FAILED,
                },
                "receipt": cancellation_receipt,
                "observed_at": authority_observed_at,
                "freshness": ("current" if authority_view["availability"] == "available" else "unavailable"),
            },
            "service": {
                "owner": "local-daemon",
                "availability": "available" if healthy else "unavailable",
                "state": "healthy" if healthy else "degraded",
                "diagnostic": None if healthy else "owner_status_unavailable",
                "revision": {
                    "admission": admission_revision,
                    "scheduling": scheduling_revision,
                    "assignment": assignment_revision,
                    "execution": agent_revision,
                },
                "observed_at": clock(),
                "freshness": "current" if healthy else "unavailable",
            },
        },
        path="local_daemon_status.runs",
    )
    if not isinstance(view, dict):
        raise AssertionError("local daemon owner view must be a mapping")
    return view
