"""Stage output validation for execution commits."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.specs import StageSpec
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError

from .errors import OutputValidationError


def validate_stage_outputs(
    *,
    stage: StageSpec,
    outputs: Mapping[str, object],
    artifact_store: ArtifactStore,
) -> dict[str, ArtifactRef]:
    if not isinstance(stage, StageSpec):
        raise OutputValidationError("stage must be a StageSpec")
    if not isinstance(outputs, Mapping):
        raise OutputValidationError(
            f"pipeline.stages.{stage.name}.outputs: returned outputs must be a mapping"
        )

    for output_name in outputs:
        if not isinstance(output_name, str) or not output_name:
            raise OutputValidationError(
                f"pipeline.stages.{stage.name}.outputs returned output names must be non-empty strings"
            )

    declared = set(stage.outputs)
    returned = set(outputs)
    missing = declared - returned
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise OutputValidationError(
            f"pipeline.stages.{stage.name}.outputs missing declared output(s): {missing_text}"
        )
    extra = returned - declared
    if extra:
        extra_text = ", ".join(sorted(extra))
        raise OutputValidationError(
            f"pipeline.stages.{stage.name}.outputs returned undeclared output(s): {extra_text}"
        )

    normalized: dict[str, ArtifactRef] = {}
    for output_name, output_spec in stage.outputs.items():
        value = outputs[output_name]
        path = f"pipeline.stages.{stage.name}.outputs.{output_name}"
        if not isinstance(value, ArtifactRef):
            raise OutputValidationError(f"{path} must be an ArtifactRef")
        if value.artifact_type != output_spec.artifact_type:
            raise OutputValidationError(
                f"{path} artifact_type mismatch: expected {output_spec.artifact_type!r}, got {value.artifact_type!r}"
            )
        if (
            output_spec.codec_key is not None
            and value.codec_key != output_spec.codec_key
        ):
            raise OutputValidationError(
                f"{path} codec_key mismatch: expected {output_spec.codec_key!r}, got {value.codec_key!r}"
            )
        if (
            output_spec.schema_version is not None
            and value.schema_version != output_spec.schema_version
        ):
            raise OutputValidationError(
                f"{path} schema_version mismatch: expected {output_spec.schema_version}, got {value.schema_version}"
            )
        if value.producer_stage is not None and value.producer_stage != stage.name:
            raise OutputValidationError(
                f"{path} producer_stage mismatch: expected {stage.name!r}, got {value.producer_stage!r}"
            )
        try:
            artifact_store.validate(value, expected_type=output_spec.artifact_type)
        except ArtifactStoreError as exc:
            raise OutputValidationError(
                f"{path} artifact validation failed: {exc}"
            ) from exc
        normalized[output_name] = value
    return normalized


__all__ = ["validate_stage_outputs"]
