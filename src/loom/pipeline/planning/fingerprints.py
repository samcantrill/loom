"""Stage fingerprint construction for deterministic planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.pipeline.specs import OutputSpec, StageSpec
from loom.serialization import PlainData

from .errors import StageFingerprintError
from .models import (
    DEFAULT_FINGERPRINT_ALGORITHM,
    STAGE_FINGERPRINT_POLICY_NAME,
    STAGE_FINGERPRINT_POLICY_VERSION,
    STAGE_FINGERPRINT_SCHEMA_VERSION,
    FingerprintContext,
    StageFingerprintPayload,
    StageFingerprintRecord,
)


def build_stage_fingerprint(
    stage: StageSpec,
    *,
    bound_inputs: Mapping[str, ArtifactRef],
    fingerprint_context: FingerprintContext | None = None,
) -> StageFingerprintRecord:
    """Build a deterministic semantic fingerprint for a stage invocation."""

    context = fingerprint_context or FingerprintContext()
    missing_inputs = tuple(
        input_name for input_name in stage.inputs if input_name not in bound_inputs
    )
    if missing_inputs:
        missing = ", ".join(missing_inputs)
        raise StageFingerprintError(
            f"stage {stage.name!r} has pending input(s): {missing}"
        )
    unexpected_inputs = tuple(
        input_name for input_name in bound_inputs if input_name not in stage.inputs
    )
    if unexpected_inputs:
        unexpected = ", ".join(sorted(unexpected_inputs))
        raise StageFingerprintError(
            f"stage {stage.name!r} received undeclared bound input(s): {unexpected}"
        )

    normalized_inputs = {
        input_name: _artifact_identity(
            ref,
            source_stage=stage.inputs[input_name].split(".", 1)[0],
            source_output=stage.inputs[input_name].split(".", 1)[1],
        )
        for input_name, ref in sorted(bound_inputs.items())
    }
    normalized_outputs = {
        name: _output_spec_identity(output)
        for name, output in sorted(stage.outputs.items())
    }
    payload = StageFingerprintPayload(
        schema_version=STAGE_FINGERPRINT_SCHEMA_VERSION,
        policy_name=context.policy_name,
        policy_version=context.policy_version,
        stage_name=stage.name,
        factory_target=stage.target_path,
        factory_init=stage.factory.init,
        stage_config=stage.stage_config,
        fingerprint_fields=stage.fingerprint_fields,
        declared_inputs=dict(sorted(stage.inputs.items())),
        bound_inputs=normalized_inputs,
        declared_outputs=normalized_outputs,
        python_version=context.resolved_python_version(),
        loom_version=context.resolved_loom_version(),
        git=context.git,
        dependencies=dict(sorted(context.dependencies.items())),
        extra=context.extra,
    )
    algorithm = context.algorithm or DEFAULT_FINGERPRINT_ALGORITHM
    digest = hash_mapping(payload.to_hash_input(), algorithm=algorithm)
    return StageFingerprintRecord(
        schema_version=STAGE_FINGERPRINT_SCHEMA_VERSION,
        algorithm=algorithm,
        policy_name=context.policy_name or STAGE_FINGERPRINT_POLICY_NAME,
        policy_version=context.policy_version or STAGE_FINGERPRINT_POLICY_VERSION,
        fingerprint=digest,
        payload=payload,
        inputs_summary=_inputs_summary(stage, bound_inputs, context),
    )


def _artifact_identity(
    ref: ArtifactRef, *, source_stage: str, source_output: str
) -> dict[str, PlainData]:
    return {
        "source_stage": source_stage,
        "source_output": source_output,
        "artifact_id": ref.artifact_id,
        "artifact_type": ref.artifact_type,
        "codec_key": ref.codec_key,
        "schema_version": ref.schema_version,
        "checksum": ref.checksum,
        "fingerprint": ref.fingerprint,
        "producer_stage": ref.producer_stage,
        "metadata": dict(ref.metadata),
    }


def _output_spec_identity(output_spec: OutputSpec) -> dict[str, PlainData]:
    return {
        "artifact_type": output_spec.artifact_type,
        "codec_key": output_spec.codec_key,
        "schema_version": output_spec.schema_version,
        "metadata": dict(output_spec.metadata),
    }


def _inputs_summary(
    stage: StageSpec,
    bound_inputs: Mapping[str, ArtifactRef],
    context: FingerprintContext,
) -> dict[str, PlainData]:
    input_artifacts: dict[str, PlainData] = {}
    for input_name, ref in sorted(bound_inputs.items()):
        source = stage.inputs.get(input_name, "")
        input_artifacts[input_name] = {
            "source": source,
            "artifact_id": ref.artifact_id,
            "checksum": ref.checksum,
            "fingerprint": ref.fingerprint,
        }
    return cast(
        dict[str, PlainData],
        {
            "stage_name": stage.name,
            "factory_target": stage.target_path,
            "input_names": sorted(stage.inputs),
            "output_names": sorted(stage.outputs),
            "input_artifacts": input_artifacts,
            "python_version": context.resolved_python_version(),
            "loom_version": context.resolved_loom_version(),
            "git": dict(context.git),
            "dependency_names": sorted(context.dependencies),
            "extra_keys": sorted(context.extra),
        },
    )


__all__ = ["build_stage_fingerprint"]
