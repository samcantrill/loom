from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from loom.queue._managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    ManagedAssignment,
    ManagedLocalError,
    ManagedOfferSnapshot,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
    ObserveRequest,
    _compose_agent_resource_providers,
)
from loom.pipeline.orchestration import (
    ExecutionRequirement,
    SchedulingProjectionState,
    SQLiteStageWorkStore,
    StageWorkRecord,
    stage_work_identity,
)
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime.placement import (
    StagePlacementPolicy,
    resolve_stage_placement,
)
from loom.pipeline.stores import BackendRevision
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData


def _assignment() -> ManagedAssignment:
    stage_work_id = stage_work_identity("admission-1", "train", "train-1", "ready-1")
    return ManagedAssignment(
        assignment_id="assignment-1",
        run_uri="file:///run",
        stage_work_id=stage_work_id,
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
    provider = AtomResourceProvider(descriptor, (contract,), (atom,))
    claim = ResourceClaim("cpu", contract, (atom,), 1)
    return provider, ClaimCommand(_assignment(), "prepare-1", claim, descriptor)


def _seed_stage_work(path, assignment: ManagedAssignment) -> None:
    SQLiteStageWorkStore(path).create_or_refresh(
        StageWorkRecord(
            stage_work_id=assignment.stage_work_id,
            admission_id="admission-1",
            run_uri=assignment.run_uri,
            stage_name=assignment.stage_name,
            attempt=assignment.attempt,
            attempt_id=assignment.attempt_id,
            readiness_generation="ready-1",
            ready_at=1,
            ready_order=1,
            plan_fingerprint="plan-1",
            authority_revision=BackendRevision(1, "revision-1"),
            bound_inputs={},
            upstream_commits={},
            placement=resolve_stage_placement(
                authored=ResourceRequest(),
                runtime=None,
                policy=StagePlacementPolicy(),
                planners={},
            ),
            execution_requirement=ExecutionRequirement(
                "test-project", "test-environment", "test-executor"
            ),
        )
    )


def _decision_receipt(
    assignment: ManagedAssignment, claim: ResourceClaim
) -> dict[str, PlainData]:
    return {
        "policy_epoch": "one",
        "policy_descriptor": SchedulingComponentDescriptor(
            "fifo", 1, "1", "test-fifo", "configured"
        ).to_dict(),
        "stage_work_id": assignment.stage_work_id,
        "candidate_id": assignment.agent_id,
        "stage_work_revision": 1,
        "snapshot_revision": "snapshot-1",
        "offer_revision": assignment.offer_id,
        "score_summary": {"tiers": [0]},
        "fallback_eligible": False,
        "as_of": "2020-01-01T00:00:00Z",
        "reason_codes": ["selected"],
        "component_descriptors": [
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "implementation", "configured"
            ).to_dict()
        ],
        "provider_descriptors": [
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "implementation", "configured"
            ).to_dict()
        ],
        "claim_contract_descriptors": [claim.contract.to_dict()],
    }


def _offer(
    assignment: ManagedAssignment,
    atoms: tuple[CapacityAtom, ...],
    *,
    reflected_claim_ids: tuple[str, ...] = (),
) -> ManagedOfferSnapshot:
    return ManagedOfferSnapshot(
        agent_id=assignment.agent_id,
        session_id=assignment.session_id,
        offer_revision=assignment.offer_id,
        snapshot_revision="snapshot-1",
        inventory_revision="inventory-1",
        availability_revision=f"availability-{assignment.offer_id}",
        component_descriptors=(
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "implementation", "configured"
            ),
        ),
        provider_descriptors=(
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "implementation", "configured"
            ),
        ),
        atoms=atoms,
        reflected_claim_ids=reflected_claim_ids,
    )


def test_provider_is_idempotent_and_never_claims_process_enforcement() -> None:
    provider, command = _provider()

    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    observed = provider.observe(ObserveRequest("agent", "session", "observe-1"))
    assert observed.atoms[0].amount == ExactQuantity(2)


