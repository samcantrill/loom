"""Input binding helpers for static pipeline graphs."""

from __future__ import annotations

from dataclasses import dataclass

from loom.ids import StageID
from loom.pipeline.errors import InputBindingError, PipelineSpecError

from loom.pipeline.specs import PipelineSpec, OutputSpec, _validate_identifier


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    stage_id: StageID
    output_name: str


@dataclass(frozen=True, slots=True)
class ResolvedInputBinding:
    consumer_stage_id: StageID
    input_name: str
    source_stage_id: StageID
    source_output_name: str
    source_output_spec: "OutputSpec"


def parse_artifact_reference(value: str) -> ArtifactReference:
    if not isinstance(value, str) or not value:
        raise InputBindingError("input references must be non-empty strings")
    if value.count(".") != 1:
        raise InputBindingError(f"invalid artifact reference '{value}'; expected exactly one '.': 'stage.output'")
    stage_id, output_name = value.split(".", 1)
    if not stage_id or not output_name:
        raise InputBindingError(f"invalid artifact reference '{value}'; expected 'stage.output'")
    _validate_identifier(
        stage_id,
        kind="stage identifier",
        path=f"{value} (stage)",
    )
    _validate_identifier(
        output_name,
        kind="output name",
        path=f"{value} (output)",
    )
    return ArtifactReference(stage_id=stage_id, output_name=output_name)


def bind_stage_inputs(stage_id: StageID, spec: PipelineSpec) -> dict[str, ResolvedInputBinding]:
    try:
        stage = spec.get_stage(stage_id)
    except PipelineSpecError as exc:
        raise InputBindingError(f"unknown stage '{stage_id}'") from exc
    outputs_by_stage = {stage.name: stage.outputs for stage in spec.stages}

    bindings: dict[str, ResolvedInputBinding] = {}
    for input_name, target in stage.inputs.items():
        try:
            reference = parse_artifact_reference(target)
        except InputBindingError as exc:
            raise InputBindingError(f"stage '{stage_id}' input '{input_name}' has invalid reference: {exc}") from exc

        source = reference.stage_id
        if source not in outputs_by_stage:
            raise InputBindingError(
                f"stage '{stage_id}' input '{input_name}' references unknown stage '{source}'",
            )
        if source == stage_id:
            raise InputBindingError(
                f"stage '{stage_id}' input '{input_name}' cannot reference its own output",
            )
        output_name = reference.output_name
        source_outputs = outputs_by_stage[source]
        if output_name not in source_outputs:
            raise InputBindingError(
                f"stage '{stage_id}' input '{input_name}' references unknown output '{source}.{output_name}'",
            )

        bindings[input_name] = ResolvedInputBinding(
            consumer_stage_id=stage_id,
            input_name=input_name,
            source_stage_id=source,
            source_output_name=output_name,
            source_output_spec=source_outputs[output_name],
        )
    return bindings


def resolve_input_bindings(spec: PipelineSpec) -> dict[StageID, dict[str, ResolvedInputBinding]]:
    resolved: dict[StageID, dict[str, ResolvedInputBinding]] = {}
    for stage in spec.stages:
        resolved[stage.name] = bind_stage_inputs(stage.name, spec)
    return resolved


__all__ = [
    "ArtifactReference",
    "ResolvedInputBinding",
    "parse_artifact_reference",
    "bind_stage_inputs",
    "resolve_input_bindings",
]
