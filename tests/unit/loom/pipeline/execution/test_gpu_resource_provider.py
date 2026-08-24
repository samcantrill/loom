from __future__ import annotations

import pytest

from loom.pipeline.execution.managed_local import (
    ClaimCommand,
    ClaimOutcome,
    GpuResourceProvider,
    ManagedAssignment,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.execution.managed_local import ManagedLocalError
from loom.scheduling import CapacityAtom, ExactQuantity, ResourceClaim


def test_gpu_provider_uses_only_the_journalled_claim_for_private_binding() -> None:
    planner = GpuResourcePlanner()
    atom = CapacityAtom(
        "gpu", "safe-gpu-id", ExactQuantity(1), "count", ExactQuantity(1)
    )
    provider = GpuResourceProvider(
        planner.claim_contracts,
        (atom,),
        bindings={"safe-gpu-id": "private-device-binding"},
    )
    claim = ResourceClaim(
        "gpu",
        planner.claim_contracts[0],
        (atom,),
        1,
        {
            "allocation_mode": "exclusive",
            "provider": "exclusive",
            "device_ids": ["safe-gpu-id"],
            "snapshot_revision": "r1",
        },
    )
    assignment = ManagedAssignment(
        "assignment-1",
        "run-1",
        "work-1",
        "train",
        1,
        "attempt-1",
        "agent-1",
        "session-1",
        "offer-1",
        "claim-1",
    )
    command = ClaimCommand(assignment, "prepare-1", claim, provider.descriptor)

    assert provider.descriptor != planner.descriptor
    assert "private-device-binding" not in str(provider.descriptor.to_dict())

    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert provider.binding_for_claim(command) == ("private-device-binding",)
    assert provider.worker_environment(command) == {
        "CUDA_VISIBLE_DEVICES": "private-device-binding"
    }
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    try:
        provider.worker_environment(command)
    except ManagedLocalError:
        pass
    else:  # pragma: no cover - documents the active-claim launch boundary.
        raise AssertionError("released GPU claim supplied a worker binding")


def test_gpu_provider_rejects_retained_claim_after_private_mapping_drift() -> None:
    planner = GpuResourcePlanner()
    atom = CapacityAtom(
        "gpu", "safe-gpu-id", ExactQuantity(1), "count", ExactQuantity(1)
    )
    previous = GpuResourceProvider(
        planner.claim_contracts,
        (atom,),
        bindings={"safe-gpu-id": "binding-old"},
    )
    replacement = GpuResourceProvider(
        planner.claim_contracts,
        (atom,),
        bindings={"safe-gpu-id": "binding-new"},
    )
    claim = ResourceClaim(
        "gpu",
        planner.claim_contracts[0],
        (atom,),
        1,
        {
            "allocation_mode": "exclusive",
            "provider": "exclusive",
            "device_ids": ["safe-gpu-id"],
            "snapshot_revision": "r1",
        },
    )
    assignment = ManagedAssignment(
        "assignment-1",
        "run-1",
        "work-1",
        "train",
        1,
        "attempt-1",
        "agent-1",
        "session-1",
        "offer-1",
        "claim-1",
    )
    retained = ClaimCommand(
        assignment, "prepare-1", claim, previous.descriptor
    )

    assert previous.descriptor != replacement.descriptor
    with pytest.raises(ManagedLocalError, match="provider descriptor conflicts"):
        replacement.restore_capacity_holding(retained)