def test_same_kind_provider_group_splits_and_releases_aggregate_claim() -> None:
    contract = ResourceClaimContractDescriptor("cpu", 1, "configured")
    atoms = (
        CapacityAtom("cpu", "cpu-a", ExactQuantity(1), "count", ExactQuantity(1)),
        CapacityAtom("cpu", "cpu-b", ExactQuantity(1), "count", ExactQuantity(1)),
    )
    members = tuple(
        AtomResourceProvider(
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "implementation", f"configured-{index}"
            ),
            (contract,),
            (atom,),
        )
        for index, atom in enumerate(atoms)
    )
    provider = _compose_agent_resource_providers(members)["cpu"]
    aggregate = CapacityAtom(
        "cpu", "agent:cpu", ExactQuantity(2), "count", ExactQuantity(1)
    )
    claim = ResourceClaim("cpu", contract, (aggregate,), 1)
    command = ClaimCommand(
        _assignment(), "prepare-composite", claim, provider.descriptor
    )

    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    held = provider.observe(ObserveRequest("agent", "session", "observe-held"))
    assert held.atoms == ()
    assert held.live_claim_ids == ("claim",)
    assert provider.release(command).outcome is ClaimOutcome.RELEASED
    released = provider.observe(ObserveRequest("agent", "session", "observe-released"))
    assert released.atoms == atoms
    assert released.live_claim_ids == ()


class _RaisingAtomProvider(AtomResourceProvider):
    def prepare(self, command: ClaimCommand) -> ClaimResult:
        _ = command
        raise TimeoutError("provider response was lost")


@pytest.mark.parametrize(
    ("second_provider_kind", "expected"),
    [
        ("declined", AssignmentState.DECLINED),
        ("unknown", AssignmentState.PREPARE_UNKNOWN),
    ],
)
def test_composite_prepare_compensates_exact_prior_claims(
    tmp_path, second_provider_kind: str, expected: AssignmentState
) -> None:
    assignment = _assignment()
    cpu_provider, cpu_command = _provider()
    memory_contract = ResourceClaimContractDescriptor("memory", 1, "configured")
    memory_descriptor = SchedulingComponentDescriptor(
        "memory", 1, "1", "implementation", "configured"
    )
    memory_atom = CapacityAtom(
        "memory", "memory-0", ExactQuantity(1), "bytes", ExactQuantity(1)
    )
    provider_type = (
        AtomResourceProvider
        if second_provider_kind == "declined"
        else _RaisingAtomProvider
    )
    memory_provider = provider_type(memory_descriptor, (memory_contract,), ())
    memory_claim = ResourceClaim("memory", memory_contract, (memory_atom,), 1)
    memory_command = ClaimCommand(
        assignment, "prepare-memory", memory_claim, memory_descriptor
    )
    journal = SQLiteAgentJournal(tmp_path / "journal.sqlite")
    journal.persist_request(assignment, {"request": "durable"})

    state = journal.prepare_composite(
        assignment,
        (cpu_command, memory_command),
        {"cpu": cpu_provider, "memory": memory_provider},
    )

    assert state is expected
    observed = cpu_provider.observe(ObserveRequest("agent", "session", "observe-1"))
    assert observed.live_claim_ids == ()
    assert observed.atoms == cpu_command.claim.atoms


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
    assert journal.read_grant_fence(assignment.assignment_id) == "fence-1"
    assert (
        journal.activate_composite(
            assignment.assignment_id, (command,), {"cpu": provider}
        )
        is AssignmentState.ACTIVE
    )
    assert journal.assignment_claim_commands(assignment.assignment_id) == (command,)

    calls = 0

    def launch() -> str:
        nonlocal calls
        calls += 1
        return "process-1"

    assert (
        journal.start_once(assignment.assignment_id, "process-1", launch) == "process-1"
    )
    assert (
        journal.start_once(assignment.assignment_id, "process-1", launch) == "process-1"
    )
    assert calls == 1
    assert (
        journal.record_result(assignment.assignment_id, {"status": "succeeded"})
        is AssignmentState.RESULT_DURABLE
    )
    assert (
        journal.acknowledge_terminal(assignment.assignment_id)
        is AssignmentState.TERMINAL_ACKNOWLEDGED
    )
    assert (
        journal.mark_providers_released(assignment.assignment_id)
        is AssignmentState.PROVIDERS_RELEASED
    )
    assert (
        journal.publish_availability(assignment.assignment_id, "availability-1")
        is AssignmentState.RELEASED
    )
    assert (
        journal.read_availability_revision(assignment.assignment_id) == "availability-1"
    )
    assert journal.assignment_claim_commands(assignment.assignment_id) == (command,)


