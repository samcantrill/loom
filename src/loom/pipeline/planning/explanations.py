"""Plan explanation models derived from execution plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loom.artifacts import ArtifactRef

from .errors import PlanSerializationError
from .models import (
    BoundInput,
    ExecutionPlan,
    FingerprintStatus,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    PlanSelectors,
    PendingInput,
    ResumeCheck,
    ResumeOptions,
    StagePlan,
    bound_input_mapping,
    reject_unknown,
    reason_code_tuple,
    reason_tuple,
    require_fields,
    require_mapping,
    require_str,
)

PLAN_EXPLANATION_SCHEMA_VERSION = 1
PLAN_EXPLANATION_KIND = "loom.plan_explanation"


@dataclass(frozen=True, slots=True)
class StageExplanation:
    stage_name: str
    action: PlanAction
    base_action: PlanAction
    fingerprint_status: FingerprintStatus
    reason_codes: tuple[PlanReasonCode, ...]
    reasons: tuple[PlanReason, ...]
    selector_reasons: tuple[PlanReasonCode, ...]
    invalidation_reasons: tuple[PlanReason, ...]
    resume_reasons: tuple[PlanReason, ...]
    pending_inputs: tuple[PendingInput, ...]
    bound_inputs: dict[str, BoundInput]
    reusable_outputs: dict[str, ArtifactRef]
    upstream_stages: tuple[str, ...]
    downstream_stages: tuple[str, ...]
    prior_fingerprint: str | None
    current_fingerprint: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_name": self.stage_name,
            "action": self.action.value,
            "base_action": self.base_action.value,
            "fingerprint_status": self.fingerprint_status.value,
            "reason_codes": [code.value for code in self.reason_codes],
            "reasons": [reason.to_dict() for reason in self.reasons],
            "selector_reasons": [code.value for code in self.selector_reasons],
            "invalidation_reasons": [
                reason.to_dict() for reason in self.invalidation_reasons
            ],
            "resume_reasons": [reason.to_dict() for reason in self.resume_reasons],
            "pending_inputs": [item.to_dict() for item in self.pending_inputs],
            "bound_inputs": {
                name: item.to_dict() for name, item in self.bound_inputs.items()
            },
            "reusable_outputs": {
                name: ref.to_dict() for name, ref in self.reusable_outputs.items()
            },
            "upstream_stages": list(self.upstream_stages),
            "downstream_stages": list(self.downstream_stages),
            "prior_fingerprint": self.prior_fingerprint,
            "current_fingerprint": self.current_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageExplanation":
        mapping = require_mapping(data, "StageExplanation")
        allowed = {
            "stage_name",
            "action",
            "base_action",
            "fingerprint_status",
            "reason_codes",
            "reasons",
            "selector_reasons",
            "invalidation_reasons",
            "resume_reasons",
            "pending_inputs",
            "bound_inputs",
            "reusable_outputs",
            "upstream_stages",
            "downstream_stages",
            "prior_fingerprint",
            "current_fingerprint",
        }
        reject_unknown(mapping, allowed, "StageExplanation")
        require_fields(mapping, allowed, "StageExplanation")
        return cls(
            stage_name=require_str(mapping["stage_name"], "stage_name"),
            action=PlanAction(mapping["action"]),
            base_action=PlanAction(mapping["base_action"]),
            fingerprint_status=FingerprintStatus(mapping["fingerprint_status"]),
            reason_codes=reason_code_tuple(mapping["reason_codes"], "reason_codes"),
            reasons=reason_tuple(mapping["reasons"], "reasons"),
            selector_reasons=reason_code_tuple(
                mapping["selector_reasons"], "selector_reasons"
            ),
            invalidation_reasons=reason_tuple(
                mapping["invalidation_reasons"], "invalidation_reasons"
            ),
            resume_reasons=reason_tuple(mapping["resume_reasons"], "resume_reasons"),
            pending_inputs=tuple(
                PendingInput.from_dict(item)
                for item in _sequence(mapping["pending_inputs"], "pending_inputs")
            ),
            bound_inputs=bound_input_mapping(mapping["bound_inputs"], "bound_inputs"),
            reusable_outputs={
                require_str(name, "reusable_outputs key"): ArtifactRef.from_dict(value)
                for name, value in require_mapping(
                    mapping["reusable_outputs"], "reusable_outputs"
                ).items()
            },
            upstream_stages=_string_tuple(mapping["upstream_stages"], "upstream_stages"),
            downstream_stages=_string_tuple(
                mapping["downstream_stages"],
                "downstream_stages",
            ),
            prior_fingerprint=_optional_string(
                mapping["prior_fingerprint"], "prior_fingerprint"
            ),
            current_fingerprint=_optional_string(
                mapping["current_fingerprint"], "current_fingerprint"
            ),
        )


@dataclass(frozen=True, slots=True)
class PlanExplanation:
    schema_version: int
    kind: str
    run_id: str
    pipeline_name: str | None
    selectors: PlanSelectors
    resume: ResumeOptions
    stage_order: tuple[str, ...]
    stage_explanations: tuple[StageExplanation, ...]
    summary: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "selectors": self.selectors.to_dict(),
            "resume": self.resume.to_dict(),
            "stage_order": list(self.stage_order),
            "stages": [explanation.to_dict() for explanation in self.stage_explanations],
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PlanExplanation":
        mapping = require_mapping(data, "PlanExplanation")
        allowed = {
            "schema_version",
            "kind",
            "run_id",
            "pipeline_name",
            "selectors",
            "resume",
            "stage_order",
            "stages",
            "summary",
        }
        reject_unknown(mapping, allowed, "PlanExplanation")
        require_fields(mapping, allowed, "PlanExplanation")
        return cls(
            schema_version=_schema_version(mapping["schema_version"]),
            kind=_kind(mapping["kind"]),
            run_id=require_str(mapping["run_id"], "run_id"),
            pipeline_name=_optional_string(mapping["pipeline_name"], "pipeline_name"),
            selectors=PlanSelectors.from_dict(mapping["selectors"]),
            resume=ResumeOptions.from_dict(mapping["resume"]),
            stage_order=_string_tuple(mapping["stage_order"], "stage_order"),
            stage_explanations=tuple(
                StageExplanation.from_dict(item)
                for item in _sequence(mapping["stages"], "stages")
            ),
            summary=_int_mapping(mapping["summary"], "summary"),
        )


def explain_plan(plan: ExecutionPlan) -> PlanExplanation:
    explanations = tuple(
        _explain_stage(stage=stage) for stage in plan.ordered_stage_plans
    )
    return PlanExplanation(
        schema_version=PLAN_EXPLANATION_SCHEMA_VERSION,
        kind=PLAN_EXPLANATION_KIND,
        run_id=plan.run_id,
        pipeline_name=plan.pipeline_name,
        selectors=plan.selectors,
        resume=plan.resume,
        stage_order=plan.stage_order,
        stage_explanations=explanations,
        summary=dict(plan.summary),
    )


def _explain_stage(*, stage: StagePlan) -> StageExplanation:
    resume_check: ResumeCheck | None = stage.resume_check
    return StageExplanation(
        stage_name=stage.stage_name,
        action=stage.action,
        base_action=stage.base_action,
        fingerprint_status=stage.fingerprint_status,
        reason_codes=tuple(reason.code for reason in stage.reasons),
        reasons=stage.reasons,
        selector_reasons=stage.selected_by,
        invalidation_reasons=stage.invalidated_by,
        resume_reasons=tuple(resume_check.reasons) if resume_check else (),
        pending_inputs=stage.pending_inputs,
        bound_inputs=dict(stage.bound_inputs),
        reusable_outputs=dict(stage.reusable_outputs),
        upstream_stages=stage.upstream_stages,
        downstream_stages=stage.downstream_stages,
        prior_fingerprint=(
            resume_check.prior_fingerprint.fingerprint
            if resume_check and resume_check.prior_fingerprint
            else None
        ),
        current_fingerprint=(
            resume_check.current_fingerprint.fingerprint
            if resume_check and resume_check.current_fingerprint
            else None
        ),
    )


def _schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanSerializationError("PlanExplanation.schema_version must be an integer")
    if value != PLAN_EXPLANATION_SCHEMA_VERSION:
        raise PlanSerializationError(
            "PlanExplanation.schema_version must be "
            f"{PLAN_EXPLANATION_SCHEMA_VERSION}, got {value!r}",
        )
    return value


def _kind(value: object) -> str:
    kind = require_str(value, "kind")
    if kind != PLAN_EXPLANATION_KIND:
        raise PlanSerializationError(
            f"PlanExplanation.kind must be {PLAN_EXPLANATION_KIND!r}"
        )
    return kind


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanSerializationError(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    return tuple(require_str(item, f"{field} item") for item in _sequence(value, field))


def _optional_string(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    return require_str(value, field)


def _int_mapping(value: object, field: str) -> dict[str, int]:
    mapping = require_mapping(value, field)
    result: dict[str, int] = {}
    for key, item in mapping.items():
        key_text = require_str(key, f"{field} key")
        if isinstance(item, bool) or not isinstance(item, int):
            raise PlanSerializationError(f"{field}[{key_text!r}] must be an integer")
        result[key_text] = item
    return result


__all__ = [
    "PLAN_EXPLANATION_SCHEMA_VERSION",
    "PLAN_EXPLANATION_KIND",
    "StageExplanation",
    "PlanExplanation",
    "explain_plan",
]
