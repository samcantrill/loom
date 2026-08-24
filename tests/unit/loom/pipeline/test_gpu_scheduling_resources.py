from __future__ import annotations

from typing import cast

from loom.pipeline import parse_resource_request
from loom.pipeline.runtime import (
    scheduling_entry_view,
)
from loom.pipeline.runtime.scheduling_preferences import (
    GpuModelPreferenceScorer,
    OrderedAgentPreferenceScorer,
    PackingPreferenceScorer,
    ResourceAttributePreferenceScorer,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.scheduling import (
    Candidate,
    CapacityAtom,
    ClaimSearchBudget,
    ClaimSearchState,
    ExactQuantity,
    ResourceAvailabilityEnvelope,
    ResourceInventoryEnvelope,
    ResourceResolutionState,
    FifoSchedulingPolicy,
    PreferenceScorer,
    PreferenceSpec,
    SchedulingKernel,
    WorkItem,
)
from loom.serialization import PlainData


def test_production_daemon_registers_each_concrete_preference_scorer() -> None:
    from loom.queue.local_daemon_execution import _production_preference_scorers

    assert {
        name: type(scorer) for name, scorer in _production_preference_scorers().items()
    } == {
        "preferred_agent": OrderedAgentPreferenceScorer,
        "gpu_model": GpuModelPreferenceScorer,
        "resource_attribute": ResourceAttributePreferenceScorer,
        "packing": PackingPreferenceScorer,
    }


def _gpu_candidate(name: str = "machine-B", *, large_model: str = "large") -> Candidate:
    atoms = (
        CapacityAtom("gpu", "gpu-A", ExactQuantity(1), "count", ExactQuantity(1)),
        CapacityAtom("gpu", "gpu-B", ExactQuantity(1), "count", ExactQuantity(1)),
    )
    data: dict[str, PlainData] = {
        "devices": [
            {
                "id": "gpu-A",
                "model": "small",
                "vram_bytes": 12 * 1024**3,
                "allocation_mode": "exclusive",
                "provider": "exclusive",
                "healthy": True,
            },
            {
                "id": "gpu-B",
                "model": large_model,
                "vram_bytes": 80 * 1024**3,
                "allocation_mode": "exclusive",
                "provider": "exclusive",
                "healthy": True,
            },
        ]
    }
    return Candidate(
        name,
        {
            "gpu": ResourceInventoryEnvelope(
                name, "gpu", "inventory-1", data=data, atoms=atoms
            )
        },
        {
            "gpu": ResourceAvailabilityEnvelope(
                name, "gpu", "inventory-1", data=data, atoms=atoms
            )
        },
    )


def _single_gpu_candidate(
    name: str,
    *,
    model: str,
    extra_cpu: int = 0,
) -> Candidate:
    gpu_atom = CapacityAtom(
        "gpu", f"{name}:gpu", ExactQuantity(1), "count", ExactQuantity(1)
    )
    gpu_data: dict[str, PlainData] = {
        "devices": [
            {
                "id": gpu_atom.local_capacity_key,
                "model": model,
                "vram_bytes": 80 * 1024**3,
                "allocation_mode": "exclusive",
                "provider": "exclusive",
                "healthy": True,
            }
        ]
    }
    inventory = {
        "gpu": ResourceInventoryEnvelope(
            name, "gpu", "inventory-1", data=gpu_data, atoms=(gpu_atom,)
        )
    }
    availability = {
        "gpu": ResourceAvailabilityEnvelope(
            name, "gpu", "inventory-1", data=gpu_data, atoms=(gpu_atom,)
        )
    }
    if extra_cpu:
        cpu_atom = CapacityAtom(
            "cpu", f"{name}:cpu", ExactQuantity(extra_cpu), "count", ExactQuantity(1)
        )
        inventory["cpu"] = ResourceInventoryEnvelope(
            name, "cpu", "inventory-1", atoms=(cpu_atom,)
        )
        availability["cpu"] = ResourceAvailabilityEnvelope(
            name, "cpu", "inventory-1", atoms=(cpu_atom,)
        )
    return Candidate(name, inventory, availability)


def _gpu_work(*preferences: PreferenceSpec) -> tuple[GpuResourcePlanner, WorkItem]:
    planner = GpuResourcePlanner()
    request = parse_resource_request(
        {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 1,
                    "unit": "count",
                    "attributes": {"allocation_mode": "exclusive"},
                }
            }
        }
    ).entries["gpu"]
    resolved = planner.resolve_request(scheduling_entry_view(request), None)
    assert resolved.request is not None
    return planner, WorkItem(
        "train", 1, {"gpu": resolved.request}, preferences=preferences
    )


