"""Contract tests for workspace and sweep coordination stores."""

from loom.pipeline.stores import (
    BackendCapability,
    BackendRevision,
    CapabilityScope,
    ConcurrencyCounter,
    LeaseKind,
    TrialReference,
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
    assert trial_lease.kind is LeaseKind.TRIAL

    resource = store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="sweep-worker",
        amount=2,
        lease_ttl_seconds=30,
    )
    assert resource.amount == 2
    assert resource.lease.kind is LeaseKind.RESOURCE

    counter = store.increment_counter("workspace-1", "active_trials")
    assert isinstance(counter, ConcurrencyCounter)
    assert store.read_counter("workspace-1", "active_trials") == counter
    assert store.scan_recovery("workspace-1") == ()
