"""Public lifecycle contract for Stage 29 local resource providers."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from loom.queue import (
    AgentResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    CpuResourceProvider,
    MemoryResourceProvider,
    ObserveRequest,
)
from loom.queue._managed_local import ManagedAssignment
from loom.scheduling import CapacityAtom, ExactQuantity, ResourceClaim
from loom.testing import check_agent_resource_provider_contract


pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    ("resource_kind", "factory"),
    [
        ("cpu", CpuResourceProvider),
        ("memory", MemoryResourceProvider),
    ],
)
def test_builtin_provider_lifecycle_is_exact_and_idempotent(
    resource_kind: str,
    factory: Callable[[tuple[CapacityAtom, ...]], AgentResourceProvider],
) -> None:
    capacity = CapacityAtom(
        resource_kind,
        f"{resource_kind}-0",
        ExactQuantity(2),
        "count" if resource_kind == "cpu" else "bytes",
        ExactQuantity(1),
    )
    provider = factory((capacity,))
    assignment = ManagedAssignment(
        assignment_id="assignment-1",
        run_uri="file:///run",
        stage_work_id="stage-work-1",
        stage_name="build",
        attempt=1,
        attempt_id="build-1",
        agent_id="agent-1",
        session_id="session-1",
        offer_id="offer-1",
        claim_id="claim-1",
    )
    claim = ResourceClaim(
        resource_kind,
        provider.claim_contracts[0],
        (
            CapacityAtom(
                resource_kind,
                f"{resource_kind}-0",
                ExactQuantity(1),
                capacity.unit,
                ExactQuantity(1),
            ),
        ),
        1,
    )
    command = ClaimCommand(assignment, "prepare-1", claim, provider.descriptor)

    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.reconcile(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert provider.reconcile(command).outcome is ClaimOutcome.ACTIVE
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    observed = provider.observe(ObserveRequest("agent-1", "session-1", "observe-1"))
    assert observed.atoms == (capacity,)
    assert observed.live_claim_ids == ()


def test_provider_declines_known_overcommit_without_claiming_os_enforcement() -> None:
    capacity = CapacityAtom("cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1))
    provider = CpuResourceProvider((capacity,))
    assignment = ManagedAssignment(
        assignment_id="assignment-1",
        run_uri="file:///run",
        stage_work_id="stage-work-1",
        stage_name="build",
        attempt=1,
        attempt_id="build-1",
        agent_id="agent-1",
        session_id="session-1",
        offer_id="offer-1",
        claim_id="claim-1",
    )
    claim = ResourceClaim(
        "cpu",
        provider.claim_contracts[0],
        (CapacityAtom("cpu", "cpu-0", ExactQuantity(2), "count", ExactQuantity(1)),),
        1,
    )

    result = provider.prepare(
        ClaimCommand(assignment, "prepare-1", claim, provider.descriptor)
    )

    assert result.outcome is ClaimOutcome.DECLINED
    assert "configured capacity" in (result.detail or "")
    assert "enforcement" not in provider.descriptor.to_dict()


def test_public_provider_check_exercises_a_complete_lifecycle() -> None:
    capacity = CapacityAtom("cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1))
    provider = CpuResourceProvider((capacity,))
    assignment = ManagedAssignment(
        "assignment-check",
        "file:///run",
        "work-check",
        "build",
        1,
        "build-1",
        "agent-1",
        "session-1",
        "offer-1",
        "claim-check",
    )
    claim = ResourceClaim(
        "cpu",
        provider.claim_contracts[0],
        (CapacityAtom("cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1)),),
        1,
    )
    report = check_agent_resource_provider_contract(
        provider,
        sample_claim=ClaimCommand(
            assignment, "check-prepare", claim, provider.descriptor
        ),
    )

    assert report.ok
    assert {finding.code for finding in report.findings} >= {
        "agent_resource_provider.prepare",
        "agent_resource_provider.activate",
        "agent_resource_provider.release",
    }
