"""Contract tests for workspace and sweep coordination stores."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from loom.authority._repository import AuthorityRepository
from loom.authority.mutation_service import (
    AuthorityMutationOperation,
    AuthorityMutationService,
)
from loom.pipeline.stores import (
    AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH,
    AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH,
    AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH,
    AUTHORITY_COORDINATION_COUNTER_READ_PATH,
    AUTHORITY_COORDINATION_LEASE_FAIL_PATH,
    AUTHORITY_COORDINATION_LEASE_RELEASE_PATH,
    AUTHORITY_COORDINATION_LEASE_RENEW_PATH,
    AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH,
    AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH,
    AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH,
    AUTHORITY_COORDINATION_SWEEP_CREATE_PATH,
    AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH,
    AUTHORITY_COORDINATION_TRIAL_LIST_PATH,
    AUTHORITY_COORDINATION_TRIAL_RECORD_PATH,
    AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH,
    AuthorityClient,
    BackendCapability,
    BackendRevision,
    CapabilityScope,
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    CoordinationStoreError,
    LeaseKind,
    LeaseState,
    LifecycleReason,
    RecoveryKind,
    ServiceWorkspaceCoordinationStore,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    TrialState,
    WorkspaceCoordinationStore,
    WorkspaceIdentity,
    coordination_requirement_diagnostics,
)
from loom.serialization import PlainData
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


pytestmark = pytest.mark.contract


@dataclass(slots=True)
class FrozenClock:
    tick: int = 0

    def __call__(self) -> str:
        return f"2020-01-01T00:00:{self.tick:02d}Z"


@dataclass(slots=True)
class CoordinationStoreCase:
    name: str
    store: WorkspaceCoordinationStore
    clock: FrozenClock | None = None
    supports_resources: bool = True


_COORDINATION_OPERATIONS = {
    AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH: (
        AuthorityMutationOperation.CREATE_WORKSPACE
    ),
    AUTHORITY_COORDINATION_SWEEP_CREATE_PATH: AuthorityMutationOperation.CREATE_SWEEP,
    AUTHORITY_COORDINATION_TRIAL_RECORD_PATH: AuthorityMutationOperation.RECORD_TRIAL,
    AUTHORITY_COORDINATION_TRIAL_LIST_PATH: AuthorityMutationOperation.LIST_TRIALS,
    AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH: (
        AuthorityMutationOperation.ACQUIRE_TRIAL_LEASE
    ),
    AUTHORITY_COORDINATION_LEASE_RENEW_PATH: (
        AuthorityMutationOperation.RENEW_COORDINATION_LEASE
    ),
    AUTHORITY_COORDINATION_LEASE_RELEASE_PATH: (
        AuthorityMutationOperation.RELEASE_COORDINATION_LEASE
    ),
    AUTHORITY_COORDINATION_LEASE_FAIL_PATH: (
        AuthorityMutationOperation.FAIL_COORDINATION_LEASE
    ),
    AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH: (
        AuthorityMutationOperation.SET_COUNTER_LIMIT
    ),
    AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH: (
        AuthorityMutationOperation.INCREMENT_COUNTER
    ),
    AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH: (
        AuthorityMutationOperation.DECREMENT_COUNTER
    ),
    AUTHORITY_COORDINATION_COUNTER_READ_PATH: AuthorityMutationOperation.READ_COUNTER,
    AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH: (
        AuthorityMutationOperation.SCAN_COORDINATION_RECOVERY
    ),
    AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH: (
        AuthorityMutationOperation.ACQUIRE_RESOURCE_LEASE
    ),
    AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH: (
        AuthorityMutationOperation.SET_RESOURCE_LIMIT
    ),
}


@pytest.fixture(params=["in-memory", "sqlite", "service"])
def coordination_case(
    request: pytest.FixtureRequest, tmp_path: Path
) -> CoordinationStoreCase:
    if request.param == "in-memory":
        return CoordinationStoreCase(
            name="in-memory",
            store=InMemoryWorkspaceCoordinationStore(),
        )
    if request.param == "sqlite":
        clock = FrozenClock()
        return CoordinationStoreCase(
            name="sqlite",
            store=SQLiteWorkspaceCoordinationStore(
                tmp_path / "workspace" / ".loom" / "coordination.sqlite3",
                clock=clock,
            ),
            clock=clock,
        )
    clock = FrozenClock()
    repository = AuthorityRepository(tmp_path / "authority", clock=clock)
    repository.initialize(service_generation="generation-1")
    service = AuthorityMutationService(repository)

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        path = urlsplit(url).path
        operation = _COORDINATION_OPERATIONS[path]
        return service.handle(operation, payload).to_dict()

    return CoordinationStoreCase(
        name="service",
        store=ServiceWorkspaceCoordinationStore(
            AuthorityClient("http://authority.test", transport=transport),
            workspace_id="workspace-1",
            service_generation="generation-1",
        ),
        clock=clock,
    )


def test_workspace_coordination_stores_satisfy_protocol(
    coordination_case: CoordinationStoreCase,
) -> None:
    store = coordination_case.store

    assert isinstance(store, WorkspaceCoordinationStore)
    assert store.capabilities().supports(
        BackendCapability.CROSS_RUN_COORDINATION,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert store.capabilities().supports(
        BackendCapability.GLOBAL_COUNTERS,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert not hasattr(store, "transition_stage")


def test_workspace_coordination_contract_records_cross_run_facts_only(
    coordination_case: CoordinationStoreCase,
) -> None:
    store = coordination_case.store
    _seed_workspace(store)

    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=1, token="external-rev"),
    )
    store.record_trial(trial)

    assert store.list_trials("sweep-1") == (trial,)

    trial_lease = store.acquire_trial_lease(
        "sweep-1",
        "trial-1",
        owner_id="sweep-worker",
        lease_ttl_seconds=30,
    )
    assert isinstance(trial_lease, TrialLeaseRecord)
    assert trial_lease.workspace_id == "workspace-1"
    assert trial_lease.sweep_id == "sweep-1"
    assert trial_lease.trial_id == "trial-1"
    assert trial_lease.lease.kind is LeaseKind.TRIAL
    assert TrialLeaseRecord.from_dict(trial_lease.to_dict()) == trial_lease

    if coordination_case.supports_resources:
        resource = store.acquire_resource_lease(
            "workspace-1",
            "gpu",
            owner_id="sweep-worker",
            amount=2,
            lease_ttl_seconds=30,
        )
        assert resource.workspace_id == "workspace-1"
        assert resource.resource_key == "gpu"
        assert resource.amount == 2
        assert resource.lease.kind is LeaseKind.RESOURCE
        assert type(resource).from_dict(resource.to_dict()) == resource

    counter = store.increment_counter("workspace-1", "active_trials")
    assert isinstance(counter, ConcurrencyCounter)
    assert store.read_counter("workspace-1", "active_trials") == counter
    assert ConcurrencyCounter.from_dict(counter.to_dict()) == counter
    assert store.scan_recovery("workspace-1") == ()

    _advance(coordination_case, 31)
    recovery_records = store.scan_recovery("workspace-1")
    assert len(recovery_records) == (2 if coordination_case.supports_resources else 1)
    assert all(
        isinstance(record, CoordinationRecoveryRecord) for record in recovery_records
    )
    assert {
        (record.workspace_id, record.sweep_id, record.trial_id)
        for record in recovery_records
        if record.trial_id is not None
    } == {("workspace-1", "sweep-1", "trial-1")}
    expected_resource_recovery = (
        {("workspace-1", "gpu", 2)}
        if coordination_case.supports_resources
        else set()
    )
    assert {
        (record.workspace_id, record.resource_key, record.amount)
        for record in recovery_records
        if record.resource_key is not None
    } == expected_resource_recovery
    assert {record.recovery.kind for record in recovery_records} == {
        RecoveryKind.EXPIRED_LEASE
    }
    assert [
        CoordinationRecoveryRecord.from_dict(record.to_dict())
        for record in recovery_records
    ] == list(recovery_records)


def test_workspace_coordination_contract_rejects_duplicate_identities(
    coordination_case: CoordinationStoreCase,
) -> None:
    store = coordination_case.store
    _seed_workspace(store)

    with pytest.raises(ValueError, match="workspace already exists"):
        store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    with pytest.raises(ValueError, match="sweep already exists"):
        store.create_sweep(
            SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1")
        )
    with pytest.raises(ValueError, match="unknown workspace"):
        store.create_sweep(
            SweepIdentity(sweep_id="orphan-sweep", workspace_id="missing-workspace")
        )


def test_workspace_coordination_contract_fences_leases_and_counters(
    coordination_case: CoordinationStoreCase,
) -> None:
    store = coordination_case.store
    _seed_workspace(store)
    store.record_trial(_trial_reference("trial-1"))

    trial_lease = store.acquire_trial_lease(
        "sweep-1",
        "trial-1",
        owner_id="worker-1",
        lease_ttl_seconds=10,
    )
    with pytest.raises(ValueError, match="active lease"):
        store.acquire_trial_lease(
            "sweep-1",
            "trial-1",
            owner_id="worker-2",
            lease_ttl_seconds=10,
        )
    with pytest.raises(ValueError, match="stale or foreign lease token"):
        store.renew_lease(
            trial_lease.lease.lease_id,
            owner_id="worker-2",
            fencing_token=trial_lease.lease.fencing_token,
            lease_ttl_seconds=10,
        )

    renewed = store.renew_lease(
        trial_lease.lease.lease_id,
        owner_id="worker-1",
        fencing_token=trial_lease.lease.fencing_token,
        lease_ttl_seconds=20,
    )
    assert renewed.revision.sequence > trial_lease.lease.revision.sequence
    released = store.release_lease(
        renewed.lease_id,
        owner_id="worker-1",
        fencing_token=renewed.fencing_token,
    )
    assert released.state is LeaseState.RELEASED

    replacement = store.acquire_trial_lease(
        "sweep-1",
        "trial-1",
        owner_id="worker-3",
        lease_ttl_seconds=1,
    )
    _advance(coordination_case, 2)
    with pytest.raises(ValueError, match="expired"):
        store.fail_lease(
            replacement.lease.lease_id,
            owner_id="worker-3",
            fencing_token=replacement.lease.fencing_token,
            reason=LifecycleReason(code="worker_failed"),
        )

    if coordination_case.supports_resources:
        resource_limit = store.set_resource_limit("workspace-1", "gpu", limit=2)
        assert resource_limit.counter_name == "resource:gpu"
        first_resource = store.acquire_resource_lease(
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
                lease_ttl_seconds=10,
            )
        _advance(coordination_case, 2)
        recovered_resource = store.acquire_resource_lease(
            "workspace-1",
            "gpu",
            owner_id="worker-2",
            amount=1,
            lease_ttl_seconds=10,
        )
        assert recovered_resource.lease.lease_id != first_resource.lease.lease_id
    else:
        with pytest.raises(CoordinationStoreError, match="unsupported_resource"):
            store.acquire_resource_lease(
                "workspace-1",
                "gpu",
                owner_id="worker-1",
                amount=1,
                lease_ttl_seconds=1,
            )
        with pytest.raises(CoordinationStoreError, match="unsupported_resource"):
            store.set_resource_limit("workspace-1", "gpu", limit=1)

    limited = store.set_counter_limit("workspace-1", "active_trials", limit=1)
    assert limited.value == 0
    assert store.increment_counter("workspace-1", "active_trials").value == 1
    with pytest.raises(ValueError, match="counter limit"):
        store.increment_counter("workspace-1", "active_trials")
    assert store.decrement_counter("workspace-1", "active_trials").value == 0
    assert store.increment_counter("workspace-1", "active_trials").value == 1


def test_workspace_coordination_contract_reports_local_safety_limits(
    coordination_case: CoordinationStoreCase,
) -> None:
    diagnostics = coordination_requirement_diagnostics(
        coordination_case.store.capabilities(),
        require_shared_filesystem=True,
        require_remote=True,
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "unsafe_shared_filesystem",
        "unsafe_remote_coordination",
    ]
    assert all(diagnostic.severity.value == "error" for diagnostic in diagnostics)


def _seed_workspace(store: WorkspaceCoordinationStore) -> None:
    workspace_revision = store.create_workspace(
        WorkspaceIdentity(workspace_id="workspace-1", root_uri="file:///workspace")
    )
    assert workspace_revision.sequence == 1
    assert store.check_schema().supported
    store.create_sweep(SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1"))


def _trial_reference(trial_id: str) -> TrialReference:
    return TrialReference(
        trial_id=trial_id,
        sweep_id="sweep-1",
        run_uri=f"file:///runs/{trial_id}",
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=1, token=f"{trial_id}-rev"),
    )


def _advance(coordination_case: CoordinationStoreCase, seconds: int) -> None:
    if coordination_case.clock is not None:
        coordination_case.clock.tick += seconds
        return
    store = coordination_case.store
    if isinstance(store, InMemoryWorkspaceCoordinationStore):
        store.advance_time(seconds)
