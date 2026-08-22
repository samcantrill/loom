"""The scheduling public boundary stays intentional and dependency-light."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent


def test_scheduling_import_and_protocol_annotations_are_dependency_light() -> None:
    script = dedent(
        """
        import sys
        from typing import get_type_hints

        import loom.scheduling as scheduling

        assert set(scheduling.__all__) == {
            "AttributeConstraintEvaluator", "Candidate", "CandidateEvaluation",
            "CapacityAtom", "ClaimSearchBudget", "ClaimSearchResult",
            "ClaimSearchState", "ClaimValidationResult", "ClaimValidationState",
            "ComponentRegistry", "EligibilityState", "ExactQuantity",
            "FifoSchedulingPolicy", "HardConstraintEvaluator",
            "HardConstraintResult", "HardConstraintSpec", "HardEvaluationState",
            "MandatoryEligibility", "MAX_COMPONENT_DATA_BYTES",
            "NeutralPreferenceScorer", "OpportunityState",
            "OpportunityValidationResult", "PolicyContext", "PolicyDecision",
            "PolicyDecisionState", "PreferenceEvaluationState",
            "PreferenceResult", "PreferenceScore", "PreferenceScorer",
            "PreferenceSpec", "ResolvedResourceRequest",
            "ResourceAvailabilityEnvelope", "ResourceClaim",
            "ResourceClaimContractDescriptor", "ResourceInventoryEnvelope",
            "ResourcePlanner", "ResourceRequestResolution",
            "ResourceResolutionState", "SCHEDULING_DATA_VERSION",
            "SchedulingComponentDescriptor", "SchedulingDecision",
            "SchedulingError", "SchedulingExplanation", "SchedulingKernel",
            "SchedulingLimits", "SchedulingPolicy", "SchedulingSnapshot",
            "TargetConstraintEvaluator", "ValidatedResourceEntryView",
            "ValidatedResourceOpportunity", "WorkEvaluation", "WorkItem",
            "WorkOrderKey", "WorkSearchState",
        }
        get_type_hints(scheduling.ResourcePlanner.resolve_request)
        get_type_hints(scheduling.HardConstraintEvaluator.evaluate)
        get_type_hints(scheduling.PreferenceScorer.evaluate)
        get_type_hints(scheduling.SchedulingPolicy.select)
        assert not any(
            name == "loom.pipeline" or name.startswith("loom.pipeline.")
            for name in sys.modules
        )
        assert not hasattr(__import__("loom"), "SchedulingKernel")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