def _selected_candidate(
    scorer: PreferenceScorer,
    preference: PreferenceSpec,
    candidates: tuple[Candidate, Candidate],
) -> str:
    planner, work = _gpu_work(preference)
    descriptor = preference.descriptor
    assert descriptor is not None
    kernel = SchedulingKernel(
        planners={"gpu": planner},
        policy=FifoSchedulingPolicy(),
        preference_scorers={descriptor.kind: scorer},
    )
    decision = kernel.decide(work=(work,), candidates=candidates, as_of=1)
    assert decision.selected is not None
    return decision.selected.candidate_id


def test_gpu_exclusive_request_is_per_device_and_claims_exact_safe_identity() -> None:
    request = parse_resource_request(
        {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 1,
                    "unit": "count",
                    "attributes": {
                        "allocation_mode": "exclusive",
                        "minimum_vram": {"amount": 64, "unit": "GiB"},
                    },
                }
            }
        }
    ).entries["gpu"]
    planner = GpuResourcePlanner()
    resolved = planner.resolve_request(scheduling_entry_view(request), None)
    assert resolved.state is ResourceResolutionState.RESOLVED
    assert resolved.request is not None
    candidate = _gpu_candidate()
    opportunity = planner.validate_opportunity(
        candidate.inventory["gpu"], candidate.availability["gpu"]
    )
    assert opportunity.opportunity is not None
    claims = planner.propose_claims(
        resolved.request, opportunity.opportunity, ClaimSearchBudget(4)
    )
    assert claims.state is ClaimSearchState.COMPLETE
    assert len(claims.claims) == 1
    assert claims.claims[0].atoms[0].local_capacity_key == "gpu-B"
    assert claims.claims[0].provider_data["device_ids"] == ("gpu-B",)


def test_gpu_share_and_fraction_requests_require_explicit_provider_and_exact_values() -> (
    None
):
    share = parse_resource_request(
        {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 10,
                    "unit": "GiB",
                    "attributes": {
                        "allocation_mode": "vram_share",
                        "provider": "enforced",
                    },
                }
            }
        }
    ).entries["gpu"]
    fraction = parse_resource_request(
        {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 2,
                    "unit": "share",
                    "attributes": {
                        "allocation_mode": "provider_fraction",
                        "provider": "enforced",
                        "share_denominator": 4,
                    },
                }
            }
        }
    ).entries["gpu"]
    assert scheduling_entry_view(share).amount == ExactQuantity(10 * 1024**3)
    assert scheduling_entry_view(fraction).amount == ExactQuantity(1, 2)


def test_gpu_model_preference_causally_changes_kernel_selection() -> None:
    scorer = GpuModelPreferenceScorer()
    candidates = (
        _single_gpu_candidate("machine-A", model="small"),
        _single_gpu_candidate("machine-B", model="large"),
    )
    preference = PreferenceSpec(
        "model",
        scorer.descriptor.kind,
        data={"models": ["large", "small"]},
        quality_bands=("preferred", "fallback"),
        descriptor=scorer.descriptor,
    )
    assert _selected_candidate(scorer, preference, candidates) == "machine-B"
    assert (
        _selected_candidate(
            scorer,
            PreferenceSpec(
                "model",
                scorer.descriptor.kind,
                data={"models": ["small", "large"]},
                quality_bands=("preferred", "fallback"),
                descriptor=scorer.descriptor,
            ),
            candidates,
        )
        == "machine-A"
    )


