"""Construct managed offer snapshots and the exact decision persisted for dispatch."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._managed_contracts import ManagedAssignment, ManagedOfferSnapshot

if TYPE_CHECKING:
    from loom.pipeline.orchestration import StageWorkRecord
    from loom.scheduling import (
        Candidate,
        CandidateEvaluation,
        CapacityAtom,
        ResourceClaim,
        ResourcePlanner,
        SchedulingComponentDescriptor,
        SchedulingDecision,
    )
    from loom.serialization import PlainData
    from ._managed_contracts import ObserveResult
    from ._remote_stage_execution import ResidentProfileDescriptor
    from .agent_sessions import AgentOffer
    from .submitted_execution import SubmittedContainerCapability


@dataclass(frozen=True)
class _LocalCapacityObservation:
    candidate: Candidate
    observations: Mapping[str, ObserveResult]
    descriptors: Mapping[str, SchedulingComponentDescriptor]
    sampled_at: float


@dataclass(frozen=True, slots=True)
class _RemoteCandidateTarget:
    agent_id: str
    session_id: str
    offer_id: str
    availability_revision: str
    scheduling_availability_revision: str
    inventory_revision: str
    offer: AgentOffer
    profile: ResidentProfileDescriptor | SubmittedContainerCapability
    availability_atoms: tuple[CapacityAtom, ...]
    reflected_claim_ids: tuple[str, ...]
    expires_ns: int = 0


@dataclass(frozen=True, slots=True)
class ManagedDispatch:
    assignment: ManagedAssignment
    claims: tuple[ResourceClaim, ...]
    receipt: dict[str, PlainData]
    providers: tuple[SchedulingComponentDescriptor, ...]


def local_offer_snapshot(
    record: StageWorkRecord,
    observation: _LocalCapacityObservation,
    planners: Mapping[str, ResourcePlanner],
    *,
    agent_id: str,
    session_id: str,
) -> ManagedOfferSnapshot:
    offer_id = f"offer-{record.stage_work_id}-{record.projection_revision}"
    observations = observation.observations
    availability_revision = (
        "local-"
        + hashlib.sha256(
            "\0".join(observations[kind].availability_revision for kind in sorted(observations)).encode()
        ).hexdigest()
    )
    provider_descriptors = observation.descriptors
    return ManagedOfferSnapshot(
        agent_id=agent_id,
        session_id=session_id,
        # Slow preparation can outlive a peer's claim/release without
        # changing this stage's projection. Bind the offer identity to
        # the observed capacity so retry can publish fresh evidence.
        offer_revision=offer_id + "-" + availability_revision,
        snapshot_revision=session_id,
        inventory_revision=f"inventory-{session_id}",
        availability_revision=availability_revision,
        component_descriptors=tuple(planners[kind].descriptor for kind in sorted(provider_descriptors)),
        provider_descriptors=tuple(provider_descriptors[kind] for kind in sorted(provider_descriptors)),
        atoms=tuple(atom for kind in sorted(observations) for atom in observations[kind].atoms),
        reflected_claim_ids=tuple(
            sorted(
                {live_claim_id for result in observations.values() for live_claim_id in result.live_claim_ids}
            )
        ),
    )


def remote_offer_snapshot(
    target: _RemoteCandidateTarget, planners: Mapping[str, ResourcePlanner]
) -> ManagedOfferSnapshot:
    provider_descriptors = {descriptor.kind: descriptor for descriptor in target.offer.provider_descriptors}
    return ManagedOfferSnapshot(
        agent_id=target.agent_id,
        session_id=target.session_id,
        offer_revision=target.offer_id,
        snapshot_revision=target.scheduling_availability_revision,
        inventory_revision=target.inventory_revision,
        availability_revision=target.scheduling_availability_revision,
        component_descriptors=tuple(planners[kind].descriptor for kind in sorted(provider_descriptors)),
        provider_descriptors=tuple(provider_descriptors[kind] for kind in sorted(provider_descriptors)),
        atoms=target.availability_atoms,
        reflected_claim_ids=target.reflected_claim_ids,
    )


def managed_dispatch(
    admission_id: str,
    record: StageWorkRecord,
    decision: SchedulingDecision,
    selected: CandidateEvaluation,
    planners: Mapping[str, ResourcePlanner],
    snapshot: ManagedOfferSnapshot,
    *,
    offer_id: str,
    as_of: str,
) -> ManagedDispatch:
    """The persisted offer ID and the original UTF-8 byte sequence also identify retries."""
    identity = "\0".join((admission_id, record.stage_work_id, offer_id, str(record.projection_revision)))
    assignment_id = "assignment-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    assignment = ManagedAssignment(
        assignment_id=assignment_id,
        run_uri=record.run_uri,
        stage_work_id=record.stage_work_id,
        stage_name=record.stage_name,
        attempt=record.attempt,
        attempt_id=record.attempt_id,
        agent_id=snapshot.agent_id,
        session_id=snapshot.session_id,
        offer_id=offer_id,
        claim_id=f"claim-{assignment_id}",
    )
    claims = selected.claims
    providers = {descriptor.kind: descriptor for descriptor in snapshot.provider_descriptors}
    kinds = sorted(claim.resource_kind for claim in claims)
    decision_receipt: dict[str, PlainData] = {
        "policy_epoch": decision.component_epoch,
        "policy_descriptor": decision.policy_descriptor.to_dict(),
        "stage_work_id": record.stage_work_id,
        "candidate_id": assignment.agent_id,
        "stage_work_revision": record.projection_revision,
        "snapshot_revision": snapshot.snapshot_revision,
        "offer_revision": offer_id,
        "score_summary": {"preference_vector": list(selected.preference_vector)},
        "fallback_eligible": selected.fallback_eligible,
        "as_of": as_of,
        "reason_codes": ["selected"],
        "component_descriptors": [planners[kind].descriptor.to_dict() for kind in kinds],
        "provider_descriptors": [providers[kind].to_dict() for kind in kinds],
        "claim_contract_descriptors": [
            descriptor.to_dict()
            for descriptor in sorted(
                {claim.contract for claim in claims},
                key=lambda item: item.key,
            )
        ],
    }
    return ManagedDispatch(
        assignment, claims, decision_receipt, tuple(providers[claim.resource_kind] for claim in claims)
    )
