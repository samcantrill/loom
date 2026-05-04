"""Unit tests for planning policy helper extraction."""

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.graph import resolve_input_bindings
from loom.pipeline.planning import (
    BoundInput,
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    PlanSelectors,
    PendingInput,
    ResumeCheck,
    ResumeOptions,
    StagePlan,
)
from loom.pipeline.planning.actions import decide_stage_action
from loom.pipeline.planning.explanations import (
    PLAN_EXPLANATION_KIND,
    PLAN_EXPLANATION_SCHEMA_VERSION,
    PlanExplanation,
    explain_plan,
)
from loom.pipeline.planning.fingerprints import build_stage_fingerprint
from loom.pipeline.planning.invalidation import (
    InputInvalidationResult,
    evaluate_input_invalidation,
    unique_reasons,
)
from loom.pipeline.planning.resume import DirectResumeResult


def _spec_with_input() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "policy-demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {"data": {"artifact_type": "json"}},
                },
                {
                    "name": "report",
                    "factory": {"_target_": "project.Report"},
                    "inputs": {"data": "build.data"},
                    "outputs": {"text": {"artifact_type": "text"}},
                },
            ],
        },
    )


def _spec_with_dependency() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "policy-dependency-demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {"artifact": {"artifact_type": "json"}},
                },
                {
                    "name": "validate",
                    "factory": {"_target_": "project.Validate"},
                    "depends_on": ["build"],
                    "outputs": {"ok": {"artifact_type": "json"}},
                },
            ],
        },
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build-data",
        uri="file://build/data",
        artifact_type="json",
        codec_key="json.v1",
    )


def _reason(code: PlanReasonCode) -> PlanReason:
    return PlanReason(code=code, message=f"{code.value}", stage_name="report")


def _pending(
    input_name: str,
    source_stage: str,
    source_output: str,
    reason: PlanReason,
) -> PendingInput:
    return PendingInput(
        input_name=input_name,
        source_stage=source_stage,
        source_output=source_output,
        reason=reason,
    )


def _reusable_source_plan(spec: PipelineSpec) -> StagePlan:
    build = spec.get_stage("build")
    return StagePlan(
        stage_name="build",
        action=PlanAction.REUSE,
        base_action=PlanAction.REUSE,
        fingerprint_status=FingerprintStatus.COMPUTED,
        fingerprint=build_stage_fingerprint(build, bound_inputs={}),
        resume_check=None,
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={"data": _artifact()},
        declared_outputs={},
        upstream_stages=(),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )


def _blocked_source_plan(*, base_action: PlanAction) -> StagePlan:
    return StagePlan(
        stage_name="build",
        action=PlanAction.BLOCKED,
        base_action=base_action,
        fingerprint_status=FingerprintStatus.PENDING_INPUTS,
        fingerprint=None,
        resume_check=ResumeCheck(
            stage_name="build",
            action=PlanAction.BLOCKED,
            status="blocked",
            attempt=1,
            prior_fingerprint=None,
            current_fingerprint=None,
            inputs={},
            outputs={},
            reasons=(),
        ),
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={},
        declared_outputs={},
        upstream_stages=(),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )


def _stale_source_plan() -> StagePlan:
    return StagePlan(
        stage_name="build",
        action=PlanAction.STALE,
        base_action=PlanAction.STALE,
        fingerprint_status=FingerprintStatus.PENDING_INPUTS,
        fingerprint=None,
        resume_check=None,
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={},
        declared_outputs={},
        upstream_stages=(),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )


def _direct_result(
    *,
    base_action: PlanAction,
    final_action: PlanAction,
    outputs: Mapping[str, ArtifactRef] | None = None,
) -> DirectResumeResult:
    return DirectResumeResult(
        base_action=base_action,
        final_action=final_action,
        check=ResumeCheck(
            stage_name="report",
            action=final_action,
            status="ok",
            attempt=1,
            prior_fingerprint=None,
            current_fingerprint=None,
            inputs={},
            outputs=dict(outputs or {}),
            reasons=(_reason(PlanReasonCode.FINGERPRINT_MATCH),),
        ),
    )


def test_evaluate_input_invalidation_binds_reusable_upstream_output() -> None:
    spec = _spec_with_input()
    bindings = resolve_input_bindings(spec)
    result = evaluate_input_invalidation(
        stage=spec.get_stage("report"),
        bindings=bindings["report"],
        prior_plans={"build": _reusable_source_plan(spec)},
    )
    bound_input = result.bound_inputs["data"]
    assert bound_input == BoundInput(
        input_name="data",
        source_stage="build",
        source_output="data",
        artifact_ref=_artifact(),
    )
    assert result.pending_inputs == ()
    assert result.invalidated_by == ()


def test_evaluate_input_invalidation_marks_unavailable_upstream_input() -> None:
    spec = _spec_with_input()
    bindings = resolve_input_bindings(spec)
    result = evaluate_input_invalidation(
        stage=spec.get_stage("report"),
        bindings=bindings["report"],
        prior_plans={"build": _blocked_source_plan(base_action=PlanAction.STALE)},
    )
    assert result.pending_inputs[0].reason.code == PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT
    reason_codes = {reason.code for reason in result.invalidated_by}
    assert PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT in reason_codes


def test_evaluate_input_invalidation_marks_dependency_stale() -> None:
    spec = _spec_with_dependency()
    bindings = resolve_input_bindings(spec)
    result = evaluate_input_invalidation(
        stage=spec.get_stage("validate"),
        bindings=bindings["validate"],
        prior_plans={"build": _stale_source_plan()},
    )
    assert any(
        reason.code == PlanReasonCode.UPSTREAM_STALE
        for reason in result.invalidated_by
    )
    assert result.bound_inputs == {}
    assert result.pending_inputs == ()


