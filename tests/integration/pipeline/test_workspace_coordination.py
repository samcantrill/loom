"""Integration coverage for SQLite workspace coordination behavior."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    BackendRevision,
    RecoveryKind,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
    SweepIdentity,
)
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore


pytestmark = pytest.mark.integration


@dataclass(slots=True)
class FrozenClock:
    tick: int = 0

    def __call__(self) -> str:
        return f"2020-01-01T00:00:{self.tick:02d}Z"


def test_concurrent_sqlite_trial_claims_cannot_double_claim(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workspace" / ".loom" / "coordination.sqlite3"
    clock = FrozenClock()
    store = SQLiteWorkspaceCoordinationStore(database_path, clock=clock)
    _seed_trial(store, "trial-1")

    def claim(owner_id: str) -> str:
        contender = SQLiteWorkspaceCoordinationStore(database_path, clock=clock)
        try:
            return contender.acquire_trial_lease(
                "sweep-1",
                "trial-1",
                owner_id=owner_id,
                lease_ttl_seconds=30,
            ).lease.owner_id
        except ValueError as exc:
            return f"error:{exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(claim, ("worker-1", "worker-2")))

    assert sorted(result.startswith("error:") for result in results) == [False, True]
    assert "trial already has an active lease" in " ".join(results)


def test_sqlite_resource_limits_recover_expired_capacity(tmp_path: Path) -> None:
    database_path = tmp_path / "coordination.sqlite3"
    clock = FrozenClock()
    store = SQLiteWorkspaceCoordinationStore(database_path, clock=clock)
    _seed_trial(store, "trial-1")
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    initial_limit = store.read_resource_limit("workspace-1", "gpu")
    assert initial_limit is not None
    assert initial_limit.counter_name == "resource:gpu"
    assert initial_limit.value == 0
    assert initial_limit.limit == 2

    first = store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="worker-1",
        amount=2,
        lease_ttl_seconds=1,
    )
    with pytest.raises(ValueError, match="resource limit"):
        store.acquire_resource_lease(
            "workspace-1",
            "gpu",
            owner_id="worker-2",
            amount=1,
            lease_ttl_seconds=30,
        )

    clock.tick = 2
    recovery = store.scan_recovery("workspace-1")
    assert [(record.resource_key, record.amount) for record in recovery] == [
        ("gpu", 2)
    ]
    assert recovery[0].recovery.kind is RecoveryKind.EXPIRED_LEASE

    second = store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="worker-2",
        amount=1,
        lease_ttl_seconds=30,
    )
    assert second.lease.lease_id != first.lease.lease_id
    recovered_limit = store.read_resource_limit("workspace-1", "gpu")
    assert recovered_limit is not None
    assert recovered_limit.value == 1
    assert recovered_limit.limit == 2


def test_sqlite_counters_are_transactional_and_guarded(tmp_path: Path) -> None:
    database_path = tmp_path / "coordination.sqlite3"
    store = SQLiteWorkspaceCoordinationStore(database_path, clock=FrozenClock())
    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    store.set_counter_limit("workspace-1", "active_trials", limit=1)

    def increment(owner_id: str) -> str:
        contender = SQLiteWorkspaceCoordinationStore(
            database_path,
            clock=FrozenClock(),
        )
        try:
            counter = contender.increment_counter("workspace-1", "active_trials")
            return f"{owner_id}:{counter.value}"
        except ValueError as exc:
            return f"{owner_id}:error:{exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(increment, ("worker-1", "worker-2")))

    assert sorted(":error:" in result for result in results) == [False, True]
    assert store.read_counter("workspace-1", "active_trials") is not None
    assert store.decrement_counter("workspace-1", "active_trials").value == 0
    assert store.increment_counter("workspace-1", "active_trials").value == 1


def test_sqlite_trial_references_do_not_read_per_run_authority(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "coordination.sqlite3"
    missing_run = tmp_path / "runs" / "missing"
    store = SQLiteWorkspaceCoordinationStore(database_path, clock=FrozenClock())
    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    store.create_sweep(SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1"))
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri=missing_run.as_uri(),
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=1, token="external-rev"),
    )

    store.record_trial(trial)

    assert store.list_trials("sweep-1") == (trial,)
    assert not (missing_run / ".loom").exists()


def _seed_trial(store: SQLiteWorkspaceCoordinationStore, trial_id: str) -> None:
    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    store.create_sweep(SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1"))
    store.record_trial(
        TrialReference(
            trial_id=trial_id,
            sweep_id="sweep-1",
            run_uri=f"file:///runs/{trial_id}",
            state=TrialState.PENDING,
            revision=BackendRevision(sequence=1, token=f"{trial_id}-rev"),
        )
    )
