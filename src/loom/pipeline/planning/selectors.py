"""Selector normalization and eligibility rules for planning."""

from __future__ import annotations

from dataclasses import dataclass

from loom.pipeline.graph import (
    StageGraph,
    topological_sort,
    transitive_downstream,
    transitive_upstream,
)
from loom.pipeline.specs import PipelineSpec

from .errors import SelectorValidationError
from .models import PlanReason, PlanReasonCode, PlanSelectors


@dataclass(frozen=True, slots=True)
class Selection:
    selectors: PlanSelectors
    stage_order: tuple[str, ...]
    eligible_stages: frozenset[str]
    reusable_provider_stages: frozenset[str]
    skipped_stages: frozenset[str]
    outside_only_stages: frozenset[str]
    forced_stages: frozenset[str]
    from_stage_closure: frozenset[str]
    only_stages: frozenset[str]

    def is_eligible(self, stage_name: str) -> bool:
        return stage_name in self.eligible_stages

    def is_reuse_provider(self, stage_name: str) -> bool:
        return stage_name in self.reusable_provider_stages

    def reason_for_selection(self, stage_name: str) -> tuple[PlanReasonCode, ...]:
        codes: list[PlanReasonCode] = []
        if stage_name in self.forced_stages:
            codes.append(PlanReasonCode.FORCED_BY_SELECTOR)
        if self.selectors.from_stage == stage_name:
            codes.append(PlanReasonCode.FROM_STAGE_SELECTED)
        if stage_name in self.only_stages:
            codes.append(PlanReasonCode.ONLY_STAGE_SELECTED)
        if stage_name in self.skipped_stages:
            codes.append(PlanReasonCode.SKIPPED_BY_SELECTOR)
        if stage_name in self.outside_only_stages:
            codes.append(PlanReasonCode.OUTSIDE_ONLY_SELECTION)
        return tuple(codes)


def normalize_selectors(
    selectors: PlanSelectors | None,
    *,
    spec: PipelineSpec,
    graph: StageGraph,
) -> Selection:
    raw = selectors or PlanSelectors()
    order = tuple(topological_sort(graph))
    known = set(spec.stage_names)

    force = _normalize_field(
        raw.force_stages, field="force_stages", known=known, order=order
    )
    only = _normalize_field(
        raw.only_stages, field="only_stages", known=known, order=order
    )
    skip = _normalize_field(
        raw.skip_stages, field="skip_stages", known=known, order=order
    )
    from_stage = raw.from_stage
    if from_stage is not None and from_stage not in known:
        raise SelectorValidationError(
            f"from_stage references unknown stage {from_stage!r}"
        )

    if from_stage is not None and only:
        raise SelectorValidationError(
            "from_stage and only_stages are mutually exclusive in v0"
        )
    _reject_intersection("skip_stages", skip, "force_stages", force)
    _reject_intersection("skip_stages", skip, "only_stages", only)
    if from_stage is not None and from_stage in skip:
        raise SelectorValidationError("skip_stages cannot include from_stage")

    from_closure: set[str] = set()
    if from_stage is not None:
        from_closure = {from_stage, *transitive_downstream(graph, from_stage)}
        if not set(force).issubset(from_closure):
            raise SelectorValidationError(
                "force_stages cannot widen from_stage eligibility"
            )

    if only and not set(force).issubset(set(only)):
        raise SelectorValidationError(
            "force_stages must be contained in only_stages when combined"
        )

    if only:
        eligible = set(only)
        providers: set[str] = set()
        for stage_name in only:
            providers.update(transitive_upstream(graph, stage_name))
        providers.difference_update(eligible)
        outside_only = known - eligible - providers
    elif from_stage is not None:
        eligible = set(from_closure)
        providers = set()
        for stage_name in eligible:
            providers.update(transitive_upstream(graph, stage_name))
        providers.difference_update(eligible)
        outside_only = set()
    else:
        eligible = set(known)
        providers = set()
        outside_only = set()

    eligible.difference_update(skip)
    providers.difference_update(skip)
    skipped = set(skip)

    normalized = PlanSelectors(
        force_stages=tuple(stage for stage in order if stage in force),
        from_stage=from_stage,
        only_stages=tuple(stage for stage in order if stage in only),
        skip_stages=tuple(stage for stage in order if stage in skip),
    )
    return Selection(
        selectors=normalized,
        stage_order=order,
        eligible_stages=frozenset(stage for stage in order if stage in eligible),
        reusable_provider_stages=frozenset(
            stage for stage in order if stage in providers
        ),
        skipped_stages=frozenset(stage for stage in order if stage in skipped),
        outside_only_stages=frozenset(
            stage for stage in order if stage in outside_only
        ),
        forced_stages=frozenset(stage for stage in order if stage in force),
        from_stage_closure=frozenset(stage for stage in order if stage in from_closure),
        only_stages=frozenset(stage for stage in order if stage in only),
    )


def selector_reason(code: PlanReasonCode, stage_name: str) -> PlanReason:
    return PlanReason(
        code=code,
        message=_SELECTOR_MESSAGES[code],
        stage_name=stage_name,
    )


def _normalize_field(
    stages: tuple[str, ...],
    *,
    field: str,
    known: set[str],
    order: tuple[str, ...],
) -> tuple[str, ...]:
    unknown = sorted(set(stages) - known)
    if unknown:
        raise SelectorValidationError(
            f"{field} references unknown stage(s): {', '.join(unknown)}"
        )
    seen: set[str] = set()
    for stage in stages:
        seen.add(stage)
    return tuple(stage for stage in order if stage in seen)


def _reject_intersection(
    left_name: str, left: tuple[str, ...], right_name: str, right: tuple[str, ...]
) -> None:
    overlap = sorted(set(left) & set(right))
    if overlap:
        raise SelectorValidationError(
            f"{left_name} cannot overlap {right_name}: {', '.join(overlap)}",
        )


_SELECTOR_MESSAGES = {
    PlanReasonCode.FORCED_BY_SELECTOR: "stage forced by selector",
    PlanReasonCode.FROM_STAGE_SELECTED: "stage selected by from_stage",
    PlanReasonCode.ONLY_STAGE_SELECTED: "stage selected by only_stages",
    PlanReasonCode.OUTSIDE_ONLY_SELECTION: "stage outside only_stages selection",
    PlanReasonCode.SKIPPED_BY_SELECTOR: "stage skipped by selector",
}


__all__ = ["Selection", "normalize_selectors", "selector_reason"]