def test_unique_reasons_deduplicates_identical_reason_records_preserving_order() -> None:
    reason = _reason(PlanReasonCode.UPSTREAM_SKIPPED)
    duplicate = PlanReason(
        code=PlanReasonCode.UPSTREAM_SKIPPED,
        message=reason.message,
        stage_name=reason.stage_name,
    )
    unique = unique_reasons(
        (
            reason,
            _reason(PlanReasonCode.UPSTREAM_WILL_RUN),
            duplicate,
            _reason(PlanReasonCode.UPSTREAM_BLOCKED),
        )
    )
    assert unique == (
        reason,
        _reason(PlanReasonCode.UPSTREAM_WILL_RUN),
        _reason(PlanReasonCode.UPSTREAM_BLOCKED),
    )


def test_decide_stage_action_blocks_when_ineligible_with_blocking_inputs() -> None:
    result = decide_stage_action(
        selector_reasons=(_reason(PlanReasonCode.FROM_STAGE_SELECTED),),
        eligible_to_run=False,
        force=False,
        invalidation=InputInvalidationResult(
            bound_inputs={},
            pending_inputs=(
                _pending(
                    "data",
                    "build",
                    "data",
                    _reason(PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT),
                ),
            ),
            invalidated_by=(_reason(PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT),),
        ),
    )
    assert result.action == PlanAction.BLOCKED
    assert result.base_action == PlanAction.BLOCKED
    assert result.fingerprint_status == FingerprintStatus.PENDING_INPUTS
    assert result.fingerprint is None
    assert result.resume_check is None


def test_decide_stage_action_runs_with_pending_inputs_when_eligible() -> None:
    result = decide_stage_action(
        selector_reasons=(),
        eligible_to_run=True,
        force=False,
        invalidation=InputInvalidationResult(
            bound_inputs={},
            pending_inputs=(
                _pending(
                    "data",
                    "build",
                    "data",
                    _reason(PlanReasonCode.PENDING_UPSTREAM_INPUT),
                ),
            ),
            invalidated_by=(_reason(PlanReasonCode.PENDING_UPSTREAM_INPUT),),
        ),
    )
    assert result.action == PlanAction.RUN
    assert result.base_action == PlanAction.RUN
    assert result.fingerprint_status == FingerprintStatus.PENDING_INPUTS
    assert result.reusable_outputs == {}


def test_decide_stage_action_keeps_reuse_base_action_when_forced() -> None:
    result = decide_stage_action(
        selector_reasons=(_reason(PlanReasonCode.FROM_STAGE_SELECTED),),
        eligible_to_run=True,
        force=True,
        invalidation=InputInvalidationResult(
            bound_inputs={},
            pending_inputs=(),
            invalidated_by=(),
        ),
        direct_result=_direct_result(
            base_action=PlanAction.REUSE,
            final_action=PlanAction.REUSE,
            outputs={"data": _artifact()},
        ),
        fingerprint=build_stage_fingerprint(
            _spec_with_input().get_stage("build"),
            bound_inputs={},
        ),
    )
    assert result.action == PlanAction.RUN
    assert result.base_action == PlanAction.REUSE
    assert result.reusable_outputs == {}


def test_explain_plan_derives_plain_data_and_round_trips() -> None:
    plan = ExecutionPlan(
        schema_version=1,
        run_id="run1",
        pipeline_name="policy-demo",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(),
        stage_order=("build", "report"),
        stage_plans=(
            StagePlan(
                stage_name="build",
                action=PlanAction.SKIP,
                base_action=PlanAction.SKIP,
                fingerprint_status=FingerprintStatus.PENDING_INPUTS,
                fingerprint=None,
                resume_check=None,
                reasons=(_reason(PlanReasonCode.SKIPPED_BY_SELECTOR),),
                bound_inputs={},
                pending_inputs=(),
                reusable_outputs={},
                declared_outputs={},
                upstream_stages=(),
                downstream_stages=("report",),
                selected_by=(PlanReasonCode.SKIPPED_BY_SELECTOR,),
                invalidated_by=(),
            ),
            StagePlan(
                stage_name="report",
                action=PlanAction.BLOCKED,
                base_action=PlanAction.BLOCKED,
                fingerprint_status=FingerprintStatus.PENDING_INPUTS,
                fingerprint=None,
                resume_check=None,
                reasons=(_reason(PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT),),
                bound_inputs={},
                pending_inputs=(
                    _pending(
                        "data",
                        "build",
                        "data",
                        _reason(PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT),
                    ),
                ),
                reusable_outputs={},
                declared_outputs={},
                upstream_stages=("build",),
                downstream_stages=(),
                selected_by=(),
                invalidated_by=(_reason(PlanReasonCode.UPSTREAM_BLOCKED),),
            ),
        ),
        reasons=(),
        summary={"SKIP": 1, "BLOCKED": 1},
    )
    explanation = explain_plan(plan)
    serialized = explanation.to_dict()
    assert explanation.kind == PLAN_EXPLANATION_KIND
    assert explanation.schema_version == PLAN_EXPLANATION_SCHEMA_VERSION
    assert explanation.stage_explanations[1].pending_inputs
    assert PlanExplanation.from_dict(serialized) == explanation
    assert explanation.to_dict() == serialized
    assert _is_plain_data(serialized)


def _is_plain_data(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_plain_data(item) for item in value)
    if isinstance(value, tuple):
        return all(_is_plain_data(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _is_plain_data(val)
            for key, val in value.items()
        )
    return False
