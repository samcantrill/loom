"""Lifecycle helpers for run and stage status persistence."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.planning import PlanAction, StagePlan
from loom.pipeline.reliability import StageAttemptTransactionState
from loom.pipeline.specs import StageSpec
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores import LegacyRunStore as RunStore
from loom.pipeline.stores import LifecycleReason
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.indexes import format_artifact_key, merge_artifact_index
from loom.serialization import PlainData, ensure_plain_data
from loom.timestamps import utc_timestamp

from .errors import PlanExecutionError
from .eventing import RuntimeEventDispatcher, emit_stage_event
from .models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionResult,
    StageRunResult,
)
from .outputs import validate_stage_outputs
from .reliability import (
    build_reliability_status_detail,
    classify_execution_failure,
    failure_with_reliability_classification,
    record_reliability_transaction,
    record_stage_reliability_transition,
    record_timeout_outcome_from_metadata,
)


def next_stage_attempt(run_store: RunStore, run_uri: str, stage_name: str) -> int:
    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None:
        return 1
    return status.attempt + 1


def bind_stage_inputs(
    *,
    stage: StageSpec,
    stage_plan: StagePlan,
    produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
) -> dict[str, ArtifactRef]:
    inputs: dict[str, ArtifactRef] = {
        name: bound.artifact_ref for name, bound in stage_plan.bound_inputs.items()
    }
    for pending in stage_plan.pending_inputs:
        upstream = produced_outputs.get(pending.source_stage)
        if upstream is None or pending.source_output not in upstream:
            raise PlanExecutionError(
                f"Cannot bind input {stage.name}.{pending.input_name} from "
                f"{pending.source_stage}.{pending.source_output}"
            )
        inputs[pending.input_name] = upstream[pending.source_output]
    expected = set(stage.inputs)
    if set(inputs) != expected:
        missing = expected - set(inputs)
        extra = set(inputs) - expected
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"extra {', '.join(sorted(extra))}")
        raise PlanExecutionError(
            f"Input binding mismatch for stage {stage.name}: {'; '.join(parts)}"
        )
    return inputs


def write_stage_artifact_index_refs(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    outputs: Mapping[str, ArtifactRef],
    replace: bool,
) -> None:
    updates = {
        format_artifact_key(stage_name, output_name): ref
        for output_name, ref in outputs.items()
    }
    existing = run_store.read_artifact_index(run_uri)
    run_store.write_artifact_index(
        run_uri, merge_artifact_index(existing, updates, replace=replace)
    )


def write_stage_provenance(
    run_store: RunStore,
    *,
    run_uri: str,
    stage: StageSpec,
    status: StageStatus,
    attempt: int,
    started_at: str,
    finished_at: str,
    fingerprint: Mapping[str, PlainData],
    inputs: Mapping[str, ArtifactRef],
    outputs: Mapping[str, ArtifactRef],
    executor_metadata: Mapping[str, PlainData],
) -> None:
    from loom.provenance.models import StageProvenance

    provenance = StageProvenance(
        run_uri=run_uri,
        stage_name=stage.name,
        status=status.value,
        attempt=attempt,
        target=stage.target_path,
        started_at=started_at,
        finished_at=finished_at,
        fingerprint=_plain(fingerprint, path="fingerprint"),
        input_artifacts={
            name: _plain(ref.to_dict(), path="inputs") for name, ref in inputs.items()
        },
        output_artifacts={
            name: _plain(ref.to_dict(), path="outputs") for name, ref in outputs.items()
        },
        executor_metadata=_plain(executor_metadata, path="executor_metadata"),
    )
    run_store.write_stage_provenance(
        run_uri,
        stage.name,
        _plain(provenance.to_dict(), path="stage_provenance"),
        attempt=attempt,
    )


def write_failed_run(
    run_store: RunStore,
    *,
    run_uri: str,
    created_at: str,
    started_at: str,
    failure: ExecutionFailure,
) -> None:
    write_run_status(
        run_store,
        run_uri=run_uri,
        status=RunStatus.FAILED,
        created_at=created_at,
        updated_at=failure.failed_at,
        started_at=started_at,
        finished_at=failure.failed_at,
        message=failure.message,
        metadata={
            "failed_stage": failure.stage_name,
            "failure_type": failure.failure_type,
        },
    )


def write_cancelled_run(
    run_store: RunStore,
    *,
    run_uri: str,
    created_at: str,
    started_at: str,
    cancelled_at: str,
    reason: LifecycleReason,
    stage_name: str | None = None,
) -> None:
    metadata = _reason_metadata(reason)
    if stage_name is not None:
        metadata["cancelled_stage"] = stage_name
    write_run_status(
        run_store,
        run_uri=run_uri,
        status=RunStatus.CANCELLED,
        created_at=created_at,
        updated_at=cancelled_at,
        started_at=started_at,
        finished_at=cancelled_at,
        message=reason.message,
        metadata=metadata,
    )


def persist_stage_failure(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    failure: ExecutionFailure,
    clock: Callable[[], str] = utc_timestamp,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> ExecutionFailure:
    detail = build_reliability_status_detail(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        stage_status=StageStatus.FAILED,
        attempt=attempt,
        created_at=failure.failed_at,
    )
    classification = classify_execution_failure(failure, status=detail)
    failure = failure_with_reliability_classification(failure, classification)
    run_store.write_stage_failure(
        run_uri, stage_name, failure.to_dict(), attempt=attempt
    )
    record_reliability_transaction(
        run_store,
        run_uri=run_uri,
        status=detail,
        state=StageAttemptTransactionState.FAILED,
    )
    write_stage_failed(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        started_at=started_at,
        finished_at=failure.failed_at,
        message=failure.message,
        metadata={"failure_type": failure.failure_type},
    )
    emit_stage_event(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        event_type="stage.failed",
        timestamp=clock(),
        payload={"attempt": attempt, "failure_type": failure.failure_type},
        event_dispatcher=event_dispatcher,
    )
    return failure


def persist_stage_cancellation(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    cancelled_at: str,
    reason: LifecycleReason,
    clock: Callable[[], str] = utc_timestamp,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> None:
    detail = build_reliability_status_detail(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        stage_status=StageStatus.CANCELLED,
        attempt=attempt,
        created_at=cancelled_at,
    )
    record_reliability_transaction(
        run_store,
        run_uri=run_uri,
        status=detail,
        state=StageAttemptTransactionState.CANCELLED,
    )
    write_stage_cancelled(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        started_at=started_at,
        cancelled_at=cancelled_at,
        message=reason.message,
        metadata=_reason_metadata(reason),
    )
    emit_stage_event(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        event_type="stage.cancelled",
        timestamp=clock(),
        payload={"attempt": attempt, "reason": reason.to_dict()},
        event_dispatcher=event_dispatcher,
    )


def record_stage_failure_and_failed_run(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    created_at: str,
    run_started_at: str,
    failure: ExecutionFailure,
    executor_name: str,
    clock: Callable[[], str] = utc_timestamp,
    event_dispatcher: RuntimeEventDispatcher | None = None,
    finalize_run: bool = True,
) -> ExecutionFailure:
    try:
        failure = persist_stage_failure(
            run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            started_at=started_at,
            failure=failure,
            clock=clock,
            event_dispatcher=event_dispatcher,
        )
    except Exception as exc:
        failure = ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            failed_at=clock(),
            executor=executor_name,
            failure_type="store_commit",
            message=str(exc) or type(exc).__name__,
            exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
        )
    if finalize_run:
        write_failed_run(
            run_store,
            run_uri=run_uri,
            created_at=created_at,
            started_at=run_started_at,
            failure=failure,
        )
    return failure


def commit_stage_execution_result(
    run_store: RunStore,
    *,
    run_uri: str,
    stage: StageSpec,
    stage_plan: StagePlan,
    attempt: int,
    inputs: Mapping[str, ArtifactRef],
    fingerprint: Mapping[str, PlainData],
    artifact_store: ArtifactStore,
    created_at: str,
    run_started_at: str,
    execution_result: StageExecutionResult,
    executor_name: str,
    clock: Callable[[], str] = utc_timestamp,
    event_dispatcher: RuntimeEventDispatcher | None = None,
    finalize_run_on_failure: bool = True,
) -> StageRunResult:
    if execution_result.status == StageStatus.FAILED:
        failure = execution_result.failure or ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            failed_at=clock(),
            executor=execution_result.executor_name,
            failure_type="executor_infrastructure",
            message="executor failed without failure metadata",
        )
        failure = record_stage_failure_and_failed_run(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            started_at=execution_result.started_at,
            created_at=created_at,
            run_started_at=run_started_at,
            failure=failure,
            executor_name=executor_name,
            clock=clock,
            event_dispatcher=event_dispatcher,
            finalize_run=finalize_run_on_failure,
        )
        record_timeout_outcome_from_metadata(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            stage_status=StageStatus.FAILED,
            recorded_at=failure.failed_at,
            executor_metadata=execution_result.executor_metadata,
        )
        return StageRunResult(
            stage_name=stage.name,
            action=PlanAction.RUN,
            status=StageStatus.FAILED,
            attempt=attempt,
            outputs={},
            failure=failure,
            reasons=stage_plan.reasons,
            started_at=execution_result.started_at,
            finished_at=execution_result.finished_at,
            executor_metadata=execution_result.executor_metadata,
        )

    if execution_result.status == StageStatus.CANCELLED:
        reason = _execution_result_lifecycle_reason(execution_result)
        persist_stage_cancellation(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            started_at=execution_result.started_at,
            cancelled_at=execution_result.finished_at,
            reason=reason,
            clock=clock,
            event_dispatcher=event_dispatcher,
        )
        record_timeout_outcome_from_metadata(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            stage_status=StageStatus.CANCELLED,
            recorded_at=execution_result.finished_at,
            executor_metadata=execution_result.executor_metadata,
        )
        return StageRunResult(
            stage_name=stage.name,
            action=PlanAction.RUN,
            status=StageStatus.CANCELLED,
            attempt=attempt,
            outputs={},
            failure=None,
            reasons=stage_plan.reasons,
            started_at=execution_result.started_at,
            finished_at=execution_result.finished_at,
            executor_metadata=execution_result.executor_metadata,
        )

    outputs = validate_stage_outputs(
        stage=stage,
        outputs=execution_result.outputs,
        artifact_store=artifact_store,
    )
    record_stage_reliability_transition(
        run_store,
        run_uri=run_uri,
        stage_name=stage.name,
        attempt=attempt,
        state=StageAttemptTransactionState.STAGED,
        stage_status=StageStatus.RUNNING,
        recorded_at=clock(),
    )
    try:
        if any(reason.code.value == "ARTIFACT_CHECKSUM_MISMATCH" for reason in stage_plan.reasons):
            authorize = getattr(run_store, "authorize_checksum_repair_output", None)
            if callable(authorize):
                authorize(run_uri, stage.name)
        run_store.write_stage_outputs(run_uri, stage.name, outputs, attempt=attempt)
        write_stage_artifact_index_refs(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            outputs=outputs,
            replace=True,
        )
        write_stage_provenance(
            run_store,
            run_uri=run_uri,
            stage=stage,
            status=StageStatus.SUCCEEDED,
            attempt=attempt,
            started_at=execution_result.started_at,
            finished_at=execution_result.finished_at,
            fingerprint=fingerprint,
            inputs=inputs,
            outputs=outputs,
            executor_metadata=execution_result.executor_metadata,
        )
        record_stage_reliability_transition(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            state=StageAttemptTransactionState.COMMITTED,
            stage_status=StageStatus.SUCCEEDED,
            recorded_at=execution_result.finished_at,
        )
        write_stage_succeeded(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            started_at=execution_result.started_at,
            finished_at=execution_result.finished_at,
            metadata={"action": PlanAction.RUN.value},
        )
        record_timeout_outcome_from_metadata(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            stage_status=StageStatus.SUCCEEDED,
            recorded_at=execution_result.finished_at,
            executor_metadata=execution_result.executor_metadata,
        )
    except Exception:
        record_stage_reliability_transition(
            run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            state=StageAttemptTransactionState.COMMIT_FAILED,
            stage_status=StageStatus.FAILED,
            recorded_at=clock(),
        )
        raise
    emit_stage_event(
        run_store,
        run_uri=run_uri,
        stage_name=stage.name,
        event_type="stage.completed",
        timestamp=clock(),
        payload={
            "attempt": attempt,
            "action": PlanAction.RUN.value,
            "status": StageStatus.SUCCEEDED.value,
        },
        event_dispatcher=event_dispatcher,
    )
    return StageRunResult(
        stage_name=stage.name,
        action=PlanAction.RUN,
        status=StageStatus.SUCCEEDED,
        attempt=attempt,
        outputs=outputs,
        reasons=stage_plan.reasons,
        started_at=execution_result.started_at,
        finished_at=execution_result.finished_at,
        executor_metadata=execution_result.executor_metadata,
    )


def write_run_status(
    run_store: RunStore,
    *,
    run_uri: str,
    status: RunStatus,
    created_at: str,
    updated_at: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    message: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
    intent: TransitionIntent = TransitionIntent.NORMAL,
) -> RunStatusRecord:
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_metadata, dict):
        raise ValueError("metadata must be a mapping")
    record = RunStatusRecord(
        run_uri=run_uri,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        started_at=started_at,
        finished_at=finished_at,
        message=message,
        metadata=normalized_metadata,
    )
    write_with_intent = getattr(run_store, "write_run_status_with_intent", None)
    if callable(write_with_intent):
        write_with_intent(run_uri, record, intent=intent)
    else:
        run_store.write_run_status(run_uri, record)
    return record


def write_run_submitted(
    run_store: RunStore,
    *,
    run_uri: str,
    created_at: str,
    submitted_at: str,
    message: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> RunStatusRecord:
    return write_run_status(
        run_store,
        run_uri=run_uri,
        status=RunStatus.SUBMITTED,
        created_at=created_at,
        updated_at=submitted_at,
        message=message,
        metadata=metadata,
    )


def write_stage_submitted(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    submitted_at: str,
    message: str | None = None,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    normalized_owner = ensure_plain_data(dict(owner or {}), path="owner")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_owner, dict) or not isinstance(
        normalized_metadata, dict
    ):
        raise ValueError("owner and metadata must be mappings")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.SUBMITTED,
        attempt=attempt,
        updated_at=submitted_at,
        message=message,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def write_stage_running(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    normalized_owner = ensure_plain_data(dict(owner or {}), path="owner")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_owner, dict) or not isinstance(
        normalized_metadata, dict
    ):
        raise ValueError("owner and metadata must be mappings")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.RUNNING,
        attempt=attempt,
        updated_at=started_at,
        started_at=started_at,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    record_stage_reliability_transition(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        state=StageAttemptTransactionState.RUNNING,
        stage_status=StageStatus.RUNNING,
        recorded_at=started_at,
    )
    return record


def write_stage_succeeded(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str,
    finished_at: str,
    message: str | None = None,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    normalized_owner = ensure_plain_data(dict(owner or {}), path="owner")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_owner, dict) or not isinstance(
        normalized_metadata, dict
    ):
        raise ValueError("owner and metadata must be mappings")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.SUCCEEDED,
        attempt=attempt,
        updated_at=finished_at,
        started_at=started_at,
        finished_at=finished_at,
        message=message,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def write_stage_failed(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    finished_at: str,
    message: str,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    if not message:
        raise ValueError("message is required for failed stage status")
    normalized_owner = ensure_plain_data(dict(owner or {}), path="owner")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_owner, dict) or not isinstance(
        normalized_metadata, dict
    ):
        raise ValueError("owner and metadata must be mappings")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.FAILED,
        attempt=attempt,
        updated_at=finished_at,
        started_at=started_at,
        finished_at=finished_at,
        message=message,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def write_stage_cancelled(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    started_at: str | None,
    cancelled_at: str,
    message: str | None = None,
    owner: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    normalized_owner = ensure_plain_data(dict(owner or {}), path="owner")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_owner, dict) or not isinstance(
        normalized_metadata, dict
    ):
        raise ValueError("owner and metadata must be mappings")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.CANCELLED,
        attempt=attempt,
        updated_at=cancelled_at,
        started_at=started_at,
        finished_at=cancelled_at,
        message=message,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def write_stage_skipped(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    finished_at: str,
    message: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_metadata, dict):
        raise ValueError("metadata must be a mapping")
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.SKIPPED,
        attempt=attempt,
        updated_at=finished_at,
        finished_at=finished_at,
        message=message,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def write_stage_blocked(
    run_store: RunStore,
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    blocked_at: str,
    message: str,
    blocked_by: PlainData | None = None,
    reason_code: str | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> StageStatusRecord:
    if not message:
        raise ValueError("message is required for blocked stage status")
    normalized_metadata = ensure_plain_data(dict(metadata or {}), path="metadata")
    if not isinstance(normalized_metadata, dict):
        raise ValueError("metadata must be a mapping")
    if blocked_by is not None:
        normalized_metadata["blocked_by"] = ensure_plain_data(
            blocked_by, path="blocked_by"
        )
    if reason_code is not None:
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError("reason_code must be a non-empty string")
        normalized_metadata["reason_code"] = reason_code
    record = StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.BLOCKED,
        attempt=attempt,
        updated_at=blocked_at,
        message=message,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_uri, stage_name, record)
    return record


def _plain(value: object, *, path: str) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise PlanExecutionError(f"{path} must be mapping plain data")
    return normalized


def _reason_metadata(reason: LifecycleReason) -> dict[str, PlainData]:
    if not isinstance(reason, LifecycleReason):
        raise ValueError("reason must be LifecycleReason")
    return {
        "reason": reason.to_dict(),
        "reason_code": reason.code,
    }


def _execution_result_lifecycle_reason(
    execution_result: StageExecutionResult,
) -> LifecycleReason:
    raw = execution_result.executor_metadata.get("lifecycle_reason")
    if isinstance(raw, Mapping):
        try:
            return LifecycleReason.from_dict(raw)
        except Exception:
            pass
    return LifecycleReason(
        code="early_stop",
        message="stage requested early stop",
    )


__all__ = [
    "bind_stage_inputs",
    "commit_stage_execution_result",
    "next_stage_attempt",
    "persist_stage_cancellation",
    "persist_stage_failure",
    "record_stage_failure_and_failed_run",
    "write_stage_artifact_index_refs",
    "write_cancelled_run",
    "write_failed_run",
    "write_run_status",
    "write_run_submitted",
    "write_stage_provenance",
    "write_stage_submitted",
    "write_stage_running",
    "write_stage_succeeded",
    "write_stage_cancelled",
    "write_stage_failed",
    "write_stage_skipped",
    "write_stage_blocked",
]