def test_pregrant_cancellation_releases_exact_claim_before_decline(
    tmp_path,
) -> None:
    journal = SQLiteAgentJournal(tmp_path / "journal.sqlite")
    assignment = _assignment()
    provider, command = _provider()
    journal.persist_request(assignment, {"request": "durable"})
    assert (
        journal.prepare_composite(assignment, (command,), {"cpu": provider})
        is AssignmentState.PREPARED
    )
    assert journal.accept(assignment.assignment_id) is AssignmentState.ACCEPTED

    assert (
        journal.abort_pregrant(
            assignment.assignment_id,
            (command,),
            {"cpu": provider},
        )
        is AssignmentState.DECLINED
    )
    observed = provider.observe(ObserveRequest("agent", "session", "observe-cancel"))
    assert observed.live_claim_ids == ()
    assert (
        journal.release_declined(assignment.assignment_id, "availability-cancelled")
        is AssignmentState.RELEASED
    )


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
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, command.assignment)
    coordinator = SQLiteCoordinatorAssignments(path, command.claim.atoms)
    coordinator.publish_offer(_offer(command.assignment, command.claim.atoms))
    assert (
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(command.assignment, command.claim),
        )
        == "reserved"
    )
    assert {
        descriptor.kind for descriptor in coordinator.retained_scheduling_descriptors()
    } == {"cpu", "fifo"}
    assert (
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(command.assignment, command.claim),
        )
        == "reserved"
    )
    changed_receipt = _decision_receipt(command.assignment, command.claim)
    changed_receipt["reason_codes"] = ["changed"]
    with pytest.raises(ManagedLocalError, match="replay conflicts"):
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=changed_receipt,
        )
    changed_atom = replace(command.claim.atoms[0], amount=ExactQuantity(1))
    changed_claim = replace(command.claim, atoms=(changed_atom,))
    with pytest.raises(ManagedLocalError, match="replay conflicts"):
        coordinator.reserve(
            command.assignment,
            (changed_claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(command.assignment, changed_claim),
        )
    competing = ManagedAssignment(
        assignment_id="assignment-2",
        run_uri=command.assignment.run_uri,
        stage_work_id=stage_work_identity(
            "admission-1", "evaluate", "evaluate-1", "ready-1"
        ),
        stage_name="evaluate",
        attempt=1,
        attempt_id="evaluate-1",
        agent_id="agent",
        session_id="session",
        offer_id="offer-2",
        claim_id="claim-2",
    )
    _seed_stage_work(path, competing)
    coordinator.publish_offer(_offer(competing, command.claim.atoms))
    with pytest.raises(ManagedLocalError, match="limit"):
        coordinator.reserve(
            competing,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(competing, command.claim),
        )
    assert (
        coordinator.advance(
            command.assignment.assignment_id, expected="reserved", next_state="bound"
        )
        == "bound"
    )
    assert (
        coordinator.advance(
            command.assignment.assignment_id, expected="bound", next_state="terminal"
        )
        == "terminal"
    )
    assert (
        coordinator.advance(
            command.assignment.assignment_id,
            expected="terminal",
            next_state="logical_released",
        )
        == "logical_released"
    )
    with pytest.raises(ManagedLocalError, match="capacity atom"):
        coordinator.reserve(
            competing,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(competing, command.claim),
        )
    assert (
        coordinator.advance(
            command.assignment.assignment_id,
            expected="logical_released",
            next_state="released",
        )
        == "released"
    )
    assert (
        coordinator.reserve(
            competing,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(competing, command.claim),
        )
        == "reserved"
    )


def test_concurrent_reservations_cannot_consume_the_final_run_slot(tmp_path) -> None:
    _provider_value, command = _provider()
    capacity = replace(command.claim.atoms[0], amount=ExactQuantity(4))
    path = tmp_path / "coordinator.sqlite"
    assignments = (
        command.assignment,
        replace(
            command.assignment,
            assignment_id="assignment-2",
            stage_work_id=stage_work_identity(
                "admission-1", "evaluate", "evaluate-1", "ready-1"
            ),
            stage_name="evaluate",
            attempt_id="evaluate-1",
            claim_id="claim-2",
        ),
    )
    for assignment in assignments:
        _seed_stage_work(path, assignment)
    coordinator = SQLiteCoordinatorAssignments(path, (capacity,))
    coordinator.publish_offer(_offer(assignments[0], (capacity,)))
    barrier = Barrier(2)

    def reserve(assignment: ManagedAssignment) -> str:
        barrier.wait(timeout=10)
        try:
            return coordinator.reserve(
                assignment,
                (command.claim,),
                max_parallel_stages=1,
                decision_receipt=_decision_receipt(assignment, command.claim),
            )
        except ManagedLocalError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(reserve, assignments))

    assert outcomes.count("reserved") == 1
    assert sum("limit" in outcome for outcome in outcomes) == 1
    assert coordinator.run_active_assignment_count(command.assignment.run_uri) == 1


