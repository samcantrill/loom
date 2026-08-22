from __future__ import annotations

import pytest

from loom.pipeline.execution.managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ManagedAssignment,
    ManagedLocalError,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
)
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)


def _assignment() -> ManagedAssignment:
    return ManagedAssignment(
        assignment_id="assignment-1",
        run_uri="file:///run",
        stage_work_id="work-1",
        stage_name="train",
        attempt=1,
        attempt_id="train-1",
        agent_id="agent",
        session_id="session",
        offer_id="offer",
        claim_id="claim",
    )


def _provider() -> tuple[AtomResourceProvider, ClaimCommand]:
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "implementation", "configured"
    )
    contract = ResourceClaimContractDescriptor("cpu", 1, "configured")
    atom = CapacityAtom("cpu", "cpu-0", ExactQuantity(2), "count", ExactQuantity(1))
    provider = AtomResourceProvider(descriptor, (atom,))
    claim = ResourceClaim("cpu", contract, (atom,), 1)
    return provider, ClaimCommand(_assignment(), "prepare-1", claim)


def test_provider_is_idempotent_and_never_claims_process_enforcement() -> None:
    provider, command = _provider()

    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    assert provider.observe()[0].amount == ExactQuantity(2)


def test_journal_requires_grant_and_durable_start_intent_before_one_launch(
    tmp_path,
) -> None:
    journal = SQLiteAgentJournal(tmp_path / "agent" / "journal.sqlite")
    assignment = _assignment()
    assert (
        journal.persist_request(assignment, {"request": "durable"})
        is AssignmentState.REQUEST_DURABLE
    )
    provider, command = _provider()
    assert (
        journal.prepare_composite(assignment, (command,), {"cpu": provider})
        is AssignmentState.PREPARED
    )
    assert journal.accept(assignment.assignment_id) is AssignmentState.ACCEPTED
    assert journal.grant(assignment.assignment_id, "fence-1") is AssignmentState.GRANTED

    calls = 0

    def launch() -> str:
        nonlocal calls
        calls += 1
        return "process-1"

    assert journal.start_once(assignment.assignment_id, launch) == "process-1"
    assert journal.start_once(assignment.assignment_id, launch) == "process-1"
    assert calls == 1
    assert (
        journal.record_result(assignment.assignment_id, {"status": "succeeded"})
        is AssignmentState.RESULT_DURABLE
    )
    assert journal.release(assignment.assignment_id) is AssignmentState.RELEASED


def test_journal_rejects_event_gap_and_conflicting_replay(tmp_path) -> None:
    journal = SQLiteAgentJournal(tmp_path / "journal.sqlite")
    assignment = _assignment()
    journal.persist_request(assignment, {"request": "durable"})

    with pytest.raises(ManagedLocalError, match="gap"):
        journal.record_event(assignment.assignment_id, 2, "event-2", {"kind": "start"})
    assert (
        journal.record_event(assignment.assignment_id, 1, "event-1", {"kind": "start"})
        == 1
    )
    assert (
        journal.record_event(assignment.assignment_id, 1, "event-1", {"kind": "start"})
        == 1
    )
    with pytest.raises(ManagedLocalError, match="conflicts"):
        journal.record_event(assignment.assignment_id, 1, "event-1", {"kind": "result"})
    assert journal.acknowledge(assignment.assignment_id, 1) == 1


def test_coordinator_reserves_atoms_and_run_slot_in_one_transaction(tmp_path) -> None:
    provider, command = _provider()
    del provider
    coordinator = SQLiteCoordinatorAssignments(
        tmp_path / "coordinator.sqlite", command.claim.atoms
    )
    assert (
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt={"policy_epoch": "one", "reason_codes": ["selected"]},
        )
        == "reserved"
    )
    competing = ManagedAssignment(
        assignment_id="assignment-2",
        run_uri=command.assignment.run_uri,
        stage_work_id="work-2",
        stage_name="evaluate",
        attempt=1,
        attempt_id="evaluate-1",
        agent_id="agent",
        session_id="session",
        offer_id="offer",
        claim_id="claim-2",
    )
    with pytest.raises(ManagedLocalError, match="limit"):
        coordinator.reserve(
            competing,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt={"policy_epoch": "one", "reason_codes": ["selected"]},
        )
    assert (
        coordinator.advance(
            command.assignment.assignment_id, expected="reserved", next_state="terminal"
        )
        == "terminal"
    )
    assert (
        coordinator.reserve(
            competing,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt={"policy_epoch": "one", "reason_codes": ["selected"]},
        )
        == "reserved"
    )
