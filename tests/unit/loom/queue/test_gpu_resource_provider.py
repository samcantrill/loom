from __future__ import annotations

from datetime import datetime, timezone

import pytest

from loom.queue._managed_local import (
    ClaimCommand,
    ClaimOutcome,
    GpuResourceProvider,
    ManagedAssignment,
    ObserveRequest,
    ResourceAvailabilityStatus,
    SQLiteAgentJournal,
    AssignmentState,
)
from loom.queue.gpu.occupancy import (
    GpuOccupancyMonitor,
    GpuProcessObservation,
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


def test_gpu_provider_filters_cached_observations_and_forces_preparation_probe(tmp_path) -> None:
    planner = GpuResourcePlanner()
    atoms = tuple(
        CapacityAtom("gpu", key, ExactQuantity(1), "count", ExactQuantity(1))
        for key in ("safe-a", "safe-b")
    )
    clock = [0.0]
    observer = _FakeOccupancyObserver(
        ("GPU-a", "GPU-b"),
        (
            GpuProcessObservation("GPU-a", True, True, "external_process_detected"),
            GpuProcessObservation("GPU-b", True, False, "available"),
        ),
    )
    monitor = GpuOccupancyMonitor(
        ("GPU-a", "GPU-b"),
        observer=observer,  # type: ignore[arg-type]
        monotonic_clock=lambda: clock[0],
        utc_clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    provider = GpuResourceProvider(
        planner.claim_contracts,
        atoms,
        bindings={"safe-a": "GPU-a", "safe-b": "GPU-b"},
        occupancy_monitor=monitor,
    )
    request = ObserveRequest("agent", "session", "observe")

    initial = provider.observe(request)
    assert initial.atoms == ()
    assert [item.reason_code for item in initial.resource_status] == [
        "observation_unavailable",
        "observation_unavailable",
    ]
    assert observer.calls == 0

    provider.refresh_occupancy()
    busy = provider.observe(request)
    assert [item.local_capacity_key for item in busy.atoms] == ["safe-b"]
    assert [item.reason_code for item in busy.resource_status] == [
        "external_process_detected",
        "available",
    ]

    clock[0] = 16.0
    stale = provider.observe(request)
    assert stale.atoms == ()
    assert [item.reason_code for item in stale.resource_status] == [
        "observation_stale",
        "observation_stale",
    ]

    observer.observations = (
        GpuProcessObservation("GPU-a", True, False, "available"),
        GpuProcessObservation("GPU-b", True, False, "available"),
    )
    provider.refresh_occupancy(force=True)
    recovered = provider.observe(request)
    assert [item.local_capacity_key for item in recovered.atoms] == ["safe-a", "safe-b"]
    assert recovered.availability_revision != busy.availability_revision

    observer.observations = (
        GpuProcessObservation("GPU-a", True, True, "external_process_detected"),
        GpuProcessObservation("GPU-b", True, False, "available"),
    )
    command = _claim_command(provider, planner, atoms[0])
    result = provider.prepare(command)
    assert result.outcome is ClaimOutcome.DECLINED
    assert result.detail == "external_process_detected"
    assert observer.calls == 3

    journal_path = tmp_path / "journal.sqlite"
    journal = SQLiteAgentJournal(journal_path)
    assignment = command.assignment
    assert isinstance(assignment, ManagedAssignment)
    journal.persist_request(assignment, {"request": "durable"})
    assert journal.prepare_composite(assignment, (command,), {"gpu": provider}) is AssignmentState.DECLINED
    assert journal.read_decline_reason(assignment.assignment_id) == "external_process_detected"
    journal.release_declined(assignment.assignment_id, "after-decline")
    probe_count = observer.calls
    observer.observations = tuple(
        GpuProcessObservation(uuid, True, False, "available") for uuid in ("GPU-a", "GPU-b")
    )
    reopened = SQLiteAgentJournal(journal_path)
    assert reopened.prepare_composite(assignment, (command,), {"gpu": provider}) is AssignmentState.DECLINED
    assert reopened.read_decline_reason(assignment.assignment_id) == "external_process_detected"
    assert reopened.read_result(assignment.assignment_id) is None
    assert observer.calls == probe_count


def test_resource_availability_status_excludes_timestamp_from_decision() -> None:
    status = ResourceAvailabilityStatus(
        "gpu", "safe-a", False, "observation_unavailable", "2026-01-01T00:00:00Z"
    )

    assert ResourceAvailabilityStatus.from_dict(status.to_dict()) == status
    assert status.decision_dict() == {
        "resource_kind": "gpu",
        "local_capacity_key": "safe-a",
        "available": False,
        "reason_code": "observation_unavailable",
    }


def _claim_command(
    provider: GpuResourceProvider, planner: GpuResourcePlanner, atom: CapacityAtom
) -> ClaimCommand:
    return ClaimCommand(
        ManagedAssignment(
            "assignment-observed",
            "run",
            "work",
            "stage",
            1,
            "attempt",
            "agent",
            "session",
            "offer",
            "claim",
        ),
        "prepare-observed",
        ResourceClaim("gpu", planner.claim_contracts[0], (atom,), 1),
        provider.descriptor,
    )


class _FakeOccupancyObserver:
    def __init__(
        self,
        selected_uuids: tuple[str, ...],
        observations: tuple[GpuProcessObservation, ...],
    ) -> None:
        self.selected_uuids = selected_uuids
        self.observations = observations
        self.calls = 0

    def observe(self) -> dict[str, GpuProcessObservation]:
        self.calls += 1
        return {item.uuid: item for item in self.observations}
