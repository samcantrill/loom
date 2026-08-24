from __future__ import annotations

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
    PreferenceSpec,
    SchedulingKernel,
    WorkItem,
)
from loom.serialization import PlainData


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


def test_concrete_gpu_preferences_only_contribute_evidence_through_kernel() -> None:
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
    scorer = GpuModelPreferenceScorer()
    preferences = (
        PreferenceSpec(
            "model",
            scorer.descriptor.kind,
            data={"models": ["large", "small"]},
            quality_bands=("preferred", "fallback"),
            descriptor=scorer.descriptor,
        ),
    )
    work = WorkItem("train", 1, {"gpu": resolved.request}, preferences=preferences)
    alternate = _gpu_candidate("machine-B")
    first = _gpu_candidate("machine-A", large_model="small")
    kernel = SchedulingKernel(
        planners={"gpu": planner},
        policy=FifoSchedulingPolicy(),
        preference_scorers={scorer.descriptor.kind: scorer},
    )
    decision = kernel.decide(work=(work,), candidates=(first, alternate), as_of=1)
    assert decision.selected is not None
    assert decision.selected.candidate_id == "machine-B"
    # The other scorer types share the same protocol but not the kernel algebra.
    assert OrderedAgentPreferenceScorer().descriptor.kind == "preferred_agent"
    assert ResourceAttributePreferenceScorer().descriptor.kind == "resource_attribute"
    assert PackingPreferenceScorer().descriptor.kind == "packing"
