"""Pipeline-owned validation and opt-in stage target checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from loom.pipeline.errors import PipelineSpecError
from loom.pipeline.graph import StageGraph, build_stage_graph
from loom.pipeline.specs import PipelineSpec, parse_pipeline_config
from loom.pipeline.resources import ResourceValidatorRegistry
from loom.pipeline.stage_factory import construct_stage


@dataclass(frozen=True, slots=True)
class PipelineValidationResult:
    """Structured facts from static pipeline validation."""

    spec: PipelineSpec
    graph: StageGraph
    stage_count: int
    pipeline_name: str | None
    stage_factory_target_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PipelineTargetCheckResult:
    """Summary of constructed pipeline stage factory targets."""

    target_count: int
    checked_paths: tuple[str, ...]


def validate_pipeline_config(
    config: Mapping[str, object],
    *,
    registry: ResourceValidatorRegistry | None = None,
) -> PipelineValidationResult:
    """Validate a resolved top-level config and return pipeline facts."""

    if not isinstance(config, Mapping):
        raise PipelineSpecError("$.config must be a mapping")
    if "pipeline" not in config:
        raise PipelineSpecError("$.pipeline is required")

    spec = parse_pipeline_config(config["pipeline"], registry=registry)
    graph = build_stage_graph(spec)
    stage_factory_target_paths = tuple(
        f"$.pipeline.stages[{index}].factory"
        for index, _stage in enumerate(spec.stages)
    )
    return PipelineValidationResult(
        spec=spec,
        graph=graph,
        stage_count=len(spec.stages),
        pipeline_name=spec.name,
        stage_factory_target_paths=stage_factory_target_paths,
    )


def check_pipeline_stage_targets(spec: PipelineSpec) -> PipelineTargetCheckResult:
    """Construct configured stage factory targets and discard the stages."""

    checked_paths: list[str] = []
    for index, stage in enumerate(spec.stages):
        stage_path = f"$.pipeline.stages[{index}]"
        construct_stage(factory=stage.factory, stage_path=stage_path)
        checked_paths.append(f"{stage_path}.factory")
    return PipelineTargetCheckResult(
        target_count=len(checked_paths),
        checked_paths=tuple(checked_paths),
    )


__all__ = [
    "PipelineTargetCheckResult",
    "PipelineValidationResult",
    "check_pipeline_stage_targets",
    "validate_pipeline_config",
]