def test_offer_revision_is_one_use_until_fresh_net_availability(tmp_path) -> None:
    _provider_value, command = _provider()
    capacity = command.claim.atoms[0]
    claim_atom = replace(capacity, amount=ExactQuantity(1))
    claim = replace(command.claim, atoms=(claim_atom,))
    first = command.assignment
    second = replace(
        first,
        assignment_id="assignment-2",
        stage_work_id=stage_work_identity(
            "admission-1", "evaluate", "evaluate-1", "ready-1"
        ),
        stage_name="evaluate",
        attempt_id="evaluate-1",
        claim_id="claim-2",
    )
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, first)
    _seed_stage_work(path, second)
    coordinator = SQLiteCoordinatorAssignments(path, (capacity,))
    coordinator.publish_offer(_offer(first, (capacity,)))

    assert (
        coordinator.reserve(
            first,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(first, claim),
        )
        == "reserved"
    )
    coordinator.advance(first.assignment_id, expected="reserved", next_state="bound")
    coordinator.advance(first.assignment_id, expected="bound", next_state="accepted")
    with pytest.raises(ManagedLocalError, match="availability revision"):
        coordinator.reserve(
            second,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(second, claim),
        )

    remaining = replace(capacity, amount=ExactQuantity(1))
    not_fresh = replace(second, offer_id="offer-not-fresh")
    with pytest.raises(ManagedLocalError, match="fresh availability"):
        coordinator.publish_offer(
            replace(
                _offer(not_fresh, (remaining,)),
                availability_revision=f"availability-{first.offer_id}",
            )
        )

    inconsistent = replace(second, offer_id="offer-inconsistent")
    coordinator.publish_offer(
        _offer(
            inconsistent,
            (capacity,),
            reflected_claim_ids=(first.claim_id,),
        )
    )
    with pytest.raises(ManagedLocalError, match="reflected logical claims"):
        coordinator.reserve(
            inconsistent,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(inconsistent, claim),
        )

    fresh = replace(second, offer_id="offer-fresh")
    coordinator.publish_offer(
        _offer(fresh, (remaining,), reflected_claim_ids=(first.claim_id,))
    )
    assert (
        coordinator.reserve(
            fresh,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(fresh, claim),
        )
        == "reserved"
    )


