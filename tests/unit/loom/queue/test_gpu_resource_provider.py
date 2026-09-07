from __future__ import annotations

import pytest

from loom.queue._managed_local import (
    ClaimCommand,
    ClaimOutcome,
    GpuResourceProvider,
    ManagedAssignment,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.queue._managed_local import ManagedLocalError
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
    retained = ClaimCommand(assignment, "prepare-1", claim, previous.descriptor)

    assert previous.descriptor != replacement.descriptor
    with pytest.raises(ManagedLocalError, match="provider descriptor conflicts"):
        replacement.restore_capacity_holding(retained)


def test_eight_selected_gpus_yield_disjoint_claims_and_the_ninth_waits() -> None:
    planner = GpuResourcePlanner()
    atoms = tuple(
        CapacityAtom("gpu", f"GPU-{index}", ExactQuantity(1), "count", ExactQuantity(1))
        for index in range(8)
    )
    provider = GpuResourceProvider(
        planner.claim_contracts,
        atoms,
        bindings={atom.local_capacity_key: atom.local_capacity_key for atom in atoms},
    )
    commands = tuple(
        ClaimCommand(
            ManagedAssignment(
                f"assignment-{index}",
                "run-1",
                f"work-{index}",
                "train",
                1,
                f"attempt-{index}",
                "agent-1",
                "session-1",
                "offer-1",
                f"claim-{index}",
            ),
            f"prepare-{index}",
            ResourceClaim("gpu", planner.claim_contracts[0], (atom,), 1),
            provider.descriptor,
        )
        for index, atom in enumerate(atoms)
    )

    for command in commands:
        assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
        assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert {
        provider.worker_environment(command)["CUDA_VISIBLE_DEVICES"]
        for command in commands
    } == {f"GPU-{index}" for index in range(8)}

    ninth = ClaimCommand(
        ManagedAssignment(
            "assignment-9", "run-1", "work-9", "train", 1, "attempt-9", "agent-1", "session-1", "offer-1", "claim-9"
        ),
        "prepare-9",
        ResourceClaim("gpu", planner.claim_contracts[0], (atoms[0],), 1),
        provider.descriptor,
    )
    assert provider.prepare(ninth).outcome is ClaimOutcome.DECLINED

    for command in commands:
        assert provider.release(command).outcome is ClaimOutcome.RELEASED
