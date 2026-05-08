"""Lifecycle helpers for run and stage status persistence."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.planning import StagePlan
from loom.pipeline.specs import StageSpec
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import RunStore
from loom.pipeline.stores.indexes import format_artifact_key, merge_artifact_index
from loom.serialization import PlainData, ensure_plain_data

from .errors import PlanExecutionError


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
    run_store.write_run_status(run_uri, record)
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


__all__ = [
    "bind_stage_inputs",
    "next_stage_attempt",
    "write_stage_artifact_index_refs",
    "write_run_status",
    "write_stage_running",
    "write_stage_succeeded",
    "write_stage_failed",
    "write_stage_skipped",
    "write_stage_blocked",
]
