"""Pipeline-owned structural validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from loom.pipeline.errors import PipelineSpecError
from loom.pipeline.graph import StageGraph, build_stage_graph
from loom.pipeline.specs import PipelineSpec, parse_pipeline_config
from loom.pipeline.resources import ResourceValidatorRegistry


@dataclass(frozen=True, slots=True)
class PipelineValidationResult:
    """Structured facts from static pipeline validation."""

    spec: PipelineSpec
    graph: StageGraph
    stage_count: int
    pipeline_name: str | None
    stage_factory_target_paths: tuple[str, ...]


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


__all__ = [
    "PipelineValidationResult",
    "validate_pipeline_config",
]
