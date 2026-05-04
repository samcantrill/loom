"""Lifecycle helpers for run and stage status persistence."""

from __future__ import annotations

from collections.abc import Mapping

from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import RunStore
from loom.serialization import PlainData, ensure_plain_data


def next_stage_attempt(run_store: RunStore, run_id: str, stage_name: str) -> int:
    status = run_store.read_stage_status(run_id, stage_name)
    if status is None:
        return 1
    return status.attempt + 1


def write_run_status(
    run_store: RunStore,
    *,
    run_id: str,
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
        run_id=run_id,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        started_at=started_at,
        finished_at=finished_at,
        message=message,
        metadata=normalized_metadata,
    )
    run_store.write_run_status(run_id, record)
    return record


def write_stage_running(
    run_store: RunStore,
    *,
    run_id: str,
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
        run_id=run_id,
        stage_name=stage_name,
        status=StageStatus.RUNNING,
        attempt=attempt,
        updated_at=started_at,
        started_at=started_at,
        owner=normalized_owner,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_id, stage_name, record)
    return record


def write_stage_succeeded(
    run_store: RunStore,
    *,
    run_id: str,
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
        run_id=run_id,
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
    run_store.write_stage_status(run_id, stage_name, record)
    return record


def write_stage_failed(
    run_store: RunStore,
    *,
    run_id: str,
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
        run_id=run_id,
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
    run_store.write_stage_status(run_id, stage_name, record)
    return record


def write_stage_skipped(
    run_store: RunStore,
    *,
    run_id: str,
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
        run_id=run_id,
        stage_name=stage_name,
        status=StageStatus.SKIPPED,
        attempt=attempt,
        updated_at=finished_at,
        finished_at=finished_at,
        message=message,
        metadata=normalized_metadata,
    )
    run_store.write_stage_status(run_id, stage_name, record)
    return record


__all__ = [
    "next_stage_attempt",
    "write_run_status",
    "write_stage_running",
    "write_stage_succeeded",
    "write_stage_failed",
    "write_stage_skipped",
]
