"""Package-level API tests for planning."""

import subprocess
import sys

import pytest


pytestmark = pytest.mark.package


def test_pipeline_planning_public_exports_are_phase_scoped() -> None:
    import loom
    import loom.pipeline
    import loom.pipeline.planning as planning

    assert planning.__all__ == [
        "DEFAULT_FINGERPRINT_ALGORITHM",
        "PLAN_SCHEMA_VERSION",
        "STAGE_FINGERPRINT_POLICY_NAME",
        "STAGE_FINGERPRINT_POLICY_VERSION",
        "STAGE_FINGERPRINT_SCHEMA_VERSION",
        "BoundInput",
        "AttemptReadiness",
        "ExecutionPlan",
        "FingerprintContext",
        "FingerprintStatus",
        "PendingInput",
        "PlanAction",
        "PlanPersistenceError",
        "PlanReason",
        "PlanReasonCode",
        "PlanSerializationError",
        "PlanSelectors",
        "PlanningError",
        "PlanningValidationError",
        "ResumeCheck",
        "ResumeOptions",
        "ReadinessAttemptView",
        "RetryAuthorization",
        "ResumeStateError",
        "SelectorValidationError",
        "StageFingerprintError",
        "StageFingerprintPayload",
        "StageFingerprintRecord",
        "StagePlan",
        "build_stage_fingerprint",
        "explain_plan",
        "PLAN_EXPLANATION_KIND",
        "PLAN_EXPLANATION_SCHEMA_VERSION",
        "PlanExplanation",
        "StageExplanation",
        "plan_pipeline",
        "evaluate_attempt_readiness",
    ]
    assert "plan_pipeline" not in loom.__all__
    assert "plan_pipeline" not in loom.pipeline.__all__


@pytest.mark.parametrize(
    "forbidden",
    [
        "weave",
        "loom.cli",
        "loom.pipeline.execution",
        "loom.pipeline.executors",
    ],
)
def test_pipeline_planning_import_does_not_import_forbidden_modules(
    forbidden: str,
) -> None:
    script = (
        "import sys\n"
        "import loom.pipeline.planning\n"
        f"if {forbidden!r} in sys.modules:\n"
        f"    raise SystemExit('{forbidden} was imported through loom.pipeline.planning')\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
