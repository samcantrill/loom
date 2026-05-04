"""Run-lock helpers for execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from loom.pipeline.locks import RunLockRecord
from loom.pipeline.stores import RunLockStore
from loom.serialization import PlainData


@dataclass(frozen=True, slots=True)
class ActiveRunLock:
    run_id: str
    token: str

    @classmethod
    def from_record(cls, record: RunLockRecord) -> "ActiveRunLock":
        return cls(run_id=record.run_id, token=record.token)


def build_lock_owner(*, component: str, run_id: str, executor: str) -> dict[str, PlainData]:
    """Build canonical lock owner metadata for execution-held locks."""

    return {
        "component": component,
        "run_id": run_id,
        "executor": executor,
    }


def acquire_run_lock(
    run_store: RunLockStore,
    run_id: str,
    *,
    owner: Mapping[str, PlainData] | None = None,
) -> ActiveRunLock:
    return ActiveRunLock.from_record(run_store.acquire_run_lock(run_id, owner=owner))


def release_run_lock(run_store: RunLockStore, lock: ActiveRunLock | None) -> None:
    if lock is None:
        return
    run_store.release_run_lock(lock.run_id, lock.token)


__all__ = ["ActiveRunLock", "acquire_run_lock", "build_lock_owner", "release_run_lock"]