def test_replacement_offer_withholds_old_session_claim_without_inheriting_it(
    tmp_path,
) -> None:
    _provider_value, command = _provider()
    capacity = command.claim.atoms[0]
    claim = replace(
        command.claim,
        atoms=(replace(capacity, amount=ExactQuantity(1)),),
    )
    old = command.assignment
    successor = replace(
        old,
        assignment_id="assignment-successor",
        stage_work_id=stage_work_identity(
            "admission-1", "evaluate", "evaluate-1", "ready-1"
        ),
        stage_name="evaluate",
        attempt_id="evaluate-1",
        session_id="session-successor",
        offer_id="offer-successor",
        claim_id="claim-successor",
    )
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, old)
    _seed_stage_work(path, successor)
    coordinator = SQLiteCoordinatorAssignments(path, (capacity,))
    coordinator.publish_offer(_offer(old, (capacity,)))
    coordinator.reserve(
        old,
        (claim,),
        max_parallel_stages=2,
        decision_receipt=_decision_receipt(old, claim),
    )
    coordinator.advance(old.assignment_id, expected="reserved", next_state="bound")
    coordinator.advance(old.assignment_id, expected="bound", next_state="accepted")

    withheld = coordinator.withhold_claims(
        agent_id=old.agent_id,
        atoms=(capacity,),
        claim_ids=(old.claim_id,),
    )
    assert len(withheld) == 1
    assert withheld[0].amount == ExactQuantity(1)
    coordinator.publish_offer(
        _offer(successor, withheld, reflected_claim_ids=(old.claim_id,))
    )
    assert (
        coordinator.reserve(
            successor,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(successor, claim),
        )
        == "reserved"
    )
    facts = coordinator.session_assignment_facts(session_id=old.session_id)
    assert len(facts) == 1
    assert facts[0]["assignment_id"] == old.assignment_id
    assert facts[0]["state"] == "accepted"
    coordinator.release_contained(old.assignment_id)
    assert (
        coordinator.session_assignment_facts(session_id=old.session_id)[0]["state"]
        == "released"
    )
    with pytest.raises(ManagedLocalError, match="not retained and live"):
        coordinator.withhold_claims(
            agent_id=old.agent_id,
            atoms=(capacity,),
            claim_ids=("missing-claim",),
        )


def test_unaccepted_release_can_reopen_the_same_availability_offer(tmp_path) -> None:
    _provider_value, command = _provider()
    capacity = command.claim.atoms[0]
    claim = replace(
        command.claim,
        atoms=(replace(capacity, amount=ExactQuantity(1)),),
    )
    first = command.assignment
    second = replace(
        first,
        assignment_id="assignment-2",
        stage_work_id=stage_work_identity(
            "admission-1", "evaluate", "evaluate-1", "ready-1"
        ),
        stage_name="evaluate",
        attempt_id="evaluate-1",
        claim_id="claim-2",
    )
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, first)
    _seed_stage_work(path, second)
    coordinator = SQLiteCoordinatorAssignments(path, (capacity,))
    coordinator.publish_offer(_offer(first, (capacity,)))
    coordinator.reserve(
        first,
        (claim,),
        max_parallel_stages=2,
        decision_receipt=_decision_receipt(first, claim),
    )
    coordinator.advance(first.assignment_id, expected="reserved", next_state="bound")

    assert (
        coordinator.release_unaccepted(first.assignment_id, reopen_offer=True)
        == "released"
    )
    reopened = next(
        record
        for record in SQLiteStageWorkStore(path).list_stage_work()
        if record.stage_work_id == first.stage_work_id
    )
    assert reopened.scheduling_state is SchedulingProjectionState.READY
    assert reopened.scheduling_diagnostics == {}
    assert reopened.projection_revision == 2
    assert (
        coordinator.reserve(
            second,
            (claim,),
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(second, claim),
        )
        == "reserved"
    )