def test_agent_and_resource_attribute_preferences_causally_select() -> None:
    candidates = (
        _single_gpu_candidate("machine-A", model="small"),
        _single_gpu_candidate("machine-B", model="large"),
    )
    agent = OrderedAgentPreferenceScorer()
    for order, expected in (
        (["machine-A", "machine-B"], "machine-A"),
        (["machine-B", "machine-A"], "machine-B"),
    ):
        preference = PreferenceSpec(
            "agent",
            agent.descriptor.kind,
            data={"agents": cast(PlainData, order)},
            quality_bands=("preferred", "fallback"),
            descriptor=agent.descriptor,
        )
        assert _selected_candidate(agent, preference, candidates) == expected

    attribute = ResourceAttributePreferenceScorer()
    for order, expected in (
        (["small", "large"], "machine-A"),
        (["large", "small"], "machine-B"),
    ):
        preference = PreferenceSpec(
            "attribute",
            attribute.descriptor.kind,
            data={
                "resource": "gpu",
                "attribute": "model",
                "values": cast(PlainData, order),
            },
            quality_bands=("preferred", "fallback"),
            descriptor=attribute.descriptor,
        )
        assert _selected_candidate(attribute, preference, candidates) == expected


def test_packing_preference_causally_selects_the_tighter_complete_candidate() -> None:
    scorer = PackingPreferenceScorer()
    preference = PreferenceSpec(
        "packing",
        scorer.descriptor.kind,
        utility_min=-(2**63) + 1,
        utility_max=0,
        descriptor=scorer.descriptor,
    )
    assert (
        _selected_candidate(
            scorer,
            preference,
            (
                _single_gpu_candidate("machine-A", model="same", extra_cpu=1),
                _single_gpu_candidate("machine-B", model="same", extra_cpu=8),
            ),
        )
        == "machine-A"
    )
    assert (
        _selected_candidate(
            scorer,
            preference,
            (
                _single_gpu_candidate("machine-A", model="same", extra_cpu=8),
                _single_gpu_candidate("machine-B", model="same", extra_cpu=1),
            ),
        )
        == "machine-B"
    )


def test_concrete_higher_tier_dominates_model_score_and_candidate_order() -> None:
    agent = OrderedAgentPreferenceScorer()
    model = GpuModelPreferenceScorer()
    preferences = (
        PreferenceSpec(
            "agent",
            agent.descriptor.kind,
            tier=0,
            data={"agents": ["machine-A"]},
            quality_bands=("preferred", "fallback"),
            descriptor=agent.descriptor,
        ),
        PreferenceSpec(
            "model",
            model.descriptor.kind,
            tier=1,
            weight=100,
            data={"models": ["large", "small"]},
            quality_bands=("preferred", "fallback"),
            descriptor=model.descriptor,
        ),
    )
    planner, work = _gpu_work(*preferences)
    candidates = (
        _single_gpu_candidate("machine-A", model="small"),
        _single_gpu_candidate("machine-B", model="large"),
    )
    kernel = SchedulingKernel(
        planners={"gpu": planner},
        policy=FifoSchedulingPolicy(),
        preference_scorers={
            agent.descriptor.kind: agent,
            model.descriptor.kind: model,
        },
    )
    for ordered in (candidates, tuple(reversed(candidates))):
        decision = kernel.decide(work=(work,), candidates=ordered, as_of=1)
        assert decision.selected is not None
        assert decision.selected.candidate_id == "machine-A"


def test_concrete_model_fallback_waits_for_the_durable_deadline() -> None:
    scorer = GpuModelPreferenceScorer()
    preference = PreferenceSpec(
        "model",
        scorer.descriptor.kind,
        fallback_after_seconds=10,
        data={"models": ["unavailable-model"]},
        quality_bands=("preferred", "fallback"),
        fallback_band="fallback",
        descriptor=scorer.descriptor,
    )
    planner, work = _gpu_work(preference)
    kernel = SchedulingKernel(
        planners={"gpu": planner},
        policy=FifoSchedulingPolicy(),
        preference_scorers={scorer.descriptor.kind: scorer},
    )
    candidates = (_single_gpu_candidate("machine-A", model="small"),)

    waiting = kernel.decide(work=(work,), candidates=candidates, as_of=10)
    assert waiting.selected is None

    selected = kernel.decide(work=(work,), candidates=candidates, as_of=11)
    assert selected.selected is not None
    assert selected.selected.candidate_id == "machine-A"
    assert selected.selected.fallback_eligible is True
