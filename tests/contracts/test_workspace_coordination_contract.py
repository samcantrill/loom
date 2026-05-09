"""Contract tests for workspace and sweep coordination stores."""

from loom.pipeline.stores import (
    BackendCapability,
    BackendRevision,
    CapabilityScope,
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    LeaseKind,
    RecoveryKind,
    TrialReference,
    TrialLeaseRecord,
    TrialState,
    WorkspaceCoordinationStore,
    WorkspaceIdentity,
    SweepIdentity,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_in_memory_store_satisfies_workspace_coordination_protocol() -> None:
    store = InMemoryWorkspaceCoordinationStore()

    assert isinstance(store, WorkspaceCoordinationStore)
    assert store.capabilities().supports(
        BackendCapability.CROSS_RUN_COORDINATION,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert not hasattr(store, "transition_stage")


def test_workspace_coordination_contract_records_cross_run_facts_only() -> None:
    store = InMemoryWorkspaceCoordinationStore()

    workspace_revision = store.create_workspace(
        WorkspaceIdentity(workspace_id="workspace-1", root_uri="file:///workspace")
    )
    assert workspace_revision.sequence == 1
    assert store.check_schema().supported

    store.create_sweep(SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1"))
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

    store.advance_time(31)
    recovery_records = store.scan_recovery("workspace-1")
    assert len(recovery_records) == 2
    assert all(
        isinstance(record, CoordinationRecoveryRecord) for record in recovery_records
    )
    assert {
        (record.workspace_id, record.sweep_id, record.trial_id)
        for record in recovery_records
        if record.trial_id is not None
    } == {("workspace-1", "sweep-1", "trial-1")}
    assert {
        (record.workspace_id, record.resource_key, record.amount)
        for record in recovery_records
        if record.resource_key is not None
    } == {("workspace-1", "gpu", 2)}
    assert {record.recovery.kind for record in recovery_records} == {
        RecoveryKind.EXPIRED_LEASE
    }
    assert [
        CoordinationRecoveryRecord.from_dict(record.to_dict())
        for record in recovery_records
    ] == list(recovery_records)
