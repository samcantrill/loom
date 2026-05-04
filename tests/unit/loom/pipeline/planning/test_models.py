"""Unit tests for planning model serialization."""

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    PlanSerializationError,
    PlanSelectors,
    ResumeCheck,
    ResumeOptions,
    StageFingerprintPayload,
    StageFingerprintRecord,
    StagePlan,
)


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build/data",
        uri="file:///tmp/data.json",
        artifact_type="json",
        codec_key="json.v1",
        checksum="sha256:" + "1" * 64,
    )


def _fingerprint() -> StageFingerprintRecord:
    payload = StageFingerprintPayload(
        schema_version=2,
        policy_name="loom.stage.semantic",
        policy_version=2,
        stage_name="build",
        factory_target="project.Build",
        factory_init={},
        stage_config={"limit": 1},
        fingerprint_fields={},
        declared_inputs={},
        bound_inputs={},
        declared_outputs={
            "data": {
                "artifact_type": "json",
                "codec_key": "json.v1",
                "schema_version": None,
                "metadata": {},
            }
        },
        python_version="3.12.0",
        loom_version="0.1.0",
        git={},
        dependencies={},
        extra={},
    )
    return StageFingerprintRecord(
        schema_version=2,
        algorithm="sha256",
        policy_name="loom.stage.semantic",
        policy_version=2,
        fingerprint="sha256:" + "2" * 64,
        payload=payload,
        inputs_summary={"stage_name": "build"},
    )


def test_execution_plan_round_trips_through_plain_data() -> None:
    fingerprint = _fingerprint()
    reason = PlanReason(
        PlanReasonCode.FINGERPRINT_MATCH, "fingerprint matched", stage_name="build"
    )
    resume = ResumeCheck(
        stage_name="build",
        action=PlanAction.REUSE,
        status="SUCCEEDED",
        attempt=1,
        prior_fingerprint=fingerprint,
        current_fingerprint=fingerprint,
        inputs={},
        outputs={"data": _artifact_ref()},
        reasons=(reason,),
    )
    stage_plan = StagePlan(
        stage_name="build",
        action=PlanAction.REUSE,
        base_action=PlanAction.REUSE,
        fingerprint_status=FingerprintStatus.COMPUTED,
        fingerprint=fingerprint,
        resume_check=resume,
        reasons=(reason,),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={"data": _artifact_ref()},
        declared_outputs={
            "data": {
                "artifact_type": "json",
                "codec_key": "json.v1",
                "schema_version": None,
                "metadata": {},
            }
        },
        upstream_stages=(),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )
    plan = ExecutionPlan(
        schema_version=1,
        run_id="run1",
        pipeline_name="demo",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0", loom_version="0.1.0"
        ),
        stage_order=("build",),
        stage_plans=(stage_plan,),
        reasons=(),
        summary={"RUN": 0, "REUSE": 1, "SKIP": 0, "STALE": 0, "BLOCKED": 0},
    )

    assert ExecutionPlan.from_dict(plan.to_dict()).to_dict() == plan.to_dict()


def test_model_parsers_reject_unknown_fields_and_invalid_enums() -> None:
    with pytest.raises(PlanSerializationError, match="unknown"):
        PlanReason.from_dict(
            {"code": "FINGERPRINT_MATCH", "message": "ok", "extra": True}
        )

    with pytest.raises(Exception, match="invalid"):
        StagePlan.from_dict(
            {
                "stage_name": "build",
                "action": "NOPE",
                "base_action": "RUN",
                "fingerprint_status": "COMPUTED",
                "fingerprint": None,
                "resume_check": None,
                "reasons": [],
                "bound_inputs": {},
                "pending_inputs": [],
                "reusable_outputs": {},
                "declared_outputs": {},
                "upstream_stages": [],
                "downstream_stages": [],
                "selected_by": [],
                "invalidated_by": [],
            }
        )
