"""Unit tests for planning model serialization."""

from dataclasses import replace
from typing import Any, cast

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
    PlanningValidationError,
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
    return StageFingerprintRecord.create(
        algorithm="sha256",
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
        run_uri="run1",
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

    for version in (2, 0, -1, True, 1.0, "1"):
        with pytest.raises(PlanningValidationError, match="schema_version"):
            replace(plan, schema_version=version)
        with pytest.raises(PlanningValidationError, match="schema_version"):
            ExecutionPlan.from_dict({**plan.to_dict(), "schema_version": version})


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


def test_fingerprint_record_is_derived_verified_and_serialized_independently() -> None:
    config: Any = {"nested": {"labels": ["raw", "processed"]}}
    summary: Any = {"input_artifacts": {"data": {"labels": ["raw"]}}}
    payload = StageFingerprintPayload(
        schema_version=2,
        policy_name="loom.stage.semantic",
        policy_version=2,
        stage_name="build",
        factory_target="project.Build",
        factory_init={},
        stage_config=config,
        fingerprint_fields={},
        declared_inputs={},
        bound_inputs={},
        declared_outputs={},
        python_version="3.12.0",
        loom_version="0.1.0",
        git={},
        dependencies={},
        extra={},
    )
    record = StageFingerprintRecord.create(
        payload=payload, algorithm="sha256", inputs_summary=summary
    )

    config["nested"]["labels"].append("changed")
    summary["input_artifacts"]["data"]["labels"].append("changed")
    serialized = cast(Any, record.to_dict())
    serialized["payload"]["stage_config"]["nested"]["labels"].append("snapshot")
    serialized["inputs_summary"]["input_artifacts"]["data"]["labels"].append("snapshot")

    assert record.payload.stage_config == {"nested": {"labels": ("raw", "processed")}}
    assert record.inputs_summary == {"input_artifacts": {"data": {"labels": ("raw",)}}}
    assert cast(Any, record.to_dict())["payload"]["stage_config"] == {
        "nested": {"labels": ["raw", "processed"]}
    }
    assert record.to_dict()["inputs_summary"] == {
        "input_artifacts": {"data": {"labels": ["raw"]}}
    }

    corrupted = cast(Any, record.to_dict())
    corrupted["fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(PlanSerializationError, match="does not match its payload"):
        StageFingerprintRecord.from_dict(corrupted)
    with pytest.raises(PlanSerializationError, match="does not match its payload"):
        StageFingerprintRecord(
            schema_version=record.schema_version,
            algorithm=record.algorithm,
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            fingerprint="sha256:" + "0" * 64,
            payload=record.payload,
            inputs_summary=record.inputs_summary,
        )

    mismatched_policy = cast(Any, record.to_dict())
    mismatched_policy["policy_name"] = "different-policy"
    with pytest.raises(
        PlanSerializationError,
        match="policy_name does not match its payload",
    ):
        StageFingerprintRecord.from_dict(mismatched_policy)


@pytest.mark.parametrize("version", [1, 3, True, "2"])
def test_fingerprint_requires_current_schema_at_construction_and_decode(version: Any) -> None:
    record = _fingerprint()
    with pytest.raises(PlanSerializationError, match="schema_version"):
        replace(record, schema_version=version)
    with pytest.raises(PlanSerializationError, match="schema_version"):
        replace(record.payload, schema_version=version)
    with pytest.raises(PlanningValidationError, match="schema_version"):
        StageFingerprintRecord.from_dict({**record.to_dict(), "schema_version": version})
    with pytest.raises(PlanningValidationError, match="schema_version"):
        StageFingerprintPayload.from_dict({**record.payload.to_dict(), "schema_version": version})


@pytest.mark.parametrize("field", ["factory_target", "factory_init", "fingerprint_fields"])
def test_fingerprint_requires_all_current_factory_fields(field: str) -> None:
    payload = _fingerprint().payload.to_dict()
    del payload[field]
    with pytest.raises(PlanSerializationError, match=field):
        StageFingerprintPayload.from_dict(payload)


def test_fingerprint_rejects_retired_target_alias() -> None:
    payload = _fingerprint().payload.to_dict()
    payload["target_path"] = payload.pop("factory_target")
    with pytest.raises(PlanSerializationError, match="unknown.*target_path"):
        StageFingerprintPayload.from_dict(payload)