def test_start_outcome_unknown_never_invokes_launcher_again(tmp_path) -> None:
    journal = SQLiteAgentJournal(tmp_path / "journal.sqlite")
    assignment = _assignment()
    provider, command = _provider()
    journal.persist_request(assignment, {"request": "durable"})
    journal.prepare_composite(assignment, (command,), {"cpu": provider})
    journal.accept(assignment.assignment_id)
    journal.grant(assignment.assignment_id, "fence-1")
    journal.activate_composite(assignment.assignment_id, (command,), {"cpu": provider})
    calls = 0

    def ambiguous_launch() -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("spawn response was lost")

    with pytest.raises(TimeoutError):
        journal.start_once(assignment.assignment_id, "process-1", ambiguous_launch)
    assert journal.read_state(assignment.assignment_id) is AssignmentState.START_UNKNOWN
    with pytest.raises(ManagedLocalError, match="cannot be invoked again"):
        journal.start_once(assignment.assignment_id, "process-1", ambiguous_launch)
    assert (
        journal.confirm_supervised_start(assignment.assignment_id, "process-1")
        is AssignmentState.PROCESS_STARTED
    )
    assert (
        journal.start_once(assignment.assignment_id, "process-1", ambiguous_launch)
        == "process-1"
    )
    assert calls == 1


def test_decision_receipt_is_bounded_and_rejects_secret_material(tmp_path) -> None:
    _provider_value, command = _provider()
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, command.assignment)
    coordinator = SQLiteCoordinatorAssignments(path, command.claim.atoms)
    secret_receipt = _decision_receipt(command.assignment, command.claim)
    secret_receipt["password"] = "must-not-persist"
    with pytest.raises(ManagedLocalError, match="secret"):
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=secret_receipt,
        )
    oversized_receipt = _decision_receipt(command.assignment, command.claim)
    oversized_receipt["explanation"] = "x" * 20_000
    with pytest.raises(ManagedLocalError, match="bounded"):
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=oversized_receipt,
        )


def test_coordinator_rejects_stale_stage_work_and_wrong_candidate(tmp_path) -> None:
    _provider_value, command = _provider()
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, command.assignment)
    store = SQLiteStageWorkStore(path)
    store.create_or_refresh(store.list_stage_work()[0])
    coordinator = SQLiteCoordinatorAssignments(path, command.claim.atoms)

    with pytest.raises(ManagedLocalError, match="revision changed"):
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(command.assignment, command.claim),
        )

    receipt = _decision_receipt(command.assignment, command.claim)
    receipt["stage_work_revision"] = 2
    receipt["candidate_id"] = "other-agent"
    with pytest.raises(ManagedLocalError, match="candidate"):
        coordinator.reserve(
            command.assignment,
            (command.claim,),
            max_parallel_stages=1,
            decision_receipt=receipt,
        )


def test_event_replay_after_commit_can_be_acknowledged_exactly_once(tmp_path) -> None:
    _provider_value, command = _provider()
    path = tmp_path / "coordinator.sqlite"
    _seed_stage_work(path, command.assignment)
    coordinator = SQLiteCoordinatorAssignments(path, command.claim.atoms)
    coordinator.publish_offer(_offer(command.assignment, command.claim.atoms))
    coordinator.reserve(
        command.assignment,
        (command.claim,),
        max_parallel_stages=1,
        decision_receipt=_decision_receipt(command.assignment, command.claim),
    )
    journal = SQLiteAgentJournal(tmp_path / "journal.sqlite")
    journal.persist_request(command.assignment, {"request": "durable"})
    payload = {"kind": "request_and_inputs_durable"}
    sequence = journal.append_event(
        command.assignment.assignment_id,
        "assignment-1:request_and_inputs_durable",
        payload,
    )

    assert (
        coordinator.record_event(
            command.assignment.assignment_id,
            sequence,
            "assignment-1:request_and_inputs_durable",
            payload,
        )
        == 1
    )
    # A lost response is replayed with the same durable event identity.
    assert (
        coordinator.record_event(
            command.assignment.assignment_id,
            sequence,
            "assignment-1:request_and_inputs_durable",
            payload,
        )
        == 1
    )
    assert journal.acknowledge(command.assignment.assignment_id, sequence) == 1
